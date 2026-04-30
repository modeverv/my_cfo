from __future__ import annotations

import unittest
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from finance_core.db import connect, init_db
from finance_core.importers.credit_card_csv import import_csv, import_directory, parse_csv
from finance_core.services.ask_context import (
    build_finance_context,
    card_billing_month,
    get_card_month_summary,
    refresh_card_unbilled,
)
from finance_core.services.commands import handle_command
from finance_core.services.manual_snapshots import cash_in, cash_out, set_wallet_total
from finance_core.services.snapshots import calculate_total, get_latest_snapshot
from finance_core.services.transfers import transfer
from finance_mcp.server import FinanceMcpServer


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "finance.sqlite3"
        init_db(self.db_path)
        self.conn = connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()


class SnapshotTests(DatabaseTestCase):
    def test_calculate_total_subtracts_credit_card_unbilled(self) -> None:
        self.assertEqual(
            calculate_total(
                bank_total=3_200_000,
                securities_total=58_800_000,
                wallet_total=42_000,
                credit_card_unbilled=230_000,
            ),
            61_812_000,
        )

    def test_set_commands_update_latest_snapshot(self) -> None:
        handle_command(self.conn, "/set-bank 3200000")
        handle_command(self.conn, "/set-securities 58800000")
        handle_command(self.conn, "/cash-set 42000")

        latest = get_latest_snapshot(self.conn)
        self.assertEqual(latest["bank_total"], 3_200_000)
        self.assertEqual(latest["securities_total"], 58_800_000)
        self.assertEqual(latest["wallet_total"], 42_000)
        self.assertEqual(latest["total_assets"], 62_042_000)


class WalletAndTransferTests(DatabaseTestCase):
    def test_cash_in_and_cash_out_change_total_assets(self) -> None:
        set_wallet_total(self.conn, 1_000)

        after_in = cash_in(self.conn, 500, "refund")
        self.assertEqual(after_in["wallet_total"], 1_500)
        self.assertEqual(after_in["total_assets"], 1_500)

        after_out = cash_out(self.conn, 200, "lunch")
        self.assertEqual(after_out["wallet_total"], 1_300)
        self.assertEqual(after_out["total_assets"], 1_300)

    def test_cash_out_rejects_negative_wallet_balance(self) -> None:
        set_wallet_total(self.conn, 300)

        with self.assertRaises(ValueError):
            cash_out(self.conn, 301, "too much")

    def test_bank_to_wallet_transfer_keeps_total_assets_unchanged(self) -> None:
        handle_command(self.conn, "/set-bank 10000")
        handle_command(self.conn, "/cash-set 1000")
        before = get_latest_snapshot(self.conn)["total_assets"]

        result = transfer(self.conn, "bank", "wallet", 3_000, "ATM")
        snapshot = result["snapshot"]

        self.assertEqual(snapshot["bank_total"], 7_000)
        self.assertEqual(snapshot["wallet_total"], 4_000)
        self.assertEqual(snapshot["total_assets"], before)

    def test_atm_command_keeps_total_assets_unchanged(self) -> None:
        handle_command(self.conn, "/set-bank 10000")
        handle_command(self.conn, "/cash-set 1000")
        before = get_latest_snapshot(self.conn)["total_assets"]

        output = handle_command(self.conn, "/atm 3000 ATM")
        after = get_latest_snapshot(self.conn)

        self.assertIn("総資産は変わりません", output)
        self.assertEqual(after["bank_total"], 7_000)
        self.assertEqual(after["wallet_total"], 4_000)
        self.assertEqual(after["total_assets"], before)

    def test_wallet_to_bank_transfer_rejects_insufficient_wallet_balance(self) -> None:
        handle_command(self.conn, "/set-bank 10000")
        handle_command(self.conn, "/cash-set 1000")

        with self.assertRaises(ValueError):
            transfer(self.conn, "wallet", "bank", 1_001, "deposit")


