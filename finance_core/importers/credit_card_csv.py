from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from finance_core.config import load as load_config


DEFAULT_CARD_CSV_CONFIG: dict[str, Any] = {
    "default_inbox": "data/inbox/card",
    "encodings": ["utf-8-sig", "utf-8", "cp932"],
    "formats": [
        {
            "name": "format_a_filename_payment_month",
            "detect": {"first_column_is_date": False},
            "columns": {
                "used_on": 0,
                "merchant": 1,
                "amount": 5,
            },
            "payment_month": {
                "source": "filename",
                "parser": "yyyymm",
                "fallback": "current_month",
            },
        },
        {
            "name": "format_b_payment_month_column",
            "detect": {"first_column_is_date": True},
            "columns": {
                "used_on": 0,
                "merchant": 1,
                "amount": [7, 6],
            },
            "payment_month": {
                "source": "column",
                "column": 5,
                "parser": "yy/mm",
            },
        },
    ],
}


class CsvConfigError(ValueError):
    pass


def _normalize(text: str) -> str:
    """全角英数字・記号を半角に統一して前後の空白を除去する"""
    return unicodedata.normalize("NFKC", text).strip()


def _parse_date(raw: str) -> str:
    """YYYY/M/D または YYYY/MM/DD → YYYY-MM-DD"""
    parts = raw.strip().split("/")
    return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def _parse_payment_month_col(raw: str) -> str:
    """'26/05 → 2026-05"""
    raw = raw.strip().lstrip("'")
    parts = raw.split("/")
    year = 2000 + int(parts[0])
    month = int(parts[1])
    return f"{year:04d}-{month:02d}"


def _parse_yyyy_mm(raw: str) -> str:
    raw = _normalize(raw).replace("/", "-")
    parts = raw.split("-")
    return f"{int(parts[0]):04d}-{int(parts[1]):02d}"


