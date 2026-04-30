from __future__ import annotations

import argparse
import shlex
import sqlite3
from pathlib import Path

from finance_core.db import DEFAULT_DB_PATH, connect, init_db
from finance_core.llm import chat_completion
from finance_core.services.ask_context import build_ask_prompt, build_finance_context
from finance_core.services.manual_snapshots import (
    cash_in,
    cash_out,
    set_bank_total,
    set_securities_total,
    set_wallet_total,
)
from finance_core.importers.credit_card_csv import import_csv, import_directory
from finance_core.services.ask_context import card_billing_month, current_month, refresh_card_unbilled
from finance_core.services.now import show_card, show_now, show_wallet
from finance_core.services.transfers import transfer
from finance_core.services.snapshots import format_snapshot


def parse_amount(raw: str) -> int:
    try:
        amount = int(raw)
    except ValueError as exc:
        raise ValueError(f"金額は整数で指定してください: {raw}") from exc
    if amount < 0:
        raise ValueError("金額は0以上で指定してください")
    return amount


def handle_command(conn: sqlite3.Connection, command_line: str) -> str:
    parts = shlex.split(command_line)
    if not parts:
        return ""

    command = parts[0]
    if command == "/now":
        return show_now(conn)

    if command == "/set-bank":
        require_args(parts, 2, "/set-bank <amount>")
        snapshot = set_bank_total(conn, parse_amount(parts[1]))
        return "銀行残高を更新しました\n" + format_snapshot(snapshot)

    if command == "/set-securities":
        require_args(parts, 2, "/set-securities <amount>")
        snapshot = set_securities_total(conn, parse_amount(parts[1]))
        return "証券評価額を更新しました\n" + format_snapshot(snapshot)

    if command == "/cash-set":
        require_args(parts, 2, "/cash-set <amount>")
        snapshot = set_wallet_total(conn, parse_amount(parts[1]))
        return "財布残高を設定しました\n" + format_snapshot(snapshot)

    if command == "/cash-in":
        if len(parts) < 3:
            raise ValueError("使い方: /cash-in <amount> <memo>")
        amount = parse_amount(parts[1])
        memo = " ".join(parts[2:])
        snapshot = cash_in(conn, amount, memo)
        return f"財布に {amount:,}円 入金しました: {memo}\n" + format_snapshot(snapshot)

    if command == "/cash-out":
        if len(parts) < 3:
            raise ValueError("使い方: /cash-out <amount> <memo>")
        amount = parse_amount(parts[1])
        memo = " ".join(parts[2:])
        snapshot = cash_out(conn, amount, memo)
        return f"財布から {amount:,}円 支出しました: {memo}\n" + format_snapshot(snapshot)

    if command == "/cash":
        return show_wallet(conn)

    if command == "/import":
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

    if command == "/import-card":
        require_args(parts, 2, "/import-card <path>")
        result = import_csv(conn, parts[1])
        snapshot = refresh_card_unbilled(conn, card_billing_month())
        return (
            f"{result['imported']}件のカード明細を取り込みました\n"
            + format_snapshot(snapshot)
        )

    if command == "/card":
        arg = parts[1] if len(parts) > 1 else "this_month"
        month = card_billing_month() if arg == "this_month" else arg
        return show_card(conn, month)

    if command == "/transfer":
        if len(parts) < 4:
            raise ValueError("使い方: /transfer <from> <to> <amount> [memo]")
        from_key = parts[1]
        to_key = parts[2]
        amount = parse_amount(parts[3])
        memo = " ".join(parts[4:]) if len(parts) > 4 else None
        result = transfer(conn, from_key, to_key, amount, memo)
        memo_str = f" ({memo})" if memo else ""
        msg = f"{from_key}から{to_key}へ {amount:,}円を振替しました{memo_str}\n総資産は変わりません\n"
        return msg + format_snapshot(result["snapshot"])

    if command == "/ask":
        if len(parts) < 2:
            raise ValueError("/ask <質問> の形式で指定してください")
        question = " ".join(parts[1:])
        context = build_finance_context(conn, question)
        prompt = build_ask_prompt(context, question)
        print("LLMに問い合わせ中です、お待ちください...", flush=True)
        return chat_completion(prompt)

    raise ValueError(f"未対応コマンドです: {command}")


def require_args(parts: list[str], expected: int, usage: str) -> None:
    if len(parts) != expected:
        raise ValueError(f"使い方: {usage}")


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
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Command to run once. Omit to start the CLI loop.",
    )
    args = parser.parse_args()

    init_db(args.db)
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
