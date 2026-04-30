use crate::error::{FinError, Result};
use crate::importers::credit_card_csv::{import_csv, import_directory};
use crate::llm::chat_completion;
use crate::services::ask_context::{
    build_ask_prompt, build_finance_context, card_billing_month, refresh_card_unbilled,
};
use crate::services::manual_snapshots::{
    cash_add, cash_out, set_bank_total, set_securities_total, set_wallet_total,
};
use crate::services::now::{show_card, show_now, show_wallet};
use crate::services::snapshots::format_snapshot;
use crate::services::transfers::transfer;
use rusqlite::Connection;
use std::path::Path;

fn parse_amount(raw: &str, allow_zero: bool) -> Result<i64> {
    let amount: i64 = raw
        .parse()
        .map_err(|_| FinError::invalid(format!("金額は整数で指定してください: {}", raw)))?;
    if allow_zero && amount < 0 {
        return Err(FinError::invalid("金額は0以上で指定してください"));
    }
    if !allow_zero && amount <= 0 {
        return Err(FinError::invalid("金額は1以上で指定してください"));
    }
    Ok(amount)
}

pub fn handle_command(conn: &Connection, command_line: &str) -> Result<String> {
    let parts = match shlex::split(command_line) {
        Some(p) => p,
        None => return Err(FinError::invalid("コマンドの解析に失敗しました")),
    };
    if parts.is_empty() {
        return Ok(String::new());
    }

    match parts[0].as_str() {
        "/now" => Ok(show_now(conn)?),

        "/set-bank" => {
            if parts.len() != 2 {
                return Err(FinError::invalid("使い方: /set-bank <amount>"));
            }
            let amount = parse_amount(&parts[1], true)?;
            let snap = set_bank_total(conn, amount)?;
            Ok(format!(
                "銀行残高を更新しました\n{}",
                format_snapshot(&snap)
            ))
        }

        "/set-securities" => {
            if parts.len() != 2 {
                return Err(FinError::invalid("使い方: /set-securities <amount>"));
            }
            let amount = parse_amount(&parts[1], true)?;
            let snap = set_securities_total(conn, amount)?;
            Ok(format!(
                "証券評価額を更新しました\n{}",
                format_snapshot(&snap)
            ))
        }

        "/cash-set" => {
            if parts.len() != 2 {
                return Err(FinError::invalid("使い方: /cash-set <amount>"));
            }
            let amount = parse_amount(&parts[1], true)?;
            let snap = set_wallet_total(conn, amount)?;
            Ok(format!(
                "財布残高を設定しました\n{}",
                format_snapshot(&snap)
            ))
        }

        "/cash-in" => {
            if parts.len() < 3 {
                return Err(FinError::invalid("使い方: /cash-in <amount> <memo>"));
            }
            let amount = parse_amount(&parts[1], false)?;
            let memo = parts[2..].join(" ");
            let snap = cash_add(conn, amount, &memo)?;
            Ok(format!(
                "財布に {}円 追加しました: {}\n{}",
                crate::models::format_amount(amount),
                memo,
                format_snapshot(&snap)
            ))
        }

        "/cash-out" => {
            if parts.len() < 3 {
                return Err(FinError::invalid("使い方: /cash-out <amount> <memo>"));
            }
            let amount = parse_amount(&parts[1], false)?;
            let memo = parts[2..].join(" ");
            let snap = cash_out(conn, amount, &memo)?;
            Ok(format!(
                "財布から {}円 支出しました: {}\n{}",
                crate::models::format_amount(amount),
                memo,
                format_snapshot(&snap)
            ))
        }

        "/cash" => Ok(show_wallet(conn, 10)?),

        "/import-card" | "/import" => {
            let path = parts.get(1).map(Path::new);
            let (result, label) = if let Some(p) = path {
                if p.is_file() {
                    let r = import_csv(conn, p)?;
                    let result = crate::models::ImportResult {
                        files: 1,
                        imported: r.imported,
                        skipped: r.skipped,
                        skipped_rows: r.skipped_rows,
                        errors: vec![],
                    };
                    (result, "1ファイルを走査".to_string())
                } else {
                    let r = import_directory(conn, Some(p))?;
                    let label = format!("{}ファイルを走査", r.files);
                    (r, label)
                }
            } else {
                let r = import_directory(conn, None)?;
                let label = format!("{}ファイルを走査", r.files);
                (r, label)
            };

            let snap = refresh_card_unbilled(conn, &card_billing_month())?;
            let mut lines = vec![format!(
                "{}: {}件取り込み / {}件スキップ(重複)",
                label, result.imported, result.skipped
            )];
            if result.skipped_rows > 0 && !result.errors.iter().any(|e| e.contains("行をスキップ"))
            {
                lines.push(format!("  WARN: {}行をスキップ", result.skipped_rows));
            }
            for err in &result.errors {
                lines.push(format!("  ERROR: {}", err));
            }
            lines.push(format_snapshot(&snap));
            Ok(lines.join("\n"))
        }

        "/card" => {
            let arg = parts.get(1).map(|s| s.as_str()).unwrap_or("this_month");
            let month = if arg == "this_month" {
                card_billing_month()
            } else {
                arg.to_string()
            };
            Ok(show_card(conn, &month)?)
        }

        "/atm" => {
            if parts.len() < 2 {
                return Err(FinError::invalid("使い方: /atm <amount> [memo]"));
            }
            let amount = parse_amount(&parts[1], false)?;
            let memo = if parts.len() > 2 {
                parts[2..].join(" ")
            } else {
                "ATM引き出し".to_string()
            };
            let result = transfer(conn, "bank", "wallet", amount, Some(&memo))?;
            Ok(format!(
                "銀行から財布へ {}円を移しました ({})\n総資産は変わりません\n{}",
                crate::models::format_amount(amount),
                memo,
                format_snapshot(&result.snapshot)
            ))
        }

        "/transfer" => {
            if parts.len() < 4 {
                return Err(FinError::invalid(
                    "使い方: /transfer <from> <to> <amount> [memo]",
                ));
            }
            let from_account = &parts[1];
            let to_account = &parts[2];
            let amount = parse_amount(&parts[3], false)?;
            let memo = if parts.len() > 4 {
                Some(parts[4..].join(" "))
            } else {
                None
            };
            let result = transfer(conn, from_account, to_account, amount, memo.as_deref())?;
            let memo_str = memo.map(|m| format!(" ({})", m)).unwrap_or_default();
            Ok(format!(
                "{} から {} へ {}円を移しました{}\n総資産は変わりません\n{}",
                from_account,
                to_account,
                crate::models::format_amount(amount),
                memo_str,
                format_snapshot(&result.snapshot)
            ))
        }

        "/ask" => {
            if parts.len() < 2 {
                return Err(FinError::invalid("/ask <質問> の形式で指定してください"));
            }
            let question = parts[1..].join(" ");
            let context = build_finance_context(conn, &question)?;
            let prompt = build_ask_prompt(&context, &question);
            eprintln!("LLMに問い合わせ中です、お待ちください...");
            let response = chat_completion(&prompt).map_err(|e| FinError::Other(e.to_string()))?;
            Ok(response)
        }

        "/help" => Ok("── コマンド一覧 ──\n\
                  /now                       現在の資産状況\n\
                  /set-bank <amount>         銀行残高を更新\n\
                  /set-securities <amount>   証券評価額を更新\n\
                  /cash-set <amount>         財布残高を補正\n\
                  /cash-in <amount> <memo>   財布に入金\n\
                  /cash-out <amount> <memo>  財布から支出\n\
                  /cash                      財布の取引履歴\n\
                  /atm <amount> [memo]       銀行→財布へATM引き出し\n\
                  /transfer <from> <to> <amount> [memo]  振替\n\
                  /import-card [dir]         カードCSVを一括取り込み\n\
                  /import [dir]              /import-card の別名\n\
                  /card [this_month|YYYY-MM] カード利用集計（this_monthは支払月ベース）\n\
                  /ask <質問>                LLMに分析を依頼\n\
                  /help                      このヘルプを表示"
            .to_string()),

        cmd => Err(FinError::invalid(format!("未対応コマンドです: {}", cmd))),
    }
}
