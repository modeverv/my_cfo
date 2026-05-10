from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from finance_core.services.snapshots import insert_snapshot


def import_bitflyer_balance(conn: sqlite3.Connection, amount: int) -> dict[str, Any]:
    """
    bitFlyerの評価額（日本円換算）を手動またはCSVから更新する想定の関数。
    現在は金額を直接受け取ってsnapshotを更新する。
    """
    return insert_snapshot(conn, crypto_total=amount, memo="bitflyer-import")


def import_bitflyer_csv(conn: sqlite3.Connection, file_path: Path) -> dict[str, Any]:
    """
    bitFlyerの「お取引レポート」等のCSVを取り込むためのスケルトン。
    将来的にここでCSVをパースし、最終的な残高を計算したり、
    取引履歴を別のテーブルに保存したりする。
    """
    # TODO: CSVパースの実装
    # bitFlyerのCSVはBOM付きUTF-8であることが多い
    # 列: 日時, 内容, 通貨, 金額, 手数料, 合計, 備考 など
    
    file_content = file_path.read_bytes()
    file_hash = hashlib.sha256(file_content).hexdigest()

    # 重複チェック
    existing = conn.execute(
        "SELECT id FROM imports WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if existing:
        return {"imported": 0, "skipped": 1, "errors": []}

    # 仮の実装: ファイルの存在を記録するだけ
    conn.execute(
        """
        INSERT INTO imports (source_type, source_name, file_path, file_hash, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("crypto", "bitflyer", str(file_path), file_hash, "imported"),
    )

    return {"imported": 1, "skipped": 0, "errors": ["CSVパースは未実装です。残高は /set-crypto で更新してください。"]}
