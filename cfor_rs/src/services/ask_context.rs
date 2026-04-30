use crate::error::Result;
use crate::models::{
    CardMonthSummary, CashOutEntry, LargeTransaction, MerchantTotal, Snapshot, WalletMonthSummary,
};
use crate::services::snapshots::{get_latest_snapshot, insert_snapshot, SnapshotBuilder};
use rusqlite::Connection;

const CARD_PAYMENT_MONTH_EXPR: &str = "COALESCE(payment_month, substr(used_on, 1, 7))";

pub fn current_month() -> String {
    chrono::Local::now().format("%Y-%m").to_string()
}

pub fn card_billing_month() -> String {
    let now = chrono::Local::now();
    let year = now.year();
    let month = now.month();
    if month == 12 {
        format!("{:04}-01", year + 1)
    } else {
        format!("{:04}-{:02}", year, month + 1)
    }
}

pub fn latest_card_payment_month(conn: &Connection) -> Result<Option<String>> {
    let month = conn.query_row(
        &format!(
            "SELECT MAX({})
             FROM card_transactions
             WHERE {} IS NOT NULL",
            CARD_PAYMENT_MONTH_EXPR, CARD_PAYMENT_MONTH_EXPR
        ),
        [],
        |row| row.get::<_, Option<String>>(0),
    )?;
    Ok(month)
}

pub fn active_card_month(conn: &Connection) -> Result<String> {
    let billing_month = card_billing_month();
    let count: i64 = conn.query_row(
        &format!(
            "SELECT COUNT(*)
             FROM card_transactions
             WHERE {} = ?1",
            CARD_PAYMENT_MONTH_EXPR
        ),
        rusqlite::params![billing_month],
        |row| row.get(0),
    )?;
    if count > 0 {
        return Ok(billing_month);
    }

    Ok(latest_card_payment_month(conn)?.unwrap_or(billing_month))
}

use chrono::Datelike;

pub fn get_card_month_summary(conn: &Connection, month: &str) -> Result<CardMonthSummary> {
    let (count, total) = conn.query_row(
        &format!(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0)
             FROM card_transactions
             WHERE {} = ?1",
            CARD_PAYMENT_MONTH_EXPR
        ),
        rusqlite::params![month],
        |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
    )?;

    let mut stmt = conn.prepare(&format!(
        "SELECT merchant, SUM(amount) AS total
         FROM card_transactions
         WHERE {} = ?1
         GROUP BY merchant
         ORDER BY total DESC
         LIMIT 10",
        CARD_PAYMENT_MONTH_EXPR
    ))?;
    let by_merchant: Vec<MerchantTotal> = stmt
        .query_map(rusqlite::params![month], |row| {
            Ok(MerchantTotal {
                merchant: row.get(0)?,
                total: row.get(1)?,
            })
        })?
        .filter_map(|r| r.ok())
        .collect();

    let mut stmt = conn.prepare(&format!(
        "SELECT used_on, merchant, amount
         FROM card_transactions
         WHERE {} = ?1
         ORDER BY amount DESC, used_on DESC
         LIMIT 10",
        CARD_PAYMENT_MONTH_EXPR
    ))?;
    let large_transactions: Vec<LargeTransaction> = stmt
        .query_map(rusqlite::params![month], |row| {
            Ok(LargeTransaction {
                used_on: row.get(0)?,
                merchant: row.get(1)?,
                amount: row.get(2)?,
            })
        })?
        .filter_map(|r| r.ok())
        .collect();

    Ok(CardMonthSummary {
        month: month.to_string(),
        count,
        total,
        by_merchant,
        large_transactions,
    })
}

pub fn get_wallet_month_summary(conn: &Connection, month: &str) -> Result<WalletMonthSummary> {
    let cash_out_total: i64 = conn.query_row(
        "SELECT COALESCE(SUM(amount), 0)
         FROM wallet_transactions
         WHERE direction = 'out'
           AND substr(occurred_on, 1, 7) = ?1",
        rusqlite::params![month],
        |row| row.get(0),
    )?;

    let mut stmt = conn.prepare(
        "SELECT occurred_on, amount, description
         FROM wallet_transactions
         WHERE direction = 'out'
           AND substr(occurred_on, 1, 7) = ?1
         ORDER BY amount DESC, occurred_on DESC
         LIMIT 10",
    )?;
    let large_cash_out: Vec<CashOutEntry> = stmt
        .query_map(rusqlite::params![month], |row| {
            Ok(CashOutEntry {
                occurred_on: row.get(0)?,
                amount: row.get(1)?,
                description: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
            })
        })?
        .filter_map(|r| r.ok())
        .collect();

    Ok(WalletMonthSummary {
        month: month.to_string(),
        cash_out_total,
        large_cash_out,
    })
}

