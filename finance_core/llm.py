from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from finance_core.config import load as load_config


DEFAULT_BASE_URL = "http://localhost:1234/v1"

ANSWER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "finance_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "conclusion": {
                    "type": "string",
                    "description": "結論を1〜2文で簡潔に"
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "数値根拠のリスト"
                },
                "points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "増加要因・注意点の箇条書き"
                },
                "unknown": {
                    "type": "string",
                    "description": "不明な点。なければ空文字"
                }
            },
            "required": ["conclusion", "evidence", "points", "unknown"],
            "additionalProperties": False
        }
    }
}


def _format_answer(data: dict) -> str:
    lines = [
        "【結論】",
        data.get("conclusion", ""),
        "",
        "【数値根拠】",
        *[f"・{e}" for e in data.get("evidence", [])],
        "",
        "【要因・注意点】",
        *[f"・{p}" for p in data.get("points", [])],
    ]
    unknown = data.get("unknown", "").strip()
    if unknown:
        lines += ["", "【不明な点】", unknown]
    return "\n".join(lines)


def _llm_config() -> dict:
    return load_config().get("llm", {})


def _resolve_model(base_url: str, preferred: str | None) -> str:
    """yaml → 環境変数 → API自動選択 の優先順でモデルを決定する"""
    if preferred:
        return preferred
    env_model = os.environ.get("LM_STUDIO_MODEL")
    if env_model:
        return env_model
    yaml_model = _llm_config().get("model")
    if yaml_model:
        return yaml_model
    try:
        req = urllib.request.Request(f"{base_url}/models")
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read())
        candidates = [
            m["id"] for m in data.get("data", [])
            if "embed" not in m["id"].lower()
        ]
        if candidates:
            return candidates[0]
    except Exception:
        pass
    return "local-model"


def chat_completion(
    prompt: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout_seconds: int = 120,
) -> str:
    cfg = _llm_config()
    resolved_base_url = (
        base_url
        or os.environ.get("LM_STUDIO_BASE_URL")
        or cfg.get("base_url")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    resolved_model = _resolve_model(resolved_base_url, model)
    endpoint = f"{resolved_base_url}/chat/completions"

    payload = {
        "model": resolved_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "あなたは個人CFOコンソールの分析アシスタントです。"
                    "必ず指定されたJSONスキーマに従って回答してください。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": ANSWER_SCHEMA,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LM Studio APIエラー (HTTP {exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"LM Studio APIに接続できません ({resolved_base_url}): {exc}"
        ) from exc

    decoded = json.loads(body)
    try:
        content = decoded["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LM Studio APIの応答形式が不正です: {decoded}") from exc

    try:
        return _format_answer(json.loads(content))
    except (json.JSONDecodeError, TypeError):
        return content
