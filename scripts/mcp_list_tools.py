#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys

def main():
    python = sys.executable
    cmd = [python, "-m", "finance_mcp.server", "--db", "finance.sqlite3"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # send tools/list
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            print("No response from MCP server", file=sys.stderr)
            return
        resp = json.loads(line)
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    finally:
        try:
            proc.kill()
        except Exception:
            pass

if __name__ == '__main__':
    main()

