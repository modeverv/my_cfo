use crate::db::{connect, init_db};
use crate::importers::credit_card_csv::{import_csv, import_directory};
use crate::services::ask_context::{
    build_finance_context, card_billing_month, current_month, get_card_month_summary,
    get_recent_transfers, get_wallet_month_summary, refresh_card_unbilled,
};
use crate::services::manual_snapshots::{cash_add, cash_out, set_bank_total, set_securities_total};
use crate::services::snapshots::get_latest_snapshot;
use crate::services::transfers::transfer;
use serde_json::{json, Value};
use std::io::{BufRead, Write};
use std::path::Path;

const SERVER_NAME: &str = "personal-finance-console";
const SERVER_VERSION: &str = "0.1.0";
const USAGE_GUIDE_URI: &str = "finance://usage-guide";
const LEGACY_USAGE_GUIDE_URI: &str = "finance://usage-image";

const USAGE_GUIDE_MARKDOWN: &str = r#"# Personal Finance Console MCP 使用イメージ

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
"#;

const SERVER_INSTRUCTIONS: &str = "Personal Finance Console MCP.\n\
Use these tools through finance_core only. Never run arbitrary SQL.\n\
Do not confuse transfers with spending: bank -> wallet changes location only.\n\
Use the resource finance://usage-guide for concrete usage examples.\n\
Use `finance.import_card` with no arguments to scan the configured default card CSV inbox.";

fn ok(data: Value) -> Value {
    json!({"ok": true, "data": data})
}

fn validate_amount(args: &Value, key: &str, allow_zero: bool) -> Result<i64, String> {
    let raw = &args[key];
    if !raw.is_i64() && !raw.is_u64() {
        return Err(format!("{} は整数で指定してください", key));
    }
    let v = raw.as_i64().unwrap_or(0);
    if allow_zero && v < 0 {
        return Err(format!("{} は0以上で指定してください", key));
    }
    if !allow_zero && v <= 0 {
        return Err(format!("{} は1以上で指定してください", key));
    }
    Ok(v)
}

fn validate_memo(args: &Value, required: bool) -> Result<String, String> {
    let raw = &args["memo"];
    if raw.is_null() {
        if required {
            return Err("memo は必須です".to_string());
        }
        return Ok(String::new());
    }
    raw.as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| "memo は文字列で指定してください".to_string())
}

