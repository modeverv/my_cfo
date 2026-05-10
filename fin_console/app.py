from __future__ import annotations

import threading
import re
from pathlib import Path
from typing import Any

from finance_core.display import fit as _fit

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from finance_core.db import DEFAULT_DB_PATH, connect, init_db
from finance_core.services.ask_context import (
    current_month,
    get_card_payment_month_summary,
    get_card_usage_month_summary,
    get_recent_transfers,
    get_wallet_month_summary,
)
from finance_core.services.commands import run_command
from finance_core.services.snapshots import get_latest_snapshot


COMMAND_COLOR = "#ff0066"
BASE_COLOR = "#00e040"
AMOUNT_COLOR = "#eeeeee"


def _command_markup(text: str) -> str:
    return f"[{COMMAND_COLOR}]{escape(text)}[/{COMMAND_COLOR}]"


def _base_markup(text: str) -> str:
    return f"[{BASE_COLOR}]{escape(text)}[/{BASE_COLOR}]"


def _amount_markup(text: str) -> str:
    return f"[{AMOUNT_COLOR}]{escape(text)}[/{AMOUNT_COLOR}]"


def _style_command_spec(spec: str) -> str:
    """Style command names and argument placeholders in a help command spec."""
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"/[A-Za-z0-9_-]+|<[^>\s]+>|\[[^\]\s]+(?:\|[^\]\s]+)?\]", spec):
        parts.append(escape(spec[pos:match.start()]))
        parts.append(_command_markup(match.group(0)))
        pos = match.end()
    parts.append(escape(spec[pos:]))
    return "".join(parts)


def _style_help_output(output: str) -> str:
    lines: list[str] = []
    for line in output.splitlines():
        if line.startswith("  /"):
            leading = line[: len(line) - len(line.lstrip())]
            rest = line[len(leading):]
            match = re.match(r"^(/[A-Za-z0-9_-]+(?:\s+(?:<[^>\s]+>|\[[^\]]+\]))*)(\s+)(.*)$", rest)
            if match:
                spec, gap, description = match.groups()
                lines.append(
                    escape(leading)
                    + _style_command_spec(spec)
                    + escape(gap)
                    + _base_markup(description)
                )
            else:
                lines.append(escape(leading) + _style_command_spec(rest))
        else:
            lines.append(_base_markup(line))
    return "\n".join(lines)


def _style_amount_lines(output: str) -> str:
    lines: list[str] = []
    for line in output.splitlines():
        match = re.match(r"^(.*?)(-?[\d,]+)(円)$", line)
        if match:
            label, amount, yen = match.groups()
            lines.append(_base_markup(label) + _amount_markup(amount) + _base_markup(yen))
        else:
            lines.append(_base_markup(line))
    return "\n".join(lines)


def _style_command_output(command_line: str, output: str) -> str:
    command = command_line.split(maxsplit=1)[0] if command_line.strip() else ""
    if command == "/help":
        return _style_help_output(output)
    if command in {"/now", "/set-bank", "/set-securities", "/cash-set", "/cash-in", "/cash-out", "/atm", "/transfer"}:
        return _style_amount_lines(output)
    return escape(output)


# ── 画面描画 ──────────────────────────────────────────────

class StatusHeader(Static):
    def update_stats(self, snap: dict[str, Any]) -> None:
        def fmt(n: int) -> str:
            if abs(n) >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if abs(n) >= 1_000:
                return f"{n / 1_000:.0f}K"
            return str(n)

        self.update(
            f" as_of: {snap['as_of_date']} │ total: {fmt(snap['total_assets'])}"
            f" │ card: {fmt(snap['credit_card_unbilled'])} │ wallet: {fmt(snap['wallet_total'])}"
        )


class SidePane(RichLog):
    def update_side(
        self,
        next_payment_summary: dict[str, Any],
        current_usage_summary: dict[str, Any],
        wallet_summary: dict[str, Any],
        transfers: list[dict[str, Any]],
    ) -> None:
        self.clear()

        self.write("[bold #00ff66]── 次回引落予定 TOP5 ──[/bold #00ff66]")
        for t in next_payment_summary["large_transactions"][:5]:
            merchant = _fit(str(t["merchant"]), 18)
            self.write(f"  [#007733]{t['used_on']}[/#007733]  {merchant}  [yellow]{int(t['amount']):>9,}円[/yellow]")

        self.write("")
        self.write("[bold #00ff66]── 今月カード利用 TOP5 ──[/bold #00ff66]")
        for t in current_usage_summary["large_transactions"][:5]:
            merchant = _fit(str(t["merchant"]), 18)
            self.write(f"  [#007733]{t['used_on']}[/#007733]  {merchant}  [yellow]{int(t['amount']):>9,}円[/yellow]")

        self.write("")
        self.write("[bold #00ff66]── 今月の現金支出 ──[/bold #00ff66]")
        if wallet_summary["large_cash_out"]:
            for w in wallet_summary["large_cash_out"][:5]:
                desc = _fit(str(w["description"]) if w["description"] else "-", 16)
                self.write(f"  [#007733]{w['occurred_on']}[/#007733]  {desc}  [yellow]{int(w['amount']):>9,}円[/yellow]")
        else:
            self.write("  [dim]（記録なし）[/dim]")

        self.write("")
        self.write("[bold #00ff66]── 最近の振替 ──[/bold #00ff66]")
        if transfers:
            for tr in transfers:
                memo = f" [dim]{str(tr['memo'])}[/dim]" if tr["memo"] else ""
                self.write(
                    f"  [#007733]{tr['occurred_on']}[/#007733]"
                    f"  [cyan]{tr['from_account']}→{tr['to_account']}[/cyan]"
                    f"  {int(tr['amount']):,}円{memo}"
                )
        else:
            self.write("  [dim]（記録なし）[/dim]")


