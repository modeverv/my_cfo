use crate::error::{FinError, Result};
use crate::models::Snapshot;
use crate::services::snapshots::{get_latest_snapshot, insert_snapshot, SnapshotBuilder};
use rusqlite::Connection;

pub fn set_bank_total(conn: &Connection, amount: i64) -> Result<Snapshot> {
    insert_snapshot(
        conn,
        SnapshotBuilder {
            bank_total: Some(amount),
            memo: Some("set-bank".to_string()),
            ..Default::default()
        },
    )
}

pub fn set_securities_total(conn: &Connection, amount: i64) -> Result<Snapshot> {
    insert_snapshot(
        conn,
        SnapshotBuilder {
            securities_total: Some(amount),
            memo: Some("set-securities".to_string()),
            ..Default::default()
        },
    )
}

pub fn set_wallet_total(conn: &Connection, amount: i64) -> Result<Snapshot> {
    let latest = get_latest_snapshot(conn)?;
    let description = format!(
        "cash-set: {}円 -> {}円",
        crate::models::format_amount(latest.wallet_total),
        crate::models::format_amount(amount)
    );
    conn.execute(
        "INSERT INTO wallet_transactions (occurred_on, direction, amount, balance_after, description)
         VALUES (date('now', 'localtime'), 'set', ?1, ?2, ?3)",
        rusqlite::params![amount, amount, description],
    )?;
    insert_snapshot(
        conn,
        SnapshotBuilder {
            wallet_total: Some(amount),
            memo: Some("cash-set".to_string()),
            ..Default::default()
        },
    )
}

pub fn cash_add(conn: &Connection, amount: i64, memo: &str) -> Result<Snapshot> {
    if amount <= 0 {
        return Err(FinError::invalid("現金追加額は1円以上で指定してください"));
    }
    let latest = get_latest_snapshot(conn)?;
    let new_wallet = latest.wallet_total + amount;
    conn.execute(
        "INSERT INTO wallet_transactions (occurred_on, direction, amount, balance_after, description)
         VALUES (date('now', 'localtime'), 'in', ?1, ?2, ?3)",
        rusqlite::params![amount, new_wallet, memo],
    )?;
    insert_snapshot(
        conn,
        SnapshotBuilder {
            wallet_total: Some(new_wallet),
            memo: Some(format!("cash-in: {}", memo)),
            ..Default::default()
        },
    )
}

pub fn cash_out(conn: &Connection, amount: i64, memo: &str) -> Result<Snapshot> {
    if amount <= 0 {
        return Err(FinError::invalid("支出額は1円以上で指定してください"));
    }
    let latest = get_latest_snapshot(conn)?;
    let new_wallet = latest.wallet_total - amount;
    if new_wallet < 0 {
        return Err(FinError::invalid(format!(
            "財布残高が不足しています (現在: {}円)",
            crate::models::format_amount(latest.wallet_total)
        )));
    }
    conn.execute(
        "INSERT INTO wallet_transactions (occurred_on, direction, amount, balance_after, description)
         VALUES (date('now', 'localtime'), 'out', ?1, ?2, ?3)",
        rusqlite::params![amount, new_wallet, memo],
    )?;
    insert_snapshot(
        conn,
        SnapshotBuilder {
            wallet_total: Some(new_wallet),
            memo: Some(format!("cash-out: {}", memo)),
            ..Default::default()
        },
    )
}
