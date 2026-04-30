use crate::config::{
    default_csv_formats, default_encodings, default_inbox, load, load_with_path,
    resolve_config_relative_path, CsvFormatConfig,
};
use crate::error::{FinError, Result};
use crate::models::ImportResult;
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use unicode_normalization::UnicodeNormalization;

fn normalize(text: &str) -> String {
    text.nfkc().collect::<String>().trim().to_string()
}

fn parse_date(raw: &str) -> Option<String> {
    let parts: Vec<&str> = raw.trim().split('/').collect();
    if parts.len() == 3 {
        let year: u32 = parts[0].parse().ok()?;
        let month: u32 = parts[1].parse().ok()?;
        let day: u32 = parts[2].parse().ok()?;
        Some(format!("{:04}-{:02}-{:02}", year, month, day))
    } else {
        None
    }
}

fn looks_like_date(text: &str) -> bool {
    let t = text.trim();
    let parts: Vec<&str> = t.split('/').collect();
    if parts.len() != 3 {
        return false;
    }
    parts[0].len() == 4
        && parts[0].chars().all(|c| c.is_ascii_digit())
        && parts[1].chars().all(|c| c.is_ascii_digit())
        && parts[2].chars().all(|c| c.is_ascii_digit())
}

fn parse_amount(raw: &str) -> Option<i64> {
    let normalized = normalize(raw)
        .replace(',', "")
        .replace('円', "")
        .trim()
        .to_string();
    normalized.parse::<i64>().ok()
}

fn parse_payment_month_col(raw: &str) -> Option<String> {
    let raw = raw.trim().trim_start_matches('\'');
    let parts: Vec<&str> = raw.split('/').collect();
    if parts.len() == 2 {
        let year: u32 = parts[0].parse().ok()?;
        let month: u32 = parts[1].parse().ok()?;
        Some(format!("{:04}-{:02}", 2000 + year, month))
    } else {
        None
    }
}

fn payment_month_from_filename(path: &Path) -> Option<String> {
    let stem = path.file_stem()?.to_str()?;
    if stem.len() >= 6 && stem[..6].chars().all(|c| c.is_ascii_digit()) {
        let year = &stem[..4];
        let month = &stem[4..6];
        Some(format!("{}-{}", year, month))
    } else {
        None
    }
}

fn file_hash(path: &Path) -> Result<String> {
    let bytes = std::fs::read(path).map_err(|e| FinError::Other(e.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Ok(hex::encode(hasher.finalize()))
}

fn decode_csv(bytes: &[u8], encodings: &[String]) -> String {
    // Check for UTF-8 BOM
    if bytes.starts_with(b"\xef\xbb\xbf") {
        if let Ok(s) = std::str::from_utf8(&bytes[3..]) {
            return s.to_string();
        }
    }

    for enc in encodings {
        match enc.as_str() {
            "utf-8-sig" => {
                let data = if bytes.starts_with(b"\xef\xbb\xbf") {
                    &bytes[3..]
                } else {
                    bytes
                };
                if let Ok(s) = std::str::from_utf8(data) {
                    return s.to_string();
                }
            }
            "utf-8" => {
                if let Ok(s) = std::str::from_utf8(bytes) {
                    return s.to_string();
                }
            }
            "cp932" | "shift_jis" | "shift-jis" => {
                let (cow, _, had_errors) = encoding_rs::SHIFT_JIS.decode(bytes);
                if !had_errors {
                    return cow.into_owned();
                }
            }
            _ => {
                if let Ok(s) = std::str::from_utf8(bytes) {
                    return s.to_string();
                }
            }
        }
    }
    // last resort
    let (cow, _, _) = encoding_rs::SHIFT_JIS.decode(bytes);
    cow.into_owned()
}

fn cell(row: &[String], index: usize) -> &str {
    row.get(index).map(|s| s.as_str()).unwrap_or("")
}

fn first_value<'a>(row: &'a [String], indices: &[usize]) -> &'a str {
    for &i in indices {
        let v = cell(row, i);
        if !v.is_empty() {
            return v;
        }
    }
    ""
}