def _looks_like_date(text: str) -> bool:
    return bool(re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", text.strip()))


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _payment_month_from_filename(path: Path) -> str | None:
    """202604.csv → 2026-04"""
    m = re.match(r"(\d{4})(\d{2})", path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def _project_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def _card_csv_config() -> dict[str, Any]:
    cfg = load_config().get("card_csv")
    if cfg is None:
        return DEFAULT_CARD_CSV_CONFIG
    merged = DEFAULT_CARD_CSV_CONFIG | cfg
    if "formats" not in cfg:
        merged["formats"] = DEFAULT_CARD_CSV_CONFIG["formats"]
    return merged


def _decode_csv(raw: bytes, encodings: list[str]) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        return raw.decode(encodings[-1], errors="replace")
    return raw.decode("utf-8", errors="replace")


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


def _first_value(row: list[str], columns: int | list[int]) -> str:
    candidates = columns if isinstance(columns, list) else [columns]
    for col in candidates:
        value = _cell(row, int(col))
        if value:
            return value
    return ""


def _parse_amount(raw: str) -> int:
    normalized = _normalize(raw).replace(",", "").replace("円", "")
    return int(normalized)


def _parse_payment_month(raw: str, parser: str) -> str:
    if parser == "yy/mm":
        return _parse_payment_month_col(raw)
    if parser == "yyyy-mm":
        return _parse_yyyy_mm(raw)
    raise CsvConfigError(f"未対応のpayment_month parserです: {parser}")


def _payment_month_for_row(row: list[str], path: Path, spec: dict[str, Any]) -> str:
    source = spec.get("source", "column")
    parser = spec.get("parser", "yyyy-mm")
    if source == "filename":
        if parser != "yyyymm":
            raise CsvConfigError(f"未対応のfilename payment_month parserです: {parser}")
        payment_month = _payment_month_from_filename(path)
        if payment_month:
            return payment_month
        if spec.get("fallback") == "current_month":
            return datetime.today().strftime("%Y-%m")
        raise ValueError(f"ファイル名から支払月を取得できません: {path.name}")
    if source == "column":
        column = int(spec["column"])
        raw = _cell(row, column)
        if not raw:
            raise ValueError("支払月の列が空です")
        return _parse_payment_month(raw, parser)
    raise CsvConfigError(f"未対応のpayment_month sourceです: {source}")


def _format_matches(rows: list[list[str]], fmt: dict[str, Any]) -> bool:
    detect = fmt.get("detect", {})
    if "first_column_is_date" not in detect:
        return True
    first_column_is_date = bool(rows and rows[0] and _looks_like_date(rows[0][0]))
    return first_column_is_date == bool(detect["first_column_is_date"])


def _detect_format(rows: list[list[str]], formats: list[dict[str, Any]]) -> dict[str, Any]:
    for fmt in formats:
        if _format_matches(rows, fmt):
            return fmt
    names = ", ".join(str(fmt.get("name", "(unnamed)")) for fmt in formats)
    raise ValueError(f"対応するCSVフォーマットが見つかりません: {names}")


def _parse_rows(rows: list[list[str]], path: Path, fmt: dict[str, Any]) -> list[dict[str, Any]]:
    columns = fmt["columns"]
    used_on_col = int(columns["used_on"])
    records = []
    for row in rows:
        if not _looks_like_date(_cell(row, used_on_col)):
            continue
        try:
            amount_raw = _first_value(row, columns["amount"])
            if not amount_raw:
                continue
            records.append({
                "used_on": _parse_date(_cell(row, used_on_col)),
                "merchant": _normalize(_cell(row, int(columns["merchant"]))),
                "amount": _parse_amount(amount_raw),
                "payment_month": _payment_month_for_row(row, path, fmt["payment_month"]),
            })
        except CsvConfigError:
            raise
        except (ValueError, IndexError, KeyError):
            continue
    return records


def parse_csv(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    cfg = _card_csv_config()
    text = _decode_csv(raw, list(cfg.get("encodings", ["cp932", "utf-8"])))

    reader = csv.reader(text.splitlines())
    rows = list(reader)

    fmt = _detect_format(rows, list(cfg.get("formats", [])))
    return _parse_rows(rows, path, fmt)


def import_directory(
    conn: sqlite3.Connection, directory: Path | None = None
) -> dict[str, Any]:
    """ディレクトリ内の全CSVを走査して取り込む。重複はスキップ"""
    cfg = _card_csv_config()
    target = Path(directory) if directory else _project_path(str(cfg.get("default_inbox", "data/inbox/card")))
    csv_files = sorted(target.glob("*.csv"))
    if not csv_files:
        return {"imported": 0, "skipped": 0, "errors": [], "files": 0}

    total_imported = 0
    skipped = 0
    errors: list[str] = []

    for csv_path in csv_files:
        try:
            result = import_csv(conn, csv_path)
            total_imported += result["imported"]
        except ValueError:
            # 重複ファイルはスキップ
            skipped += 1
        except Exception as exc:
            errors.append(f"{csv_path.name}: {exc}")

    return {
        "imported": total_imported,
        "skipped": skipped,
        "errors": errors,
        "files": len(csv_files),
    }


def import_csv(conn: sqlite3.Connection, path: Path) -> dict[str, int]:
    """CSVを取り込み、件数を返す。二重取り込みは file_hash で防ぐ"""
    path = Path(path)
    fhash = _file_hash(path)

    existing = conn.execute(
        "SELECT id, status FROM imports WHERE file_hash = ?", (fhash,)
    ).fetchone()
    if existing:
        raise ValueError(f"このファイルはすでに取り込み済みです (imports.id={existing['id']})")

    import_id = conn.execute(
        """
        INSERT INTO imports (source_type, source_name, file_path, file_hash, status)
        VALUES ('credit_card_csv', ?, ?, ?, 'importing')
        """,
        (path.name, str(path), fhash),
    ).lastrowid

    try:
        records = parse_csv(path)
        for rec in records:
            conn.execute(
                """
                INSERT INTO card_transactions (used_on, merchant, amount, payment_month)
                VALUES (?, ?, ?, ?)
                """,
                (rec["used_on"], rec["merchant"], rec["amount"], rec["payment_month"]),
            )
        conn.execute(
            """
            UPDATE imports
            SET status = 'done', imported_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (import_id,),
        )
    except Exception as exc:
        conn.execute(
            "UPDATE imports SET status = 'error', error_message = ? WHERE id = ?",
            (str(exc), import_id),
        )
        raise

    return {"imported": len(records), "import_id": import_id}
