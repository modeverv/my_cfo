from __future__ import annotations

import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from finance_core.db import DEFAULT_DB_PATH, connect, init_db
from finance_core.services.ask_context import (
    card_billing_month,
    current_month,
    get_card_month_summary,
    get_recent_transfers,
    get_wallet_month_summary,
)
from finance_core.services.snapshots import get_latest_snapshot


# ── ヘッダー ──────────────────────────────────────────────

class StatusHeader(Static):
    def refresh_stats(self, db_path: Path) -> None:
        with connect(db_path) as conn:
            snap = get_latest_snapshot(conn)
        as_of = snap["as_of_date"]
        total = snap["total_assets"]
        card  = snap["credit_card_unbilled"]
        wallet = snap["wallet_total"]

        def fmt(n: int) -> str:
            if abs(n) >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if abs(n) >= 1_000:
                return f"{n / 1_000:.0f}K"
            return str(n)

        self.update(
            f" as_of: {as_of} │ total: {fmt(total)} │ card: {fmt(card)} │ wallet: {fmt(wallet)}"
        )


# ── サイドパネル ──────────────────────────────────────────

class SidePane(RichLog):
    def refresh_side(self, db_path: Path) -> None:
        self.clear()
        with connect(db_path) as conn:
            billing = card_billing_month()
            usage   = current_month()
            card_summary = get_card_month_summary(conn, billing)
            wallet_summary = get_wallet_month_summary(conn, usage)
            transfers = get_recent_transfers(conn, limit=5)

        self.write("[bold]── 高額カード決済 TOP5 ──[/bold]")
        for t in card_summary["large_transactions"][:5]:
            self.write(f"  {t['used_on']}  {t['merchant'][:18]:<18}  {t['amount']:>8,}円")

        self.write("")
        self.write("[bold]── 今月の現金支出 ──[/bold]")
        if wallet_summary["large_cash_out"]:
            for w in wallet_summary["large_cash_out"][:5]:
                desc = w["description"][:16] if w["description"] else "-"
                self.write(f"  {w['occurred_on']}  {desc:<16}  {w['amount']:>8,}円")
        else:
            self.write("  （記録なし）")

        self.write("")
        self.write("[bold]── 最近の振替 ──[/bold]")
        if transfers:
            for tr in transfers:
                memo = f" {tr['memo']}" if tr["memo"] else ""
                self.write(f"  {tr['occurred_on']}  {tr['from_account']}→{tr['to_account']}  {tr['amount']:,}円{memo}")
        else:
            self.write("  （記録なし）")


# ── メインアプリ ──────────────────────────────────────────

class FinanceApp(App):
    CSS = """
    StatusHeader {
        background: $primary;
        color: $text;
        height: 1;
        padding: 0 1;
    }
    #main-pane {
        width: 3fr;
        border-right: solid $primary;
    }
    #side-pane {
        width: 2fr;
    }
    #input-bar {
        height: 3;
        border-top: solid $primary;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("f1",  "show_help",     "Help"),
        Binding("f2",  "cmd_now",       "Now"),
        Binding("f3",  "cmd_card",      "Card"),
        Binding("f4",  "cmd_cash",      "Cash"),
        Binding("f5",  "focus_transfer","Transfer"),
        Binding("f6",  "focus_ask",     "Ask"),
        Binding("f10", "quit",          "Quit"),
    ]

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        super().__init__()
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield StatusHeader(id="status-header")
        with Horizontal():
            yield RichLog(id="main-pane",  highlight=True, markup=True, wrap=True)
            yield SidePane(id="side-pane", highlight=True, markup=True, wrap=True)
        with Vertical(id="input-bar"):
            yield Input(placeholder="fin> コマンドを入力 (例: /now  /ask 今月は？)", id="cmd-input")
        yield Footer()

    def on_mount(self) -> None:
        init_db(self.db_path)
        self._refresh_all()
        self.query_one("#cmd-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.clear()
        if not line:
            return
        if line in {"q", "quit", "exit"}:
            self.exit()
            return
        self._run_command(line)

    # ── コマンド実行 ─────────────────────────────────────

    def _run_command(self, command_line: str) -> None:
        main_log = self.query_one("#main-pane", RichLog)
        main_log.write(f"[bold cyan]fin>[/bold cyan] {command_line}")

        # /ask は時間がかかるのでスレッドで実行
        if command_line.startswith("/ask"):
            main_log.write("[dim]LLMに問い合わせ中です、お待ちください...[/dim]")
            threading.Thread(
                target=self._run_ask_thread,
                args=(command_line,),
                daemon=True,
            ).start()
            return

        try:
            from main import handle_command
            with connect(self.db_path) as conn:
                output = handle_command(conn, command_line)
                conn.commit()
            if output:
                main_log.write(output)
        except Exception as exc:
            main_log.write(f"[red]ERROR: {exc}[/red]")

        self._refresh_all()

    def _run_ask_thread(self, command_line: str) -> None:
        main_log = self.query_one("#main-pane", RichLog)
        try:
            from main import handle_command
            with connect(self.db_path) as conn:
                output = handle_command(conn, command_line)
                conn.commit()
            self.call_from_thread(main_log.write, output or "")
        except Exception as exc:
            self.call_from_thread(main_log.write, f"[red]ERROR: {exc}[/red]")
        self.call_from_thread(self._refresh_all)

    def _refresh_all(self) -> None:
        self.query_one("#status-header", StatusHeader).refresh_stats(self.db_path)
        self.query_one("#side-pane", SidePane).refresh_side(self.db_path)

    # ── キーバインド ─────────────────────────────────────

    def action_show_help(self) -> None:
        help_text = (
            "[bold]── コマンド一覧 ──[/bold]\n"
            "  /now                      現在の資産状況\n"
            "  /set-bank <amount>        銀行残高を更新\n"
            "  /set-securities <amount>  証券評価額を更新\n"
            "  /cash-set <amount>        財布残高を補正\n"
            "  /cash-in <amount> <memo>  財布に入金\n"
            "  /cash-out <amount> <memo> 財布から支出\n"
            "  /cash                     財布の取引履歴\n"
            "  /transfer <from> <to> <amount> [memo]\n"
            "  /import                   CSVを一括取り込み\n"
            "  /import-card <path>       CSVを個別取り込み\n"
            "  /card [this_month|YYYY-MM] カード利用集計\n"
            "  /ask <質問>               LLMに分析を依頼\n"
        )
        self.query_one("#main-pane", RichLog).write(help_text)

    def action_cmd_now(self) -> None:
        self._run_command("/now")

    def action_cmd_card(self) -> None:
        self._run_command("/card this_month")

    def action_cmd_cash(self) -> None:
        self._run_command("/cash")

    def action_focus_transfer(self) -> None:
        inp = self.query_one("#cmd-input", Input)
        inp.value = "/transfer "
        inp.focus()
        inp.cursor_position = len(inp.value)

    def action_focus_ask(self) -> None:
        inp = self.query_one("#cmd-input", Input)
        inp.value = "/ask "
        inp.focus()
        inp.cursor_position = len(inp.value)


def main(db_path: Path = DEFAULT_DB_PATH) -> None:
    FinanceApp(db_path=db_path).run()


if __name__ == "__main__":
    main()