class CardSummaryTests(DatabaseTestCase):
    def test_card_summary_and_unbilled_refresh_use_payment_month(self) -> None:
        self.conn.executemany(
            """
            INSERT INTO card_transactions (used_on, merchant, amount, payment_month)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("2026-04-01", "Amazon", 1_200, "2026-05"),
                ("2026-04-02", "Cafe", 800, "2026-05"),
                ("2026-04-03", "Amazon", 2_000, "2026-06"),
            ],
        )

        summary = get_card_month_summary(self.conn, "2026-05")
        self.assertEqual(summary["total"], 2_000)
        self.assertEqual(summary["by_merchant"][0], {"merchant": "Amazon", "total": 1_200})

        snapshot = refresh_card_unbilled(self.conn, "2026-05")
        self.assertEqual(snapshot["credit_card_unbilled"], 2_000)
        self.assertEqual(snapshot["total_assets"], -2_000)

    def test_card_billing_month_rolls_over_year(self) -> None:
        self.assertEqual(card_billing_month(date(2026, 12, 15)), "2027-01")


class AskContextTests(DatabaseTestCase):
    def test_ask_context_keeps_card_wallet_and_transfer_sections_separate(self) -> None:
        handle_command(self.conn, "/set-bank 10000")
        handle_command(self.conn, "/cash-set 1000")
        handle_command(self.conn, "/cash-out 200 lunch")
        handle_command(self.conn, "/atm 3000 ATM")
        self.conn.execute(
            """
            INSERT INTO card_transactions (used_on, merchant, amount, payment_month)
            VALUES (?, ?, ?, ?)
            """,
            ("2026-04-01", "Amazon", 1_200, card_billing_month()),
        )

        context = build_finance_context(self.conn, "今月どう？")

        self.assertIn("## 今月のカード利用", context)
        self.assertIn("Amazon", context)
        self.assertIn("'total': 1200", context)
        self.assertIn("## 今月の現金支出", context)
        self.assertIn("財布支出合計: 200円", context)
        self.assertIn("lunch", context)
        self.assertIn("## 最近の振替", context)
        self.assertIn("'from_account': 'bank'", context)
        self.assertIn("'to_account': 'wallet'", context)


class CreditCardCsvImportTests(DatabaseTestCase):
    def test_parse_format_a_uses_filename_payment_month(self) -> None:
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "202604.csv"
            csv_path.write_text(
                "利用日,利用店名,利用金額,支払回数計,今回回数,今回支払額,備考\n"
                "2026/4/1,ＡＭＡＺＯＮ,1200,1,1,1200,\n",
                encoding="cp932",
            )

            records = parse_csv(csv_path)

        self.assertEqual(records, [
            {
                "used_on": "2026-04-01",
                "merchant": "AMAZON",
                "amount": 1_200,
                "payment_month": "2026-04",
            }
        ])

    def test_parse_format_b_uses_payment_month_column_and_amount_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "card.csv"
            csv_path.write_text(
                "2026/4/2,コンビニ,本人,一括,,'26/05,500,,\n"
                "2026/4/3,スーパー,本人,一括,,'26/05,2000,1800,\n",
                encoding="utf-8",
            )

            records = parse_csv(csv_path)

        self.assertEqual(records, [
            {
                "used_on": "2026-04-02",
                "merchant": "コンビニ",
                "amount": 500,
                "payment_month": "2026-05",
            },
            {
                "used_on": "2026-04-03",
                "merchant": "スーパー",
                "amount": 1_800,
                "payment_month": "2026-05",
            },
        ])

    def test_import_csv_skips_duplicate_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "202604.csv"
            second = base / "202604_extra.csv"
            first.write_text(
                "利用日,利用店名,利用金額,支払回数計,今回回数,今回支払額,備考\n"
                "2026/4/1,ＡＭＡＺＯＮ,1200,1,1,1200,\n",
                encoding="cp932",
            )
            second.write_text(
                "利用日,利用店名,利用金額,支払回数計,今回回数,今回支払額,備考\n"
                "2026/4/1,ＡＭＡＺＯＮ,1200,1,1,1200,\n"
                "2026/4/2,コンビニ,500,1,1,500,\n",
                encoding="cp932",
            )

            self.assertEqual(import_csv(self.conn, first)["imported"], 1)
            self.assertEqual(import_csv(self.conn, first)["skipped"], 1)
            result = import_csv(self.conn, second)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 1)
        count = self.conn.execute("SELECT COUNT(*) FROM card_transactions").fetchone()[0]
        self.assertEqual(count, 2)

    def test_import_directory_handles_empty_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            result = import_directory(self.conn, Path(tmp))

        self.assertEqual(result, {"imported": 0, "skipped": 0, "errors": [], "files": 0})

    def test_import_directory_reports_same_file_reimport_as_row_skips(self) -> None:
        with TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            csv_path = inbox / "202604.csv"
            csv_path.write_text(
                "利用日,利用店名,利用金額,支払回数計,今回回数,今回支払額,備考\n"
                "2026/4/1,ＡＭＡＺＯＮ,1200,1,1,1200,\n"
                "2026/4/2,コンビニ,500,1,1,500,\n",
                encoding="cp932",
            )

            first = import_directory(self.conn, inbox)
            second = import_directory(self.conn, inbox)

        self.assertEqual(first["files"], 1)
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["skipped"], 0)
        self.assertEqual(second["files"], 1)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["skipped"], 2)
        self.assertEqual(second["errors"], [])


class McpServerTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.server = FinanceMcpServer(self.db_path)

    def _tool(self, name: str, arguments: dict | None = None) -> dict:
        response = self.server.handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        assert response is not None
        self.assertNotIn("error", response)
        result = response["result"]
        return json.loads(result["content"][0]["text"])

    def test_mcp_lists_finance_tools_and_usage_resource(self) -> None:
        tools_response = self.server.handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })
        assert tools_response is not None
        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}

        self.assertIn("finance.now", tool_names)
        self.assertIn("finance.transfer", tool_names)
        self.assertIn("finance.build_context", tool_names)

        resource_response = self.server.handle({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "finance://usage-image"},
        })
        assert resource_response is not None
        usage = resource_response["result"]["contents"][0]["text"]

        self.assertIn("LLM -> finance.now()", usage)
        self.assertIn("bank -> wallet は支出ではなく振替", usage)

    def test_mcp_updates_and_reads_current_position(self) -> None:
        self.assertTrue(self._tool("finance.set_bank", {"amount": 10_000})["ok"])
        self.assertTrue(self._tool("finance.cash_set", {"amount": 1_000})["ok"])
        before = self._tool("finance.now")["data"]["total_assets"]

        transfer_result = self._tool(
            "finance.transfer",
            {
                "from_account": "bank",
                "to_account": "wallet",
                "amount": 3_000,
                "memo": "ATM",
            },
        )
        snapshot = transfer_result["data"]["snapshot"]

        self.assertEqual(snapshot["bank_total"], 7_000)
        self.assertEqual(snapshot["wallet_total"], 4_000)
        self.assertEqual(snapshot["total_assets"], before)

    def test_mcp_returns_tool_error_for_insufficient_wallet_balance(self) -> None:
        self.assertTrue(self._tool("finance.cash_set", {"amount": 500})["ok"])

        response = self.server.handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "finance.cash_out",
                "arguments": {"amount": 501, "memo": "too much"},
            },
        })
        assert response is not None
        result = response["result"]
        payload = json.loads(result["content"][0]["text"])

        self.assertTrue(result["isError"])
        self.assertFalse(payload["ok"])
        self.assertIn("財布残高が不足しています", payload["error"])


if __name__ == "__main__":
    unittest.main()
