use crate::config::load;
use anyhow::{anyhow, bail, Context, Result};
use serde_json::{json, Value};

const DEFAULT_BASE_URL: &str = "http://localhost:1234/v1";

fn answer_schema() -> Value {
    json!({
        "type": "json_schema",
        "json_schema": {
            "name": "finance_answer",
            "strict": true,
            "schema": {
                "type": "object",
                "properties": {
                    "conclusion": {"type": "string", "description": "結論を1〜2文で簡潔に"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "description": "数値根拠のリスト"},
                    "points": {"type": "array", "items": {"type": "string"}, "description": "増加要因・注意点の箇条書き"},
                    "unknown": {"type": "string", "description": "不明な点。なければ空文字"}
                },
                "required": ["conclusion", "evidence", "points", "unknown"],
                "additionalProperties": false
            }
        }
    })
}

fn format_answer(data: &Value) -> String {
    let conclusion = data["conclusion"].as_str().unwrap_or("");
    let evidence: Vec<&str> = data["evidence"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
        .unwrap_or_default();
    let points: Vec<&str> = data["points"]
        .as_array()
        .map(|a| a.iter().filter_map(|v| v.as_str()).collect())
        .unwrap_or_default();
    let unknown = data["unknown"].as_str().unwrap_or("").trim();

    let mut lines = vec![
        "【結論】".to_string(),
        conclusion.to_string(),
        String::new(),
        "【数値根拠】".to_string(),
    ];
    for e in &evidence {
        lines.push(format!("・{}", e));
    }
    lines.push(String::new());
    lines.push("【要因・注意点】".to_string());
    for p in &points {
        lines.push(format!("・{}", p));
    }
    if !unknown.is_empty() {
        lines.push(String::new());
        lines.push("【不明な点】".to_string());
        lines.push(unknown.to_string());
    }
    lines.join("\n")
}

fn resolve_model(
    client: &reqwest::blocking::Client,
    base_url: &str,
    preferred: Option<&str>,
) -> String {
    if let Some(m) = preferred {
        if !m.is_empty() {
            return m.to_string();
        }
    }
    if let Ok(url) = format!("{}/models", base_url).parse::<reqwest::Url>() {
        if let Ok(resp) = client.get(url).send() {
            if let Ok(body) = resp.json::<Value>() {
                if let Some(models) = body["data"].as_array() {
                    for m in models {
                        if let Some(id) = m["id"].as_str() {
                            if !id.to_lowercase().contains("embed") {
                                return id.to_string();
                            }
                        }
                    }
                }
            }
        }
    }
    "local-model".to_string()
}

pub fn chat_completion(prompt: &str) -> Result<String> {
    let cfg = load();
    let llm = cfg.llm();
    let base_url = llm
        .base_url
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| DEFAULT_BASE_URL.to_string());
    let base_url = base_url.trim_end_matches('/').to_string();

    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .context("Failed to build HTTP client")?;

    let model = resolve_model(&client, &base_url, llm.model.as_deref());

    let payload = json!({
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "あなたは個人CFOコンソールの分析アシスタントです。必ず指定されたJSONスキーマに従って回答してください。"
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "response_format": answer_schema()
    });

    let endpoint = format!("{}/chat/completions", base_url);
    let resp = client
        .post(&endpoint)
        .json(&payload)
        .send()
        .with_context(|| format!("LM Studio APIに接続できません ({})", base_url))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().unwrap_or_default();
        bail!("LM Studio APIエラー (HTTP {}): {}", status, body);
    }

    let body: Value = resp
        .json()
        .context("LM Studio APIの応答のJSONパースに失敗")?;
    let content = body["choices"][0]["message"]["content"]
        .as_str()
        .ok_or_else(|| anyhow!("LM Studio APIの応答形式が不正です: {:?}", body))?;

    match serde_json::from_str::<Value>(content) {
        Ok(data) => Ok(format_answer(&data)),
        Err(_) => Ok(content.to_string()),
    }
}
