from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from finance_core.db import DEFAULT_DB_PATH, connect, init_db
from finance_core.importers.credit_card_csv import import_csv, import_directory
from finance_core.services.ask_context import (
    build_finance_context,
    card_billing_month,
    current_month,
    get_card_month_summary,
    get_recent_transfers,
    get_wallet_month_summary,
    refresh_card_unbilled,
)
from finance_core.services.manual_snapshots import (
    cash_add as core_cash_add,
    cash_out as core_cash_out,
    set_bank_total,
    set_securities_total,
    set_wallet_total,
)
from finance_core.services.now import get_current_position
from finance_core.services.transfers import transfer as core_transfer


SERVER_NAME = "personal-finance-console"
SERVER_VERSION = "0.1.0"
USAGE_GUIDE_URI = "finance://usage-guide"
LEGACY_USAGE_GUIDE_URI = "finance://usage-image"

USAGE_GUIDE_MARKDOWN = """# Personal Finance Console MCP 使用イメージ

このMCPは、LLMにSQLiteや生データを直接触らせず、既存のfinance_coreを安全な道具として公開します。

## 読み取り

```text
LLM -> finance.now()
LLM -> finance.card_summary(month="this_month")
LLM -> finance.wallet_summary(month="this_month")
LLM -> finance.recent_transfers(limit=10)
```

## 更新

```text
LLM -> finance.set_bank(amount=3200000)
LLM -> finance.set_securities(amount=58800000)
LLM -> finance.cash_set(amount=42000)
LLM -> finance.cash_in(amount=5000, memo="refund")
LLM -> finance.cash_out(amount=1200, memo="lunch")
LLM -> finance.transfer(from_account="bank", to_account="wallet", amount=30000, memo="ATM")
```

## 相談

```text
LLM -> finance.build_context(question="今月ってカード使いすぎ？")
LLM -> 返された集計済みコンテキストだけを根拠に回答
```

## 重要ルール

- 総資産 = 銀行 + 証券 + 財布 - カード利用
- bank -> wallet は支出ではなく振替
- cash_set は実測補正であり現金支出ではない
- /ask相当の相談では集計済みデータだけを使う
"""

SERVER_INSTRUCTIONS = """Personal Finance Console MCP.
Use these tools through finance_core only. Never run arbitrary SQL.
Do not confuse transfers with spending: bank -> wallet changes location only.
Use the resource finance://usage-guide for concrete usage examples.
Use `finance.import_card` with no arguments to scan the configured default card CSV inbox.
"""

MIME_MARKDOWN = "text/markdown"

JsonDict = dict[str, Any]
ToolFunc = Callable[[sqlite3.Connection, JsonDict], JsonDict]


def _ok(data: JsonDict | list[JsonDict]) -> JsonDict:
    return {"ok": True, "data": data}


def _validate_amount(args: JsonDict, key: str = "amount", *, allow_zero: bool = True) -> int:
    raw = args.get(key)
    if not isinstance(raw, int):
        raise ValueError(f"{key} は整数で指定してください")
    if allow_zero and raw < 0:
        raise ValueError(f"{key} は0以上で指定してください")
    if not allow_zero and raw <= 0:
        raise ValueError(f"{key} は1以上で指定してください")
    return raw


def _validate_memo(args: JsonDict, required: bool = False) -> str:
    raw = args.get("memo")
    if raw is None:
        if required:
            raise ValueError("memo は必須です")
        return ""
    if not isinstance(raw, str):
        raise ValueError("memo は文字列で指定してください")
    return raw


def _resolve_month(args: JsonDict, default_fn: Callable[[], str]) -> str:
    raw = args.get("month", "this_month")
    if raw == "this_month":
        return default_fn()
    if not isinstance(raw, str) or not re.match(r"^\d{4}-\d{2}$", raw):
        raise ValueError('month は "this_month" または "YYYY-MM" で指定してください')
    return raw


