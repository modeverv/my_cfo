use crate::error::{FinError, Result};
use crate::models::Snapshot;
use crate::services::snapshots::{get_latest_snapshot, insert_snapshot, SnapshotBuilder};
use rusqlite::Connection;

fn resolve_account(key: &str) -> Result<&'static str> {
    match key.to_lowercase().as_str() {
        "bank" | "bank_main" => Ok("bank"),
        "wallet" | "wallet_main" => Ok("wallet"),
        "securities" | "sbi_main" => Ok("securities"),
        "card" | "card_main" => Ok("card"),
        _ => Err(FinError::invalid(format!(
            "不明な口座キー: {}  (使用可能: bank, wallet, securities, card)",
            key
        ))),
    }
}

fn ensure_balance(current: i64, amount: i64, label: &str) -> Result<()> {
    if current - amount < 0 {
        return Err(FinError::invalid(format!(
            "{}が不足しています (現在: {}円)",
            label,
            crate::models::format_amount(current)
        )));
    }
    Ok(())
}

pub struct TransferResult {
    pub transfer_id: i64,
    pub snapshot: Snapshot,
}

pub fn transfer(
    conn: &Connection,
    from_key: &str,
    to_key: &str,
    amount: i64,
    memo: Option<&str>,
) -> Result<TransferResult> {
    let from_account = resolve_account(from_key)?;
    let to_account = resolve_account(to_key)?;

    if amount <= 0 {
        return Err(FinError::invalid("振替金額は1円以上で指定してください"));
    }
    if from_account == to_account {
        return Err(FinError::invalid("振替元と振替先が同じ口座です"));
    }

    let latest = get_latest_snapshot(conn)?;

    let mut builder = SnapshotBuilder::default();
    match (from_account, to_account) {
        ("bank", "wallet") => {
            ensure_balance(latest.bank_total, amount, "銀行残高")?;
            builder.bank_total = Some(latest.bank_total - amount);
            builder.wallet_total = Some(latest.wallet_total + amount);
        }
        ("wallet", "bank") => {
            ensure_balance(latest.wallet_total, amount, "財布残高")?;
            builder.wallet_total = Some(latest.wallet_total - amount);
            builder.bank_total = Some(latest.bank_total + amount);
        }
        ("bank", "securities") => {
            ensure_balance(latest.bank_total, amount, "銀行残高")?;
            builder.bank_total = Some(latest.bank_total - amount);
            builder.securities_total = Some(latest.securities_total + amount);
        }
        ("securities", "bank") => {
            ensure_balance(latest.securities_total, amount, "証券評価額")?;
            builder.securities_total = Some(latest.securities_total - amount);
            builder.bank_total = Some(latest.bank_total + amount);
        }
        _ => {
            return Err(FinError::invalid(format!(
                "未対応の振替組み合わせです: {} → {}",
                from_account, to_account
            )));
        }
    }

    conn.execute(
        "INSERT INTO transfers (occurred_on, from_account, to_account, amount, memo)
         VALUES (date('now', 'localtime'), ?1, ?2, ?3, ?4)",
        rusqlite::params![from_account, to_account, amount, memo],
    )?;
    let transfer_id = conn.last_insert_rowid();

    let transfer_memo = match memo {
        Some(m) if !m.is_empty() => format!("transfer {}→{}: {}", from_account, to_account, m),
        _ => format!("transfer {}→{}", from_account, to_account),
    };
    builder.memo = Some(transfer_memo);

    let snapshot = insert_snapshot(conn, builder)?;
    Ok(TransferResult {
        transfer_id,
        snapshot,
    })
}
