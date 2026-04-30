use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct LlmConfig {
    pub base_url: Option<String>,
    pub model: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AmountColumns {
    #[serde(flatten)]
    inner: AmountColumnsInner,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(untagged)]
enum AmountColumnsInner {
    Single(usize),
    Multiple(Vec<usize>),
}

impl AmountColumns {
    pub fn indices(&self) -> Vec<usize> {
        match &self.inner {
            AmountColumnsInner::Single(i) => vec![*i],
            AmountColumnsInner::Multiple(v) => v.clone(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CsvColumns {
    pub used_on: usize,
    pub merchant: usize,
    pub amount: AmountColumnsRaw,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(untagged)]
pub enum AmountColumnsRaw {
    Single(usize),
    Multiple(Vec<usize>),
}

impl AmountColumnsRaw {
    pub fn indices(&self) -> Vec<usize> {
        match self {
            AmountColumnsRaw::Single(i) => vec![*i],
            AmountColumnsRaw::Multiple(v) => v.clone(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DetectConfig {
    pub first_column_is_date: Option<bool>,
    pub header_rows: Option<usize>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PaymentMonthConfig {
    pub source: String,
    pub column: Option<usize>,
    pub parser: Option<String>,
    pub fallback: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CsvFormatConfig {
    pub name: String,
    pub detect: Option<DetectConfig>,
    pub columns: CsvColumns,
    pub payment_month: PaymentMonthConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CardCsvConfig {
    pub default_inbox: Option<String>,
    pub encodings: Option<Vec<String>>,
    pub formats: Option<Vec<CsvFormatConfig>>,
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct AppConfig {
    pub llm: Option<LlmConfig>,
    pub card_csv: Option<CardCsvConfig>,
}

impl AppConfig {
    pub fn llm(&self) -> LlmConfig {
        self.llm.clone().unwrap_or_default()
    }
}

#[derive(Debug, Clone, Default)]
pub struct LoadedConfig {
    pub config: AppConfig,
    pub path: Option<PathBuf>,
}

const CONFIG_FILE_NAME: &str = "finance_config.yaml";

fn candidate_config_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();

    if let Ok(path) = std::env::var("CFOR_CONFIG") {
        if !path.trim().is_empty() {
            paths.push(PathBuf::from(path));
        }
    }

    paths.push(PathBuf::from(CONFIG_FILE_NAME));

    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            for ancestor in exe_dir.ancestors() {
                paths.push(ancestor.join(CONFIG_FILE_NAME));
            }
        }
    }

    paths
}

pub fn config_path() -> Option<PathBuf> {
    candidate_config_paths()
        .into_iter()
        .find(|path| path.exists())
}

pub fn load() -> AppConfig {
    load_with_path().config
}

pub fn load_with_path() -> LoadedConfig {
    let Some(path) = config_path() else {
        return LoadedConfig::default();
    };
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return LoadedConfig::default(),
    };
    let config = serde_yaml::from_str(&text).unwrap_or_default();
    LoadedConfig {
        config,
        path: Some(path),
    }
}

pub fn resolve_config_relative_path(path: &str, config_path: Option<&Path>) -> PathBuf {
    let path_buf = PathBuf::from(path);
    if path_buf.is_absolute() {
        return path_buf;
    }

    if let Some(base) = config_path.and_then(|p| p.parent()) {
        return base.join(path_buf);
    }

    path_buf
}

pub fn default_csv_formats() -> Vec<CsvFormatConfig> {
    vec![
        CsvFormatConfig {
            name: "format_a_filename_payment_month".to_string(),
            detect: Some(DetectConfig {
                first_column_is_date: Some(false),
                header_rows: None,
            }),
            columns: CsvColumns {
                used_on: 0,
                merchant: 1,
                amount: AmountColumnsRaw::Single(5),
            },
            payment_month: PaymentMonthConfig {
                source: "filename".to_string(),
                column: None,
                parser: Some("yyyymm".to_string()),
                fallback: Some("current_month".to_string()),
            },
        },
        CsvFormatConfig {
            name: "format_b_payment_month_column".to_string(),
            detect: Some(DetectConfig {
                first_column_is_date: Some(true),
                header_rows: None,
            }),
            columns: CsvColumns {
                used_on: 0,
                merchant: 1,
                amount: AmountColumnsRaw::Multiple(vec![7, 6]),
            },
            payment_month: PaymentMonthConfig {
                source: "column".to_string(),
                column: Some(5),
                parser: Some("yy/mm".to_string()),
                fallback: None,
            },
        },
    ]
}

pub fn default_encodings() -> Vec<String> {
    vec![
        "utf-8-sig".to_string(),
        "utf-8".to_string(),
        "cp932".to_string(),
    ]
}

pub fn default_inbox() -> String {
    "data/inbox/card".to_string()
}
