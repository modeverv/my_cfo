#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def build_request(method: str, params: dict[str, Any] | None, id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def call_tool(server_cmd: list[str], tool_name: str, arguments: dict | None, db: str | None = None) -> None:
    # Start MCP server as subprocess
    proc = subprocess.Popen(
        server_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # initialize (optional)
        init_req = build_request("initialize", {})
        proc.stdin.write(json.dumps(init_req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        # read and ignore initialize response if any
        # send tools/list to get tool definitions
        list_req = build_request("tools/list", {})
        proc.stdin.write(json.dumps(list_req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("No response from MCP server")
        resp = json.loads(line)
        # call the desired tool
        call_req = build_request("tools/call", {"name": tool_name, "arguments": arguments or {}})
        proc.stdin.write(json.dumps(call_req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        result_line = proc.stdout.readline()
        if not result_line:
            raise RuntimeError("No response from MCP server for tools/call")
        result = json.loads(result_line)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple MCP client for Personal Finance Console")
    parser.add_argument("--db", type=str, default="finance.sqlite3", help="Path to SQLite DB used by server")
    parser.add_argument("--tool", type=str, required=True, help="Tool name to call (e.g. finance.import_card)")
    parser.add_argument("--args", type=str, default="{}", help="JSON string of arguments for the tool")
    parser.add_argument("--python", type=str, default=sys.executable, help="Python executable to run the MCP server")
    args = parser.parse_args()

    try:
        arguments = json.loads(args.args)
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--args is not valid JSON: {exc}")

    server_cmd = [args.python, "-m", "finance_mcp.server", "--db", args.db]
    call_tool(server_cmd, args.tool, arguments, db=args.db)


if __name__ == "__main__":
    main()

