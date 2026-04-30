from __future__ import annotations

import argparse
from pathlib import Path

from finance_core.db import DEFAULT_DB_PATH, connect, init_db
from finance_core.services.commands import handle_command


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
