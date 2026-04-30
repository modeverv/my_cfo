from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


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


# ---------------------------------------------------------------------------
# Format A: Amazonマスター明細
#   列: 利用日, 利用店名, 利用金額, 支払回数計, 今回回数, 今回支払額, 備考
#   ヘッダー行あり（日付で始まらない行はスキップ）
#   payment_month はファイル名から取得
# ---------------------------------------------------------------------------

def _parse_format_a(rows: list[list[str]], payment_month: str) -> list[dict[str, Any]]:
    records = []
    for row in rows:
        if len(row) < 6:
            continue
        if not _looks_like_date(row[0]):
            continue
        amount_raw = row[5].strip()
        if not amount_raw:
            continue
        try:
            amount = int(amount_raw)
        except ValueError:
            continue
        records.append({
            "used_on": _parse_date(row[0]),
            "merchant": _normalize(row[1]),
            "amount": amount,
            "payment_month": payment_month,
        })
    return records


# ---------------------------------------------------------------------------
# Format B: 別カード明細
#   列: 利用日, 利用店名, 名義, 支払方法, 分割情報, 支払月, 利用金額, 今回支払額, ...
#   ヘッダー行なし
#   payment_month は col[5] から取得
# ---------------------------------------------------------------------------

def _parse_format_b(rows: list[list[str]]) -> list[dict[str, Any]]:
    records = []
    for row in rows:
        if len(row) < 7:
            continue
        if not _looks_like_date(row[0]):
            continue
        payment_month_raw = row[5].strip()
        if not payment_month_raw:
            continue
        try:
            payment_month = _parse_payment_month_col(payment_month_raw)
        except (ValueError, IndexError):
            continue

        # 今回支払額(col[7])が空の場合は利用金額(col[6])を使う（外貨決済など）
        amount_raw = row[7].strip() if len(row) > 7 else ""
        if not amount_raw:
            amount_raw = row[6].strip()
        try:
            amount = int(amount_raw)
        except ValueError:
            continue

        records.append({
            "used_on": _parse_date(row[0]),
            "merchant": _normalize(row[1]),
            "amount": amount,
            "payment_month": payment_month,
        })
    return records


def _detect_format(rows: list[list[str]]) -> str:
    """先頭行の第0列が日付かどうかでフォーマットを判定"""
    if rows and _looks_like_date(rows[0][0]):
        return "B"
    return "A"


def parse_csv(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.reader(text.splitlines())
    rows = list(reader)

    fmt = _detect_format(rows)
    if fmt == "A":
        payment_month = _payment_month_from_filename(path) or datetime.today().strftime("%Y-%m")
        return _parse_format_a(rows, payment_month)
    else:
        return _parse_format_b(rows)


DEFAULT_INBOX = Path(__file__).resolve().parents[2] / "data" / "inbox" / "card"


def import_directory(
    conn: sqlite3.Connection, directory: Path | None = None
) -> dict[str, Any]:
    """ディレクトリ内の全CSVを走査して取り込む。重複はスキップ"""
    target = Path(directory) if directory else DEFAULT_INBOX
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
