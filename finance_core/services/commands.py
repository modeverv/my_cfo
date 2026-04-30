from __future__ import annotations

import shlex
import sqlite3
from pathlib import Path
from typing import Callable

from finance_core.importers.credit_card_csv import import_csv, import_directory
from finance_core.llm import chat_completion
from finance_core.services.ask_context import (
    build_ask_prompt,
    build_finance_context,
    card_billing_month,
    refresh_card_unbilled,
)
from finance_core.services.manual_snapshots import (
    cash_add,
    cash_out,
    set_bank_total,
    set_securities_total,
    set_wallet_total,
)
from finance_core.services.now import show_card, show_now, show_wallet
from finance_core.services.snapshots import format_snapshot
from finance_core.services.transfers import transfer


# ── 引数ヘルパー ──────────────────────────────────────────

def parse_amount(raw: str, *, allow_zero: bool = True) -> int:
    try:
        amount = int(raw)
    except ValueError as exc:
        raise ValueError(f"金額は整数で指定してください: {raw}") from exc
    if allow_zero and amount < 0:
        raise ValueError("金額は0以上で指定してください")
    if not allow_zero and amount <= 0:
        raise ValueError("金額は1以上で指定してください")
    return amount


def require_args(parts: list[str], expected: int, usage: str) -> None:
    if len(parts) != expected:
        raise ValueError(f"使い方: {usage}")


# ── コマンドハンドラー ────────────────────────────────────

def cmd_now(conn: sqlite3.Connection, parts: list[str]) -> str:
    return show_now(conn)


def cmd_set_bank(conn: sqlite3.Connection, parts: list[str]) -> str:
    require_args(parts, 2, "/set-bank <amount>")
    return "銀行残高を更新しました\n" + format_snapshot(set_bank_total(conn, parse_amount(parts[1])))


def cmd_set_securities(conn: sqlite3.Connection, parts: list[str]) -> str:
    require_args(parts, 2, "/set-securities <amount>")
    return "証券評価額を更新しました\n" + format_snapshot(set_securities_total(conn, parse_amount(parts[1])))


def cmd_cash_set(conn: sqlite3.Connection, parts: list[str]) -> str:
    require_args(parts, 2, "/cash-set <amount>")
    return "財布残高を設定しました\n" + format_snapshot(set_wallet_total(conn, parse_amount(parts[1])))