fn format_matches(rows: &[Vec<String>], fmt: &CsvFormatConfig) -> bool {
    let used_on_col = fmt.columns.used_on;
    if let Some(detect) = &fmt.detect {
        if let Some(first_is_date) = detect.first_column_is_date {
            if let Some(header_rows) = detect.header_rows {
                if header_rows >= rows.len() {
                    return false;
                }
                return looks_like_date(cell(&rows[header_rows], used_on_col)) == first_is_date;
            }
            if first_is_date {
                return rows
                    .iter()
                    .take(20)
                    .any(|r| looks_like_date(cell(r, used_on_col)));
            } else {
                return rows
                    .first()
                    .map(|r| !looks_like_date(cell(r, used_on_col)))
                    .unwrap_or(false);
            }
        }
    }
    true
}

fn format_score(rows: &[Vec<String>], fmt: &CsvFormatConfig, _path: &Path) -> usize {
    let used_on_col = fmt.columns.used_on;
    let merchant_col = fmt.columns.merchant;
    let amount_cols = fmt.columns.amount.indices();
    let mut score = 0usize;

    for row in rows.iter().take(50) {
        if !looks_like_date(cell(row, used_on_col)) {
            continue;
        }
        if cell(row, merchant_col).is_empty() {
            continue;
        }
        let amount_raw = first_value(row, &amount_cols);
        if amount_raw.is_empty() {
            continue;
        }
        if parse_amount(amount_raw).is_none() {
            continue;
        }
        if fmt.payment_month.source == "column" {
            if let Some(col) = fmt.payment_month.column {
                let pm_raw = cell(row, col);
                if pm_raw.is_empty() {
                    continue;
                }
                let parser = fmt.payment_month.parser.as_deref().unwrap_or("yy/mm");
                if parse_payment_month_value(pm_raw, parser).is_none() {
                    continue;
                }
            }
        }
        score += 1;
    }
    score
}

fn parse_payment_month_value(raw: &str, parser: &str) -> Option<String> {
    match parser {
        "yy/mm" => parse_payment_month_col(raw),
        "yyyy-mm" => {
            let normalized = normalize(raw).replace('/', "-");
            let parts: Vec<&str> = normalized.split('-').collect();
            if parts.len() == 2 {
                let year: u32 = parts[0].parse().ok()?;
                let month: u32 = parts[1].parse().ok()?;
                Some(format!("{:04}-{:02}", year, month))
            } else {
                None
            }
        }
        _ => None,
    }
}

fn payment_month_for_row(row: &[String], path: &Path, fmt: &CsvFormatConfig) -> Option<String> {
    match fmt.payment_month.source.as_str() {
        "filename" => payment_month_from_filename(path).or_else(|| {
            if fmt.payment_month.fallback.as_deref() == Some("current_month") {
                Some(chrono::Local::now().format("%Y-%m").to_string())
            } else {
                None
            }
        }),
        "column" => {
            let col = fmt.payment_month.column?;
            let raw = cell(row, col);
            if raw.is_empty() {
                return None;
            }
            let parser = fmt.payment_month.parser.as_deref().unwrap_or("yy/mm");
            parse_payment_month_value(raw, parser)
        }
        _ => None,
    }
}

fn detect_format<'a>(
    rows: &[Vec<String>],
    formats: &'a [CsvFormatConfig],
    path: &Path,
) -> Result<&'a CsvFormatConfig> {
    let candidates: Vec<(&CsvFormatConfig, usize)> = formats
        .iter()
        .filter(|f| format_matches(rows, f))
        .map(|f| (f, format_score(rows, f, path)))
        .filter(|(_, s)| *s > 0)
        .collect();

    candidates
        .into_iter()
        .max_by_key(|(_, s)| *s)
        .map(|(f, _)| f)
        .ok_or_else(|| {
            let names: Vec<&str> = formats.iter().map(|f| f.name.as_str()).collect();
            FinError::Invalid(format!(
                "対応するCSVフォーマットが見つかりません: {}",
                names.join(", ")
            ))
        })
}

