use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub id: Option<i64>,
    pub as_of_date: String,
    pub bank_total: i64,
    pub securities_total: i64,
    pub wallet_total: i64,
    pub credit_card_unbilled: i64,
    pub total_assets: i64,
    pub memo: Option<String>,
}

impl Default for Snapshot {
    fn default() -> Self {
        let today = chrono::Local::now().format("%Y-%m-%d").to_string();
        Snapshot {
            id: None,
            as_of_date: today,
            bank_total: 0,
            securities_total: 0,
            wallet_total: 0,
            credit_card_unbilled: 0,
            total_assets: 0,
            memo: None,
        }
    }
}

impl Snapshot {
    pub fn calculate_total(&mut self) {
        self.total_assets =
            self.bank_total + self.securities_total + self.wallet_total - self.credit_card_unbilled;
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WalletTransaction {
    pub occurred_on: String,
    pub direction: String,
    pub amount: i64,
    pub balance_after: Option<i64>,
    pub description: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transfer {
    pub occurred_on: String,
    pub from_account: String,
    pub to_account: String,
    pub amount: i64,
    pub memo: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CardTransaction {
    pub used_on: String,
    pub merchant: String,
    pub amount: i64,
    pub payment_month: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MerchantTotal {
    pub merchant: String,
    pub total: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LargeTransaction {
    pub used_on: String,
    pub merchant: String,
    pub amount: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CardMonthSummary {
    pub month: String,
    pub count: i64,
    pub total: i64,
    pub by_merchant: Vec<MerchantTotal>,
    pub large_transactions: Vec<LargeTransaction>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CashOutEntry {
    pub occurred_on: String,
    pub amount: i64,
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WalletMonthSummary {
    pub month: String,
    pub cash_out_total: i64,
    pub large_cash_out: Vec<CashOutEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportResult {
    pub imported: usize,
    pub skipped: usize,
    pub skipped_rows: usize,
    pub files: usize,
    pub errors: Vec<String>,
}

pub fn format_amount(n: i64) -> String {
    let abs = n.unsigned_abs();
    let s = abs.to_string();
    let bytes = s.as_bytes();
    let mut result = String::new();
    let len = bytes.len();
    for (i, &b) in bytes.iter().enumerate() {
        if i > 0 && (len - i) % 3 == 0 {
            result.push(',');
        }
        result.push(b as char);
    }
    if n < 0 {
        format!("-{}", result)
    } else {
        result
    }
}