# ── メインアプリ ──────────────────────────────────────────

class FinanceApp(App):
    MAIN_PANE_SELECTOR = "#main-pane"
    SIDE_PANE_SELECTOR = "#side-pane"
    CMD_INPUT_SELECTOR = "#cmd-input"
    STATUS_HEADER_SELECTOR = "#status-header"

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
        height: 5;
        border-top: solid #006622;
        padding: 0 1 1 1;
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
            yield RichLog(id="main-pane",  highlight=False, markup=True, wrap=True)
            yield SidePane(id="side-pane", highlight=False, markup=True, wrap=True)
        with Vertical(id="input-bar"):
            yield Input(placeholder="fin> コマンドを入力 (例: /now  /ask 今月は？)", id="cmd-input")
        yield Footer()

    def on_mount(self) -> None:
        init_db(self.db_path)
        self._refresh_all()
        self.query_one(self.CMD_INPUT_SELECTOR, Input).focus()

    # ── 入力処理 ─────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.clear()
        if not line:
            return
        if line in {"q", "quit", "exit"}:
            self.exit()
            return
        main_log = self.query_one(self.MAIN_PANE_SELECTOR, RichLog)
        main_log.write(f"[bold #00ff66]fin>[/bold #00ff66] [#00cc44]{escape(line)}[/#00cc44]")
        if line.startswith("/ask"):
            self._dispatch_ask(line)
        else:
            self._execute(line)

    # ── コマンド実行 ──────────────────────────────────────

    def _execute(self, command_line: str) -> None:
        main_log = self.query_one(self.MAIN_PANE_SELECTOR, RichLog)
        try:
            output = run_command(self.db_path, command_line)
            if output:
                main_log.write(_style_command_output(command_line, output))
        except Exception as exc:
            main_log.write(f"[red]ERROR: {exc}[/red]")
        self._refresh_all()

    # ── /ask 非同期処理 ───────────────────────────────────

    def _dispatch_ask(self, command_line: str) -> None:
        self.query_one(self.MAIN_PANE_SELECTOR, RichLog).write("[dim]LLMに問い合わせ中です、お待ちください...[/dim]")
        threading.Thread(target=self._ask_worker, args=(command_line,), daemon=True).start()

    def _ask_worker(self, command_line: str) -> None:
        main_log = self.query_one(self.MAIN_PANE_SELECTOR, RichLog)
        try:
            output = run_command(self.db_path, command_line)
            self.call_from_thread(main_log.write, output or "")
        except Exception as exc:
            self.call_from_thread(main_log.write, f"[red]ERROR: {exc}[/red]")
        self.call_from_thread(self._refresh_all)

    # ── 画面更新（データ取得 → ウィジェットへ渡す） ────────

    def _refresh_all(self) -> None:
        with connect(self.db_path) as conn:
            snap = get_latest_snapshot(conn)
            month = current_month()
            next_payment_summary = get_card_payment_month_summary(conn, month)
            current_usage_summary = get_card_usage_month_summary(conn, month)
            wallet_summary  = get_wallet_month_summary(conn, current_month())
            transfers       = get_recent_transfers(conn, limit=5)

        self.query_one(self.STATUS_HEADER_SELECTOR, StatusHeader).update_stats(snap)
        self.query_one(self.SIDE_PANE_SELECTOR, SidePane).update_side(
            next_payment_summary,
            current_usage_summary,
            wallet_summary,
            transfers,
        )

    # ── キーバインド ─────────────────────────────────────

    def action_show_help(self) -> None:
        self._execute("/help")

    def action_cmd_now(self) -> None:
        self.query_one(self.CMD_INPUT_SELECTOR, Input).clear()
        self._execute("/now")

    def action_cmd_card(self) -> None:
        self.query_one(self.CMD_INPUT_SELECTOR, Input).clear()
        self._execute("/card this_month")

    def action_cmd_cash(self) -> None:
        self.query_one(self.CMD_INPUT_SELECTOR, Input).clear()
        self._execute("/cash")

    def action_focus_atm(self) -> None:
        inp = self.query_one(self.CMD_INPUT_SELECTOR, Input)
        inp.value = "/atm "
        inp.focus()
        inp.cursor_position = len(inp.value)  # type: ignore[arg-type]

    def action_focus_ask(self) -> None:
        inp = self.query_one(self.CMD_INPUT_SELECTOR, Input)
        inp.value = "/ask "
        inp.focus()
        inp.cursor_position = len(inp.value)  # type: ignore[arg-type]


def main(db_path: Path = DEFAULT_DB_PATH) -> None:
    FinanceApp(db_path=db_path).run()


if __name__ == "__main__":
    main()