def cmd_cash_in(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 3:
        raise ValueError("使い方: /cash-in <amount> <memo>")
    amount = parse_amount(parts[1], allow_zero=False)
    memo = " ".join(parts[2:])
    return f"財布に {amount:,}円 追加しました: {memo}\n" + format_snapshot(cash_add(conn, amount, memo))


def cmd_cash_out(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 3:
        raise ValueError("使い方: /cash-out <amount> <memo>")
    amount = parse_amount(parts[1], allow_zero=False)
    memo = " ".join(parts[2:])
    return f"財布から {amount:,}円 支出しました: {memo}\n" + format_snapshot(cash_out(conn, amount, memo))


def cmd_cash(conn: sqlite3.Connection, parts: list[str]) -> str:
    return show_wallet(conn)


def cmd_import_card(conn: sqlite3.Connection, parts: list[str]) -> str:
    path = Path(parts[1]) if len(parts) > 1 else None
    if path is not None and path.is_file():
        imported = import_csv(conn, path)
        result = {
            "files": 1,
            "imported": imported["imported"],
            "skipped": imported["skipped"],
            "skipped_rows": imported.get("skipped_rows", 0),
            "errors": [],
        }
    else:
        result = import_directory(conn, path)
    snapshot = refresh_card_unbilled(conn, card_billing_month())
    lines = [
        f"{result['files']}ファイルを走査: "
        f"{result['imported']}件取り込み / {result['skipped']}件スキップ(重複)"
    ]
    if result.get("skipped_rows", 0) and not any("行をスキップ" in err for err in result["errors"]):
        lines.append(f"  WARN: {result['skipped_rows']}行をスキップ")
    for err in result["errors"]:
        lines.append(f"  ERROR: {err}")
    lines.append(format_snapshot(snapshot))
    return "\n".join(lines)


def cmd_import(conn: sqlite3.Connection, parts: list[str]) -> str:
    return cmd_import_card(conn, parts)


def cmd_card(conn: sqlite3.Connection, parts: list[str]) -> str:
    arg = parts[1] if len(parts) > 1 else "this_month"
    month = card_billing_month() if arg == "this_month" else arg
    return show_card(conn, month)


def cmd_atm(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("使い方: /atm <amount> [memo]")
    amount = parse_amount(parts[1], allow_zero=False)
    memo = " ".join(parts[2:]) if len(parts) > 2 else "ATM引き出し"
    result = transfer(conn, "bank", "wallet", amount, memo)
    return (
        f"銀行から財布へ {amount:,}円を移しました ({memo})\n"
        "総資産は変わりません\n"
        + format_snapshot(result["snapshot"])
    )


def cmd_transfer(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 4:
        raise ValueError("使い方: /transfer <from> <to> <amount> [memo]")
    from_account = parts[1]
    to_account = parts[2]
    amount = parse_amount(parts[3], allow_zero=False)
    memo = " ".join(parts[4:]) if len(parts) > 4 else None
    result = transfer(conn, from_account, to_account, amount, memo)
    return (
        f"{from_account} から {to_account} へ {amount:,}円を移しました"
        + (f" ({memo})" if memo else "")
        + "\n総資産は変わりません\n"
        + format_snapshot(result["snapshot"])
    )


def cmd_ask(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("/ask <質問> の形式で指定してください")
    question = " ".join(parts[1:])
    prompt = build_ask_prompt(build_finance_context(conn, question), question)
    print("LLMに問い合わせ中です、お待ちください...", flush=True)
    return chat_completion(prompt)


def cmd_help(conn: sqlite3.Connection, parts: list[str]) -> str:
    return (
        "── コマンド一覧 ──\n"
        "  /now                       現在の資産状況\n"
        "  /set-bank <amount>         銀行残高を更新\n"
        "  /set-securities <amount>   証券評価額を更新\n"
        "  /cash-set <amount>         財布残高を補正\n"
        "  /cash-in <amount> <memo>   財布に入金\n"
        "  /cash-out <amount> <memo>  財布から支出\n"
        "  /cash                      財布の取引履歴\n"
        "  /atm <amount> [memo]       銀行→財布へATM引き出し\n"
        "  /transfer <from> <to> <amount> [memo]  振替\n"
        "  /import-card [dir]         カードCSVを一括取り込み\n"
        "  /import [dir]              /import-card の別名\n"
        "  /card [this_month|YYYY-MM] カード利用集計（this_monthは支払月ベース）\n"
        "  /ask <質問>                LLMに分析を依頼\n"
        "  /help                      このヘルプを表示\n"
    )


# ── ディスパッチ ──────────────────────────────────────────

_COMMANDS: dict[str, Callable[[sqlite3.Connection, list[str]], str]] = {
    "/now":            cmd_now,
    "/set-bank":       cmd_set_bank,
    "/set-securities": cmd_set_securities,
    "/cash-set":       cmd_cash_set,
    "/cash-in":        cmd_cash_in,
    "/cash-out":       cmd_cash_out,
    "/cash":           cmd_cash,
    "/import-card":    cmd_import_card,
    "/import":         cmd_import,
    "/card":           cmd_card,
    "/atm":            cmd_atm,
    "/transfer":       cmd_transfer,
    "/ask":            cmd_ask,
    "/help":           cmd_help,
}


def handle_command(conn: sqlite3.Connection, command_line: str) -> str:
    parts = shlex.split(command_line)
    if not parts:
        return ""
    handler = _COMMANDS.get(parts[0])
    if handler is None:
        raise ValueError(f"未対応コマンドです: {parts[0]}")
    return handler(conn, parts)


def run_command(db_path: str | Path, command_line: str) -> str:
    from finance_core.db import connect

    with connect(db_path) as conn:
        try:
            output = handle_command(conn, command_line)
            conn.commit()
            return output
        except Exception:
            conn.rollback()
            raise