struct ParsedRow {
    used_on: String,
    merchant: String,
    amount: i64,
    payment_month: Option<String>,
}

fn parse_rows(rows: &[Vec<String>], path: &Path, fmt: &CsvFormatConfig) -> (Vec<ParsedRow>, usize) {
    let used_on_col = fmt.columns.used_on;
    let merchant_col = fmt.columns.merchant;
    let amount_cols = fmt.columns.amount.indices();
    let mut records = Vec::new();
    let mut skipped = 0usize;

    for row in rows {
        if !looks_like_date(cell(row, used_on_col)) {
            continue;
        }
        let used_on = match parse_date(cell(row, used_on_col)) {
            Some(d) => d,
            None => {
                skipped += 1;
                continue;
            }
        };
        let merchant = normalize(cell(row, merchant_col));
        if merchant.is_empty() {
            skipped += 1;
            continue;
        }
        let amount_raw = first_value(row, &amount_cols);
        let amount = match parse_amount(amount_raw) {
            Some(a) => a,
            None => {
                skipped += 1;
                continue;
            }
        };
        let payment_month = payment_month_for_row(row, path, fmt);

        records.push(ParsedRow {
            used_on,
            merchant,
            amount,
            payment_month,
        });
    }
    (records, skipped)
}

fn parse_csv_file(
    path: &Path,
    formats: &[CsvFormatConfig],
    encodings: &[String],
) -> Result<(Vec<ParsedRow>, usize)> {
    let bytes = std::fs::read(path).map_err(|e| FinError::Other(e.to_string()))?;
    let text = decode_csv(&bytes, encodings);
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(false)
        .flexible(true)
        .from_reader(text.as_bytes());

    let rows: Vec<Vec<String>> = reader
        .records()
        .filter_map(|r| r.ok())
        .map(|r| r.iter().map(|s| s.to_string()).collect())
        .collect();

    let fmt = detect_format(&rows, formats, path)?;
    Ok(parse_rows(&rows, path, fmt))
}

fn transaction_exists(
    conn: &Connection,
    used_on: &str,
    merchant: &str,
    amount: i64,
    payment_month: Option<&str>,
) -> Result<bool> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM card_transactions
         WHERE used_on = ?1 AND merchant = ?2 AND amount = ?3 AND payment_month IS ?4
         LIMIT 1",
        rusqlite::params![used_on, merchant, amount, payment_month],
        |row| row.get(0),
    )?;
    Ok(count > 0)
}

fn insert_records(conn: &Connection, records: &[ParsedRow]) -> Result<(usize, usize)> {
    let mut imported = 0usize;
    let mut skipped = 0usize;
    for rec in records {
        if transaction_exists(
            conn,
            &rec.used_on,
            &rec.merchant,
            rec.amount,
            rec.payment_month.as_deref(),
        )? {
            skipped += 1;
            continue;
        }
        conn.execute(
            "INSERT INTO card_transactions (used_on, merchant, amount, payment_month)
             VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![rec.used_on, rec.merchant, rec.amount, rec.payment_month],
        )?;
        imported += 1;
    }
    Ok((imported, skipped))
}

fn get_formats_and_encodings() -> (Vec<CsvFormatConfig>, Vec<String>) {
    let cfg = load();
    let card_csv = cfg.card_csv;
    let formats = card_csv
        .as_ref()
        .and_then(|c| c.formats.clone())
        .unwrap_or_else(default_csv_formats);
    let encodings = card_csv
        .as_ref()
        .and_then(|c| c.encodings.clone())
        .unwrap_or_else(default_encodings);
    (formats, encodings)
}

