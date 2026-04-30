use crate::error::Result;
use crate::models::Snapshot;
use rusqlite::Connection;

pub fn get_latest_snapshot(conn: &Connection) -> Result<Snapshot> {
    let result = conn.query_row(
        "SELECT id, as_of_date, bank_total, securities_total, wallet_total,
                credit_card_unbilled, total_assets, memo
         FROM asset_snapshots
         ORDER BY as_of_date DESC, id DESC
         LIMIT 1",
        [],
        |row| {
            Ok(Snapshot {
                id: Some(row.get(0)?),
                as_of_date: row.get(1)?,
                bank_total: row.get(2)?,
                securities_total: row.get(3)?,
                wallet_total: row.get(4)?,
                credit_card_unbilled: row.get(5)?,
                total_assets: row.get(6)?,
                memo: row.get(7)?,
            })
        },
    );
    match result {
        Ok(s) => Ok(s),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(Snapshot::default()),
        Err(e) => Err(e.into()),
    }
}

pub struct SnapshotBuilder {
    pub bank_total: Option<i64>,
    pub securities_total: Option<i64>,
    pub wallet_total: Option<i64>,
    pub credit_card_unbilled: Option<i64>,
    pub memo: Option<String>,
    pub as_of_date: Option<String>,
}

impl Default for SnapshotBuilder {
    fn default() -> Self {
        SnapshotBuilder {
            bank_total: None,
            securities_total: None,
            wallet_total: None,
            credit_card_unbilled: None,
            memo: None,
            as_of_date: None,
        }
    }
}

pub fn insert_snapshot(conn: &Connection, builder: SnapshotBuilder) -> Result<Snapshot> {
    let mut latest = get_latest_snapshot(conn)?;

    if let Some(v) = builder.bank_total {
        latest.bank_total = v;
    }
    if let Some(v) = builder.securities_total {
        latest.securities_total = v;
    }
    if let Some(v) = builder.wallet_total {
        latest.wallet_total = v;
    }
    if let Some(v) = builder.credit_card_unbilled {
        latest.credit_card_unbilled = v;
    }

    latest.as_of_date = builder
        .as_of_date
        .unwrap_or_else(|| chrono::Local::now().format("%Y-%m-%d").to_string());
    latest.memo = builder.memo;
    latest.calculate_total();

    conn.execute(
        "INSERT INTO asset_snapshots
         (as_of_date, bank_total, securities_total, wallet_total,
          credit_card_unbilled, total_assets, memo)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        rusqlite::params![
            latest.as_of_date,
            latest.bank_total,
            latest.securities_total,
            latest.wallet_total,
            latest.credit_card_unbilled,
            latest.total_assets,
            latest.memo,
        ],
    )?;
    latest.id = Some(conn.last_insert_rowid());
    Ok(latest)
}

pub fn format_snapshot(snapshot: &Snapshot) -> String {
    crate::services::now::format_current_position(snapshot)
}
