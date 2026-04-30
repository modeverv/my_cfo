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