fn resolve_month(args: &Value, default_fn: fn() -> String) -> Result<String, String> {
    let raw = args["month"].as_str().unwrap_or("this_month");
    if raw == "this_month" {
        return Ok(default_fn());
    }
    if raw.len() == 7 && raw.chars().nth(4) == Some('-') {
        Ok(raw.to_string())
    } else {
        Err(r#"month は "this_month" または "YYYY-MM" で指定してください"#.to_string())
    }
}

fn tool_definitions() -> Value {
    fn schema(props: Value, required: Vec<&str>) -> Value {
        json!({
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": false
        })
    }

    json!([
        {
            "name": "finance.now",
            "description": "現在の資産状況を返す。総資産は 銀行 + 証券 + 財布 - カード利用。",
            "inputSchema": schema(json!({}), vec![])
        },
        {
            "name": "finance.card_summary",
            "description": "カード利用の月次集計を返す。this_month は今月利用分の支払月を指す。",
            "inputSchema": schema(json!({"month": {"type": "string", "default": "this_month"}}), vec![])
        },
        {
            "name": "finance.wallet_summary",
            "description": "財布の月次支出集計を返す。振替や補正は支出に含めない。",
            "inputSchema": schema(json!({"month": {"type": "string", "default": "this_month"}}), vec![])
        },
        {
            "name": "finance.recent_transfers",
            "description": "最近の振替一覧を返す。振替は支出ではない。",
            "inputSchema": schema(json!({"limit": {"type": "integer", "default": 10, "minimum": 1}}), vec![])
        },
        {
            "name": "finance.set_bank",
            "description": "銀行残高を手入力で更新する。",
            "inputSchema": schema(json!({"amount": {"type": "integer", "minimum": 0}}), vec!["amount"])
        },
        {
            "name": "finance.set_securities",
            "description": "証券評価額を手入力で更新する。",
            "inputSchema": schema(json!({"amount": {"type": "integer", "minimum": 0}}), vec!["amount"])
        },
        {
            "name": "finance.cash_set",
            "description": "財布残高を実測値で補正する。これは支出ではない。",
            "inputSchema": schema(json!({"amount": {"type": "integer", "minimum": 0}}), vec!["amount"])
        },
        {
            "name": "finance.cash_in",
            "description": "財布に現金を入れる。",
            "inputSchema": schema(json!({"amount": {"type": "integer", "minimum": 1}, "memo": {"type": "string"}}), vec!["amount", "memo"])
        },
        {
            "name": "finance.cash_out",
            "description": "財布から現金を使う。財布残高不足はエラー。",
            "inputSchema": schema(json!({"amount": {"type": "integer", "minimum": 1}, "memo": {"type": "string"}}), vec!["amount", "memo"])
        },
        {
            "name": "finance.transfer",
            "description": "振替を記録する。bank -> wallet は支出ではなく、財布履歴とは分けてtransfersに記録する。",
            "inputSchema": schema(json!({
                "from_account": {"type": "string", "enum": ["bank", "wallet", "securities", "card"]},
                "to_account": {"type": "string", "enum": ["bank", "wallet", "securities", "card"]},
                "amount": {"type": "integer", "minimum": 1},
                "memo": {"type": "string"}
            }), vec!["from_account", "to_account", "amount"])
        },
        {
            "name": "finance.import_card",
            "description": "クレカCSVを取り込む。path省略時はデフォルト受信フォルダを走査する。",
            "inputSchema": schema(json!({"path": {"type": "string"}}), vec![])
        },
        {
            "name": "finance.build_context",
            "description": "/ask用の集計済みコンテキストを返す。生データを全部返さず、支出と振替を分ける。",
            "inputSchema": schema(json!({"question": {"type": "string"}}), vec!["question"])
        }
    ])
}

pub struct McpServer {
    db_path: std::path::PathBuf,
}

impl McpServer {
    pub fn new(db_path: &Path) -> Self {
        McpServer {
            db_path: db_path.to_path_buf(),
        }
    }

    pub fn handle(&self, request: &Value) -> Option<Value> {
        let method = request["method"].as_str().unwrap_or("");
        let request_id = &request["id"];

        if method == "notifications/initialized" {
            return None;
        }

        let params = request["params"]
            .as_object()
            .map(|o| Value::Object(o.clone()))
            .unwrap_or(json!({}));

        match self.dispatch(method, &params) {
            Ok(result) => Some(json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            })),
            Err(e) => Some(json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": e}
            })),
        }
    }

    fn dispatch(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "initialize" => Ok(json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS
            })),
            "tools/list" => Ok(json!({"tools": tool_definitions()})),
            "tools/call" => self.call_tool(params),
            "resources/list" => Ok(json!({
                "resources": [
                    {
                        "uri": USAGE_GUIDE_URI,
                        "name": "Personal Finance Console MCP 使用イメージ",
                        "description": "LLMから見たツール呼び出し例と重要ルール。",
                        "mimeType": "text/markdown"
                    },
                    {
                        "uri": LEGACY_USAGE_GUIDE_URI,
                        "name": "Personal Finance Console MCP 使用イメージ (legacy)",
                        "description": "finance://usage-guide の互換URI。",
                        "mimeType": "text/markdown"
                    }
                ]
            })),
            "resources/read" => {
                let uri = params["uri"].as_str().unwrap_or("");
                if uri != USAGE_GUIDE_URI && uri != LEGACY_USAGE_GUIDE_URI {
                    return Err(format!("未知のresourceです: {}", uri));
                }
                Ok(json!({
                    "contents": [{
                        "uri": uri,
                        "mimeType": "text/markdown",
                        "text": USAGE_GUIDE_MARKDOWN
                    }]
                }))
            }
            other => Err(format!("未対応MCPメソッドです: {}", other)),
        }
    }

    fn call_tool(&self, params: &Value) -> Result<Value, String> {
        let name = params["name"].as_str().unwrap_or("");
        let args = &params["arguments"];
        let args = if args.is_null() { &json!({}) } else { args };

        let _ = init_db(&self.db_path).map_err(|e| e.to_string())?;
        let conn = connect(&self.db_path).map_err(|e| e.to_string())?;

        let (payload, is_error) = match self.invoke_tool(name, args, &conn) {
            Ok(data) => (data, false),
            Err(e) => (json!({"ok": false, "error": e}), true),
        };

        if !is_error {
            let _ = conn.execute_batch("COMMIT");
        }

        Ok(json!({
            "content": [{
                "type": "text",
                "text": serde_json::to_string_pretty(&payload).unwrap_or_default()
            }],
            "isError": is_error
        }))
    }

    fn invoke_tool(
        &self,
        name: &str,
        args: &Value,
        conn: &rusqlite::Connection,
    ) -> Result<Value, String> {
        match name {
            "finance.now" => {
                let snap = get_latest_snapshot(conn).map_err(|e| e.to_string())?;
                Ok(ok(serde_json::to_value(&snap).unwrap_or_default()))
            }
            "finance.card_summary" => {
                let month = resolve_month(args, card_billing_month)?;
                let summary = get_card_month_summary(conn, &month).map_err(|e| e.to_string())?;
                Ok(ok(serde_json::to_value(&summary).unwrap_or_default()))
            }
            "finance.wallet_summary" => {
                let month = resolve_month(args, current_month)?;
                let summary = get_wallet_month_summary(conn, &month).map_err(|e| e.to_string())?;
                Ok(ok(serde_json::to_value(&summary).unwrap_or_default()))
            }
            "finance.recent_transfers" => {
                let limit = args["limit"].as_i64().unwrap_or(10);
                if limit < 1 {
                    return Err("limit は1以上の整数で指定してください".to_string());
                }
                let transfers = get_recent_transfers(conn, limit).map_err(|e| e.to_string())?;
                Ok(ok(serde_json::to_value(&transfers).unwrap_or_default()))
            }
            "finance.set_bank" => {
                let amount = validate_amount(args, "amount", true)?;
                let snap = set_bank_total(conn, amount).map_err(|e| e.to_string())?;
                Ok(ok(json!({"snapshot": snap})))
            }
            "finance.set_securities" => {
                let amount = validate_amount(args, "amount", true)?;
                let snap = set_securities_total(conn, amount).map_err(|e| e.to_string())?;
                Ok(ok(json!({"snapshot": snap})))
            }
            "finance.cash_set" => {
                let amount = validate_amount(args, "amount", true)?;
                let snap = crate::services::manual_snapshots::set_wallet_total(conn, amount)
                    .map_err(|e| e.to_string())?;
                Ok(ok(json!({"snapshot": snap})))
            }
            "finance.cash_in" => {
                let amount = validate_amount(args, "amount", false)?;
                let memo = validate_memo(args, true)?;
                let snap = cash_add(conn, amount, &memo).map_err(|e| e.to_string())?;
                Ok(ok(json!({"snapshot": snap})))
            }
            "finance.cash_out" => {
                let amount = validate_amount(args, "amount", false)?;
                let memo = validate_memo(args, true)?;
                let snap = cash_out(conn, amount, &memo).map_err(|e| e.to_string())?;
                Ok(ok(json!({"snapshot": snap})))
            }
            "finance.transfer" => {
                let from = args["from_account"]
                    .as_str()
                    .ok_or("from_account は文字列で指定してください")?;
                let to = args["to_account"]
                    .as_str()
                    .ok_or("to_account は文字列で指定してください")?;
                let amount = validate_amount(args, "amount", false)?;
                let memo = validate_memo(args, false)?;
                let memo_opt = if memo.is_empty() {
                    None
                } else {
                    Some(memo.as_str())
                };
                let result =
                    transfer(conn, from, to, amount, memo_opt).map_err(|e| e.to_string())?;
                Ok(ok(json!({
                    "transfer_id": result.transfer_id,
                    "snapshot": result.snapshot
                })))
            }
            "finance.import_card" => {
                let raw_path = args["path"].as_str();
                let result = if let Some(p) = raw_path {
                    if p.is_empty() {
                        return Err("path は文字列で指定してください".to_string());
                    }
                    let path = std::path::Path::new(p);
                    if path.is_file() {
                        let r = import_csv(conn, path).map_err(|e| e.to_string())?;
                        json!({
                            "imported": r.imported,
                            "skipped": r.skipped,
                            "skipped_rows": r.skipped_rows,
                            "files": 1,
                            "errors": []
                        })
                    } else {
                        let r = import_directory(conn, Some(path)).map_err(|e| e.to_string())?;
                        serde_json::to_value(&r).unwrap_or_default()
                    }
                } else {
                    let r = import_directory(conn, None).map_err(|e| e.to_string())?;
                    serde_json::to_value(&r).unwrap_or_default()
                };
                refresh_card_unbilled(conn, &card_billing_month()).map_err(|e| e.to_string())?;
                Ok(ok(result))
            }
            "finance.build_context" => {
                let question = args["question"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .ok_or("question は文字列で指定してください")?;
                let context = build_finance_context(conn, question).map_err(|e| e.to_string())?;
                Ok(ok(json!({"context": context})))
            }
            other => Err(format!("未知のtoolです: {}", other)),
        }
    }
}

pub fn serve(db_path: &Path) {
    let server = McpServer::new(db_path);
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::new(stdout.lock());

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        let request: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                let _ = writeln!(
                    out,
                    "{}",
                    json!({
                        "jsonrpc": "2.0",
                        "id": null,
                        "error": {"code": -32700, "message": format!("Parse error: {}", e)}
                    })
                );
                let _ = out.flush();
                continue;
            }
        };
        if let Some(response) = server.handle(&request) {
            let _ = writeln!(
                out,
                "{}",
                serde_json::to_string(&response).unwrap_or_default()
            );
            let _ = out.flush();
        }
    }
}