def finance_now(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok(get_current_position(conn))


def finance_card_summary(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok(get_card_month_summary(conn, _resolve_month(args, card_billing_month)))


def finance_wallet_summary(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok(get_wallet_month_summary(conn, _resolve_month(args, current_month)))


def finance_recent_transfers(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    limit = args.get("limit", 10)
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit は1以上の整数で指定してください")
    return _ok(get_recent_transfers(conn, limit))


def finance_set_bank(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok({"snapshot": set_bank_total(conn, _validate_amount(args))})


def finance_set_securities(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok({"snapshot": set_securities_total(conn, _validate_amount(args))})


def finance_cash_set(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok({"snapshot": set_wallet_total(conn, _validate_amount(args))})


def finance_cash_in(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok({"snapshot": core_cash_add(conn, _validate_amount(args, allow_zero=False), _validate_memo(args, required=True))})


def finance_cash_out(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    return _ok({"snapshot": core_cash_out(conn, _validate_amount(args, allow_zero=False), _validate_memo(args, required=True))})


def finance_transfer(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    from_account = args.get("from_account")
    to_account = args.get("to_account")
    if not isinstance(from_account, str) or not isinstance(to_account, str):
        raise ValueError("from_account と to_account は文字列で指定してください")
    result = core_transfer(
        conn,
        from_account,
        to_account,
        _validate_amount(args, allow_zero=False),
        _validate_memo(args),
    )
    return _ok(result)


def finance_import_card(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    # path is optional. If omitted, scan the default inbox (same as /import)
    raw_path = args.get("path")
    if raw_path is None:
        output = import_directory(conn, None)
    else:
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("path は文字列で指定してください")
        path = Path(raw_path)
        if path.is_file():
            result = import_csv(conn, path)
            output = {
                "imported": result["imported"],
                "skipped": result["skipped"],
                "skipped_rows": result.get("skipped_rows", 0),
                "files": 1,
                "errors": [],
            }
        else:
            output = import_directory(conn, path)
    refresh_card_unbilled(conn, card_billing_month())
    return _ok(output)


def finance_build_context(conn: sqlite3.Connection, args: JsonDict) -> JsonDict:
    question = args.get("question")
    if not isinstance(question, str) or not question:
        raise ValueError("question は文字列で指定してください")
    return _ok({"context": build_finance_context(conn, question)})


TOOLS: dict[str, ToolFunc] = {
    "finance.now": finance_now,
    "finance.card_summary": finance_card_summary,
    "finance.wallet_summary": finance_wallet_summary,
    "finance.recent_transfers": finance_recent_transfers,
    "finance.set_bank": finance_set_bank,
    "finance.set_securities": finance_set_securities,
    "finance.cash_set": finance_cash_set,
    "finance.cash_in": finance_cash_in,
    "finance.cash_out": finance_cash_out,
    "finance.transfer": finance_transfer,
    "finance.import_card": finance_import_card,
    "finance.build_context": finance_build_context,
}


def _schema(properties: JsonDict | None = None, required: list[str] | None = None) -> JsonDict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: list[JsonDict] = [
    {
        "name": "finance.now",
        "description": "現在の資産状況を返す。総資産は 銀行 + 証券 + 財布 - カード利用。",
        "inputSchema": _schema(),
    },
    {
        "name": "finance.card_summary",
        "description": "カード利用の月次集計を返す。this_month は今月利用分の支払月を指す。",
        "inputSchema": _schema({"month": {"type": "string", "default": "this_month"}}),
    },
    {
        "name": "finance.wallet_summary",
        "description": "財布の月次支出集計を返す。振替や補正は支出に含めない。",
        "inputSchema": _schema({"month": {"type": "string", "default": "this_month"}}),
    },
    {
        "name": "finance.recent_transfers",
        "description": "最近の振替一覧を返す。振替は支出ではない。",
        "inputSchema": _schema({"limit": {"type": "integer", "default": 10, "minimum": 1}}),
    },
    {
        "name": "finance.set_bank",
        "description": "銀行残高を手入力で更新する。",
        "inputSchema": _schema({"amount": {"type": "integer", "minimum": 0}}, ["amount"]),
    },
    {
        "name": "finance.set_securities",
        "description": "証券評価額を手入力で更新する。",
        "inputSchema": _schema({"amount": {"type": "integer", "minimum": 0}}, ["amount"]),
    },
    {
        "name": "finance.cash_set",
        "description": "財布残高を実測値で補正する。これは支出ではない。",
        "inputSchema": _schema({"amount": {"type": "integer", "minimum": 0}}, ["amount"]),
    },
    {
        "name": "finance.cash_in",
        "description": "財布に現金を入れる。",
        "inputSchema": _schema(
            {"amount": {"type": "integer", "minimum": 1}, "memo": {"type": "string"}},
            ["amount", "memo"],
        ),
    },
    {
        "name": "finance.cash_out",
        "description": "財布から現金を使う。財布残高不足はエラー。",
        "inputSchema": _schema(
            {"amount": {"type": "integer", "minimum": 1}, "memo": {"type": "string"}},
            ["amount", "memo"],
        ),
    },
    {
        "name": "finance.transfer",
        "description": "振替を記録する。bank -> wallet は支出ではなく、財布履歴とは分けてtransfersに記録する。",
        "inputSchema": _schema(
            {
                "from_account": {"type": "string", "enum": ["bank", "wallet", "securities", "card"]},
                "to_account": {"type": "string", "enum": ["bank", "wallet", "securities", "card"]},
                "amount": {"type": "integer", "minimum": 1},
                "memo": {"type": "string"},
            },
            ["from_account", "to_account", "amount"],
        ),
    },
    {
        "name": "finance.import_card",
        "description": "クレカCSVを取り込む。path省略時はデフォルト受信フォルダを走査する。",
        "inputSchema": _schema({"path": {"type": "string"}}),
    },
    {
        "name": "finance.build_context",
        "description": "/ask用の集計済みコンテキストを返す。生データを全部返さず、支出と振替を分ける。",
        "inputSchema": _schema({"question": {"type": "string"}}, ["question"]),
    },
]

class FinanceMcpServer:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def handle(self, request: JsonDict) -> JsonDict | None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            return None
        try:
            result = self._dispatch(method, request.get("params") or {})
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def _dispatch(self, method: str, params: JsonDict) -> JsonDict:
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            }
        if method == "tools/list":
            return {"tools": TOOL_DEFINITIONS}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "resources/list":
            return {
                "resources": [
                    {
                        "uri": USAGE_GUIDE_URI,
                        "name": "Personal Finance Console MCP 使用イメージ",
                        "description": "LLMから見たツール呼び出し例と重要ルール。",
                        "mimeType": MIME_MARKDOWN,
                    },
                    {
                        "uri": LEGACY_USAGE_GUIDE_URI,
                        "name": "Personal Finance Console MCP 使用イメージ (legacy)",
                        "description": "finance://usage-guide の互換URI。",
                        "mimeType": MIME_MARKDOWN,
                    }
                ]
            }
        if method == "resources/read":
            uri = params.get("uri")
            if uri not in {USAGE_GUIDE_URI, LEGACY_USAGE_GUIDE_URI}:
                raise ValueError(f"未知のresourceです: {uri}")
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType":MIME_MARKDOWN,
                        "text": USAGE_GUIDE_MARKDOWN,
                    }
                ]
            }
        raise ValueError(f"未対応MCPメソッドです: {method}")

    def _call_tool(self, params: JsonDict) -> JsonDict:
        name = params.get("name")
        if not isinstance(name, str) or name not in TOOLS:
            raise ValueError(f"未知のtoolです: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise ValueError("arguments はobjectで指定してください")

        init_db(self.db_path)
        with connect(self.db_path) as conn:
            try:
                payload = TOOLS[name](conn, args)
                conn.commit()
                is_error = False
            except Exception as exc:
                conn.rollback()
                payload = {"ok": False, "error": str(exc)}
                is_error = True
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ],
            "isError": is_error,
        }


def serve(db_path: Path) -> None:
    server = FinanceMcpServer(db_path)
    for line in sys.stdin:
        if not line.strip():
            continue
        response = server.handle(json.loads(line))
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Finance Console MCP server")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    args = parser.parse_args()
    serve(args.db)


if __name__ == "__main__":
    main()
