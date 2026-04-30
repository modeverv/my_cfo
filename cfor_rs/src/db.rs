use crate::config::config_path;
use crate::error::Result;
use rusqlite::Connection;
use std::path::{Path, PathBuf};

pub fn default_db_path() -> PathBuf {
    config_path()
        .and_then(|path| path.parent().map(|parent| parent.join("finance.sqlite3")))
        .unwrap_or_else(|| PathBuf::from("finance.sqlite3"))
}

const SCHEMA_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS asset_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  bank_total INTEGER NOT NULL DEFAULT 0,
  securities_total INTEGER NOT NULL DEFAULT 0,
  wallet_total INTEGER NOT NULL DEFAULT 0,
  credit_card_unbilled INTEGER NOT NULL DEFAULT 0,
  total_assets INTEGER NOT NULL DEFAULT 0,
  memo TEXT
);

CREATE INDEX IF NOT EXISTS idx_asset_snapshots_as_of_date
  ON asset_snapshots(as_of_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS wallet_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_on TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('in', 'out', 'set')),
  amount INTEGER NOT NULL CHECK (amount >= 0),
  balance_after INTEGER,
  description TEXT
);

CREATE INDEX IF NOT EXISTS idx_wallet_transactions_occurred_on
  ON wallet_transactions(occurred_on DESC, id DESC);

CREATE TABLE IF NOT EXISTS transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_on TEXT NOT NULL,
  from_account TEXT NOT NULL,
  to_account TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK (amount >= 0),
  memo TEXT
);

CREATE INDEX IF NOT EXISTS idx_transfers_occurred_on
  ON transfers(occurred_on DESC, id DESC);

CREATE TABLE IF NOT EXISTS card_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  used_on TEXT NOT NULL,
  merchant TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK (amount >= 0),
  payment_month TEXT
);

CREATE INDEX IF NOT EXISTS idx_card_transactions_used_on
  ON card_transactions(used_on DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_card_transactions_payment_month
  ON card_transactions(payment_month);

CREATE INDEX IF NOT EXISTS idx_card_transactions_merchant
  ON card_transactions(merchant);

CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,
  source_name TEXT,
  file_path TEXT NOT NULL,
  file_hash TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  imported_at TEXT,
  created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"#;

pub fn connect(db_path: &Path) -> Result<Connection> {
    let conn = Connection::open(db_path)?;
    conn.execute_batch("PRAGMA foreign_keys = ON;")?;
    Ok(conn)
}

pub fn init_db(db_path: &Path) -> Result<()> {
    let conn = connect(db_path)?;
    conn.execute_batch(SCHEMA_SQL)?;
    ensure_wallet_columns(&conn)?;
    Ok(())
}

fn ensure_wallet_columns(conn: &Connection) -> Result<()> {
    let mut stmt = conn.prepare("PRAGMA table_info(wallet_transactions)")?;
    let columns: Vec<String> = stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .filter_map(|r| r.ok())
        .collect();
    if !columns.iter().any(|c| c == "balance_after") {
        conn.execute_batch("ALTER TABLE wallet_transactions ADD COLUMN balance_after INTEGER;")?;
    }
    Ok(())
}
