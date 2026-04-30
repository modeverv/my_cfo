use crate::display::fit;
use crate::error::Result;
use crate::models::Snapshot;
use crate::services::ask_context::get_card_month_summary;
use crate::services::snapshots::get_latest_snapshot;
use rusqlite::Connection;

const LABEL_COLS: usize = 13;
const AMOUNT_COLS: usize = 13;
const MERCHANT_COLS: usize = 30;

pub fn format_current_position(position: &Snapshot) -> String {
    fn row(label: &str, amount: i64) -> String {
        let label_part = fit(label, LABEL_COLS);
        let num_str = crate::models::format_amount(amount);
        let padding = AMOUNT_COLS.saturating_sub(num_str.len());
        format!("{}{}{}円", label_part, " ".repeat(padding), num_str)
    }

    vec![
        row("総資産:", position.total_assets),
        row("銀行残高:", position.bank_total),
        row("証券評価額:", position.securities_total),
        row("財布残高:", position.wallet_total),
        row("カード利用:", -position.credit_card_unbilled),
    ]
    .join("\n")
}

pub fn show_now(conn: &Connection) -> Result<String> {
    let snapshot = get_latest_snapshot(conn)?;
    Ok(format_current_position(&snapshot))
}

pub fn show_wallet(conn: &Connection, limit: i64) -> Result<String> {
    let snapshot = get_latest_snapshot(conn)?;
    let mut stmt = conn.prepare(
        "SELECT occurred_on, direction, amount, balance_after, description
         FROM wallet_transactions
         ORDER BY id DESC
         LIMIT ?1",
    )?;

    let rows: Vec<(String, String, i64, Option<i64>, Option<String>)> = stmt
        .query_map(rusqlite::params![limit], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, Option<i64>>(3)?,
                row.get::<_, Option<String>>(4)?,
            ))
        })?
        .filter_map(|r| r.ok())
        .collect();

    let mut lines = vec![
        format!(
            "財布残高: {}円",
            crate::models::format_amount(snapshot.wallet_total)
        ),
        String::new(),
    ];

    if rows.is_empty() {
        lines.push("取引履歴がありません".to_string());
    } else {
        lines.push("最近の取引:".to_string());
        for (occurred_on, direction, amount, balance_after, description) in &rows {
            let label = match direction.as_str() {
                "in" => "資産増加",
                "out" => "支出",
                "set" => "補正後残高",
                other => other,
            };
            let amount_text = if direction == "set" {
                if let Some(ba) = balance_after {
                    format!("{:>10}円", crate::models::format_amount(*ba))
                } else {
                    format!("{:>10}円", crate::models::format_amount(*amount))
                }
            } else {
                format!("{:>10}円", crate::models::format_amount(*amount))
            };
            let desc = description.as_deref().unwrap_or("");
            lines.push(format!(
                "  {}  {}  {}  {}",
                occurred_on, label, amount_text, desc
            ));
        }
    }

    Ok(lines.join("\n"))
}

pub fn show_card(conn: &Connection, month: &str) -> Result<String> {
    let summary = get_card_month_summary(conn, month)?;
    let mut lines = vec![
        format!(
            "カード利用 支払月:{} — {}件  計 {}円",
            month,
            summary.count,
            crate::models::format_amount(summary.total)
        ),
        String::new(),
        "加盟店別TOP10:".to_string(),
    ];

    for r in &summary.by_merchant {
        lines.push(format!(
            "  {}  {:>10}円",
            fit(&r.merchant, MERCHANT_COLS),
            crate::models::format_amount(r.total)
        ));
    }
    lines.push(String::new());
    lines.push("高額TOP10:".to_string());
    for r in &summary.large_transactions {
        lines.push(format!(
            "  {}  {}  {:>10}円",
            r.used_on,
            fit(&r.merchant, MERCHANT_COLS),
            crate::models::format_amount(r.amount)
        ));
    }

    Ok(lines.join("\n"))
}
