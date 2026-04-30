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

        self.write("[bold #00ff66]── 高額カード決済 TOP5 ──[/bold #00ff66]")
        for t in card_summary["large_transactions"][:5]:
            merchant = str(t["merchant"])[:18]
            self.write(f"  [#007733]{t['used_on']}[/#007733]  {merchant:<18}  [yellow]{int(t['amount']):>8,}円[/yellow]")

        self.write("")
        self.write("[bold #00ff66]── 今月の現金支出 ──[/bold #00ff66]")
        if wallet_summary["large_cash_out"]:
            for w in wallet_summary["large_cash_out"][:5]:
                desc = str(w["description"])[:16] if w["description"] else "-"
                self.write(f"  [#007733]{w['occurred_on']}[/#007733]  {desc:<16}  [yellow]{int(w['amount']):>8,}円[/yellow]")
        else:
            self.write("  [dim]（記録なし）[/dim]")

        self.write("")
        self.write("[bold #00ff66]── 最近の振替 ──[/bold #00ff66]")
        if transfers:
            for tr in transfers:
                memo = f" [dim]{str(tr['memo'])}[/dim]" if tr["memo"] else ""
                from_acc = str(tr["from_account"])
                to_acc   = str(tr["to_account"])
                self.write(f"  [#007733]{tr['occurred_on']}[/#007733]  [cyan]{from_acc}→{to_acc}[/cyan]  {int(tr['amount']):,}円{memo}")
        else:
            self.write("  [dim]（記録なし）[/dim]")


# ── メインアプリ ──────────────────────────────────────────

class FinanceApp(App):
    _MAIN_PANE  = "#main-pane"
    _SIDE_PANE  = "#side-pane"
    _CMD_INPUT  = "#cmd-input"
    _STATUS_HDR = "#status-header"

    CSS = """
    /* ── レトログリーン基調 ── */
    Screen {
        background: #050f05;
        color: #00e040;
    }

    StatusHeader {
        background: #003310;
        color: #00ff66;
        height: 1;
        padding: 0 1;
        text-style: bold;
    }

    #main-pane {
        background: #050f05;
        color: #00e040;
        width: 3fr;
        border-right: solid #006622;
        scrollbar-color: #006622;
        scrollbar-background: #030a03;
    }

    #side-pane {
        background: #030a03;
        color: #00b030;
        width: 2fr;
        scrollbar-color: #006622;
        scrollbar-background: #030a03;
    }

    #input-bar {
        background: #020802;
        height: 3;
        border-top: solid #006622;
        padding: 0 1;
    }

    Input {
        background: #020802;
        color: #00ff66;
        border: solid #004d18;
    }

    Input:focus {
        border: solid #00ff66;
        color: #00ff66;
    }

    Footer {
        background: #003310;
        color: #00cc44;
    }

    Footer .footer--key {
        background: #005522;
        color: #00ff66;
    }
    """

    BINDINGS = [
        Binding("f1",  "show_help",     "Help"),
        Binding("f2",  "cmd_now",       "Now"),
        Binding("f3",  "cmd_card",      "Card"),
        Binding("f4",  "cmd_cash",      "Cash"),
        Binding("f5",  "focus_atm",     "ATM"),
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
        self.query_one(self._CMD_INPUT, Input).focus()

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
        main_log = self.query_one(self._MAIN_PANE, RichLog)
        main_log.write(f"[bold #00ff66]fin>[/bold #00ff66] [#00cc44]{command_line}[/#00cc44]")

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
        main_log = self.query_one(self._MAIN_PANE, RichLog)
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
        self.query_one(self._STATUS_HDR, StatusHeader).refresh_stats(self.db_path)
        self.query_one(self._SIDE_PANE, SidePane).refresh_side(self.db_path)

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
            "  /atm <amount> [memo]             銀行→財布へATM引き出し\n"
            "  /import [dir]             CSVを一括取り込み（重複スキップ）\n"
            "  /card [this_month|YYYY-MM] カード利用集計\n"
            "  /ask <質問>               LLMに分析を依頼\n"
        )
        self.query_one(self._MAIN_PANE, RichLog).write(help_text)

    def action_cmd_now(self) -> None:
        self._run_command("/now")

    def action_cmd_card(self) -> None:
        self._run_command("/card this_month")

    def action_cmd_cash(self) -> None:
        self._run_command("/cash")

    def action_focus_atm(self) -> None:
        inp = self.query_one(self._CMD_INPUT, Input)
        inp.value = "/atm "
        inp.focus()
        inp.cursor_position = len(inp.value)  # type: ignore[arg-type]

    def action_focus_ask(self) -> None:
        inp = self.query_one(self._CMD_INPUT, Input)
        inp.value = "/ask "
        inp.focus()
        inp.cursor_position = len(inp.value)  # type: ignore[arg-type]


def main(db_path: Path = DEFAULT_DB_PATH) -> None:
    FinanceApp(db_path=db_path).run()


if __name__ == "__main__":
    main()