pub fn get_recent_transfers(conn: &Connection, limit: i64) -> Result<Vec<crate::models::Transfer>> {
    let mut stmt = conn.prepare(
        "SELECT occurred_on, from_account, to_account, amount, memo
         FROM transfers
         ORDER BY occurred_on DESC, id DESC
         LIMIT ?1",
    )?;
    let transfers: Vec<crate::models::Transfer> = stmt
        .query_map(rusqlite::params![limit], |row| {
            Ok(crate::models::Transfer {
                occurred_on: row.get(0)?,
                from_account: row.get(1)?,
                to_account: row.get(2)?,
                amount: row.get(3)?,
                memo: row.get(4)?,
            })
        })?
        .filter_map(|r| r.ok())
        .collect();
    Ok(transfers)
}

pub fn refresh_card_unbilled(conn: &Connection, month: &str) -> Result<Snapshot> {
    let total: i64 = conn.query_row(
        &format!(
            "SELECT COALESCE(SUM(amount), 0)
             FROM card_transactions
             WHERE {} = ?1",
            CARD_PAYMENT_MONTH_EXPR
        ),
        rusqlite::params![month],
        |row| row.get(0),
    )?;
    insert_snapshot(
        conn,
        SnapshotBuilder {
            credit_card_unbilled: Some(total),
            memo: Some(format!("card refresh {}", month)),
            ..Default::default()
        },
    )
}

pub fn build_finance_context(conn: &Connection, question: &str) -> Result<String> {
    let latest = get_latest_snapshot(conn)?;
    let usage_month = current_month();
    let billing_month = active_card_month(conn)?;
    let prev_billing = usage_month.clone();

    let wallet_summary = get_wallet_month_summary(conn, &usage_month)?;
    let card_this = get_card_month_summary(conn, &billing_month)?;
    let card_prev = get_card_month_summary(conn, &prev_billing)?;
    let transfers = get_recent_transfers(conn, 10)?;

    let transfers_str = serde_json::to_string_pretty(&transfers).unwrap_or_default();
    let by_merchant_str = serde_json::to_string_pretty(&card_this.by_merchant).unwrap_or_default();
    let large_tx_str =
        serde_json::to_string_pretty(&card_this.large_transactions).unwrap_or_default();
    let cash_out_str =
        serde_json::to_string_pretty(&wallet_summary.large_cash_out).unwrap_or_default();

    Ok(format!(
        "## 現在の資産状況\n\
        総資産: {}円\n\
        銀行残高: {}円\n\
        証券評価額: {}円\n\
        財布残高: {}円\n\
        カード未払い/今月利用: {}円\n\
        \n\
        ## 今月のカード利用（利用月: {} / 支払月: {}）\n\
        合計: {}円\n\
        加盟店別: {}\n\
        高額決済: {}\n\
        \n\
        ## 前月比較（支払月: {}）\n\
        前月カード合計: {}円\n\
        差額: {}円\n\
        \n\
        ## 今月の現金支出（{}）\n\
        財布支出合計: {}円\n\
        主な現金支出: {}\n\
        \n\
        ## 最近の振替\n\
        {}\n\
        \n\
        ## 質問\n\
        {}",
        crate::models::format_amount(latest.total_assets),
        crate::models::format_amount(latest.bank_total),
        crate::models::format_amount(latest.securities_total),
        crate::models::format_amount(latest.wallet_total),
        crate::models::format_amount(latest.credit_card_unbilled),
        usage_month,
        billing_month,
        crate::models::format_amount(card_this.total),
        by_merchant_str,
        large_tx_str,
        prev_billing,
        crate::models::format_amount(card_prev.total),
        crate::models::format_amount(card_this.total - card_prev.total),
        usage_month,
        crate::models::format_amount(wallet_summary.cash_out_total),
        cash_out_str,
        transfers_str,
        question,
    ))
}

pub fn build_ask_prompt(context: &str, question: &str) -> String {
    format!(
        "あなたは個人の財務管理を補助するアシスタントです。\n\
        以下のデータだけを根拠に回答してください。\n\
        推測する場合は、推測であることを明示してください。\n\
        \n\
        {}\n\
        \n\
        ---\n\
        質問: {}\n\
        \n\
        回答方針:\n\
        - まず結論を短く述べる\n\
        - 数値根拠を出す\n\
        - 支出・振替・資産変動を混同しない\n\
        - 増加要因・注意点を箇条書きにする\n\
        - 不明な点は不明と言う",
        context, question
    )
}
