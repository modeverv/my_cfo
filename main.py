from __future__ import annotations

import argparse
import shlex
import sqlite3
from pathlib import Path
from typing import Callable

from finance_core.db import DEFAULT_DB_PATH, connect, init_db
from finance_core.importers.credit_card_csv import import_directory
from finance_core.llm import chat_completion
from finance_core.services.ask_context import (
    build_ask_prompt,
    build_finance_context,
    card_billing_month,
    refresh_card_unbilled,
)
from finance_core.services.manual_snapshots import (
    cash_in,
    cash_out,
    set_bank_total,
    set_securities_total,
    set_wallet_total,
)
from finance_core.services.now import show_card, show_now, show_wallet
from finance_core.services.snapshots import format_snapshot
from finance_core.services.transfers import transfer


# ── 引数ヘルパー ──────────────────────────────────────────

def parse_amount(raw: str) -> int:
    try:
        amount = int(raw)
    except ValueError as exc:
        raise ValueError(f"金額は整数で指定してください: {raw}") from exc
    if amount < 0:
        raise ValueError("金額は0以上で指定してください")
    return amount


def require_args(parts: list[str], expected: int, usage: str) -> None:
    if len(parts) != expected:
        raise ValueError(f"使い方: {usage}")


# ── コマンドハンドラー ────────────────────────────────────

def _cmd_now(conn: sqlite3.Connection, parts: list[str]) -> str:
    return show_now(conn)


def _cmd_set_bank(conn: sqlite3.Connection, parts: list[str]) -> str:
    require_args(parts, 2, "/set-bank <amount>")
    return "銀行残高を更新しました\n" + format_snapshot(set_bank_total(conn, parse_amount(parts[1])))


def _cmd_set_securities(conn: sqlite3.Connection, parts: list[str]) -> str:
    require_args(parts, 2, "/set-securities <amount>")
    return "証券評価額を更新しました\n" + format_snapshot(set_securities_total(conn, parse_amount(parts[1])))


def _cmd_cash_set(conn: sqlite3.Connection, parts: list[str]) -> str:
    require_args(parts, 2, "/cash-set <amount>")
    return "財布残高を設定しました\n" + format_snapshot(set_wallet_total(conn, parse_amount(parts[1])))


def _cmd_cash_in(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 3:
        raise ValueError("使い方: /cash-in <amount> <memo>")
    amount = parse_amount(parts[1])
    memo = " ".join(parts[2:])
    return f"財布に {amount:,}円 入金しました: {memo}\n" + format_snapshot(cash_in(conn, amount, memo))


def _cmd_cash_out(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 3:
        raise ValueError("使い方: /cash-out <amount> <memo>")
    amount = parse_amount(parts[1])
    memo = " ".join(parts[2:])
    return f"財布から {amount:,}円 支出しました: {memo}\n" + format_snapshot(cash_out(conn, amount, memo))


def _cmd_cash(conn: sqlite3.Connection, parts: list[str]) -> str:
    return show_wallet(conn)


def _cmd_import(conn: sqlite3.Connection, parts: list[str]) -> str:
    directory = Path(parts[1]) if len(parts) > 1 else None
    result = import_directory(conn, directory)
    snapshot = refresh_card_unbilled(conn, card_billing_month())
    lines = [
        f"{result['files']}ファイルを走査: "
        f"{result['imported']}件取り込み / {result['skipped']}件スキップ(重複)"
    ]
    for err in result["errors"]:
        lines.append(f"  ERROR: {err}")
    lines.append(format_snapshot(snapshot))
    return "\n".join(lines)


def _cmd_card(conn: sqlite3.Connection, parts: list[str]) -> str:
    arg = parts[1] if len(parts) > 1 else "this_month"
    month = card_billing_month() if arg == "this_month" else arg
    return show_card(conn, month)


def _cmd_atm(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("使い方: /atm <amount> [memo]")
    amount = parse_amount(parts[1])
    memo = " ".join(parts[2:]) if len(parts) > 2 else "ATM引き出し"
    result = transfer(conn, "bank", "wallet", amount, memo)
    return (
        f"銀行から財布へ {amount:,}円を移しました ({memo})\n"
        "総資産は変わりません\n"
        + format_snapshot(result["snapshot"])
    )


def _cmd_ask(conn: sqlite3.Connection, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("/ask <質問> の形式で指定してください")
    question = " ".join(parts[1:])
    prompt = build_ask_prompt(build_finance_context(conn, question), question)
    print("LLMに問い合わせ中です、お待ちください...", flush=True)
    return chat_completion(prompt)


# ── ディスパッチテーブル ──────────────────────────────────

_COMMANDS: dict[str, Callable[[sqlite3.Connection, list[str]], str]] = {
    "/now":            _cmd_now,
    "/set-bank":       _cmd_set_bank,
    "/set-securities": _cmd_set_securities,
    "/cash-set":       _cmd_cash_set,
    "/cash-in":        _cmd_cash_in,
    "/cash-out":       _cmd_cash_out,
    "/cash":           _cmd_cash,
    "/import":         _cmd_import,
    "/card":           _cmd_card,
    "/atm":            _cmd_atm,
    "/ask":            _cmd_ask,
}


def handle_command(conn: sqlite3.Connection, command_line: str) -> str:
    parts = shlex.split(command_line)
    if not parts:
        return ""
    handler = _COMMANDS.get(parts[0])
    if handler is None:
        raise ValueError(f"未対応コマンドです: {parts[0]}")
    return handler(conn, parts)


# ── REPL / エントリーポイント ─────────────────────────────

def repl(db_path: Path) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        while True:
            try:
                line = input("fin> ").strip()
            except EOFError:
                print()
                return
            if line in {"q", "quit", "exit"}:
                return
            try:
                output = handle_command(conn, line)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                print(f"ERROR: {exc}")
                continue
            if output:
                print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Finance Console")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--tui", action="store_true", help="Launch TUI mode")
    parser.add_argument("command", nargs="*", help="Command to run once. Omit to start the CLI loop.")
    args = parser.parse_args()

    init_db(args.db)
    if args.tui:
        from fin_console.app import FinanceApp
        FinanceApp(db_path=args.db).run()
        return
    if not args.command:
        repl(args.db)
        return

    command_line = " ".join(args.command)
    with connect(args.db) as conn:
        try:
            output = handle_command(conn, command_line)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"ERROR: {exc}")
            raise SystemExit(1)
    if output:
        print(output)


if __name__ == "__main__":
    main()