pub struct SingleImportResult {
    pub imported: usize,
    pub skipped: usize,
    pub skipped_rows: usize,
    pub import_id: i64,
}

pub fn import_csv(conn: &Connection, path: &Path) -> Result<SingleImportResult> {
    let fhash = file_hash(path)?;
    let (formats, encodings) = get_formats_and_encodings();

    let existing: Option<(i64, String)> = conn
        .query_row(
            "SELECT id, status FROM imports WHERE file_hash = ?1",
            rusqlite::params![fhash],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .ok();

    if let Some((id, _)) = existing {
        let (records, skipped_rows) = parse_csv_file(path, &formats, &encodings)?;
        let (imported, skipped) = insert_records(conn, &records)?;
        return Ok(SingleImportResult {
            imported,
            skipped,
            skipped_rows,
            import_id: id,
        });
    }

    conn.execute(
        "INSERT INTO imports (source_type, source_name, file_path, file_hash, status)
         VALUES ('credit_card_csv', ?1, ?2, ?3, 'importing')",
        rusqlite::params![
            path.file_name().and_then(|n| n.to_str()).unwrap_or(""),
            path.display().to_string(),
            fhash,
        ],
    )?;
    let import_id = conn.last_insert_rowid();

    match parse_csv_file(path, &formats, &encodings) {
        Ok((records, skipped_rows)) => {
            let (imported, skipped) = insert_records(conn, &records)?;
            conn.execute(
                "UPDATE imports SET status = 'done', imported_at = datetime('now', 'localtime') WHERE id = ?1",
                rusqlite::params![import_id],
            )?;
            Ok(SingleImportResult {
                imported,
                skipped,
                skipped_rows,
                import_id,
            })
        }
        Err(e) => {
            conn.execute(
                "UPDATE imports SET status = 'error', error_message = ?1 WHERE id = ?2",
                rusqlite::params![e.to_string(), import_id],
            )?;
            Err(e)
        }
    }
}

pub fn import_directory(conn: &Connection, directory: Option<&Path>) -> Result<ImportResult> {
    let loaded = load_with_path();
    let inbox_str = loaded
        .config
        .card_csv
        .as_ref()
        .and_then(|c| c.default_inbox.clone())
        .unwrap_or_else(default_inbox);

    let target = directory
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| resolve_config_relative_path(&inbox_str, loaded.path.as_deref()));

    let mut csv_files: Vec<PathBuf> = match std::fs::read_dir(&target) {
        Ok(rd) => rd
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("csv"))
            .collect(),
        Err(_) => {
            return Ok(ImportResult {
                imported: 0,
                skipped: 0,
                skipped_rows: 0,
                files: 0,
                errors: vec![],
            });
        }
    };
    csv_files.sort();

    if csv_files.is_empty() {
        return Ok(ImportResult {
            imported: 0,
            skipped: 0,
            skipped_rows: 0,
            files: 0,
            errors: vec![],
        });
    }

    let mut total_imported = 0usize;
    let mut total_skipped = 0usize;
    let mut total_skipped_rows = 0usize;
    let mut errors = Vec::new();

    for csv_path in &csv_files {
        match import_csv(conn, csv_path) {
            Ok(r) => {
                total_imported += r.imported;
                total_skipped += r.skipped;
                total_skipped_rows += r.skipped_rows;
                if r.skipped_rows > 0 {
                    errors.push(format!(
                        "{}: {}行をスキップ",
                        csv_path.file_name().and_then(|n| n.to_str()).unwrap_or(""),
                        r.skipped_rows
                    ));
                }
            }
            Err(e) => {
                errors.push(format!(
                    "{}: {}",
                    csv_path.file_name().and_then(|n| n.to_str()).unwrap_or(""),
                    e
                ));
            }
        }
    }

    Ok(ImportResult {
        imported: total_imported,
        skipped: total_skipped,
        skipped_rows: total_skipped_rows,
        files: csv_files.len(),
        errors,
    })
}
