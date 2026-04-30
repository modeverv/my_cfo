from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "local-model"


def chat_completion(
    prompt: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout_seconds: int = 120,
) -> str:
    resolved_base_url = (base_url or os.environ.get("LM_STUDIO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    resolved_model = model or os.environ.get("LM_STUDIO_MODEL") or DEFAULT_MODEL
    endpoint = f"{resolved_base_url}/chat/completions"

    payload = {
        "model": resolved_model,
        "messages": [
            {
                "role": "system",
                "content": "あなたは個人CFOコンソールの分析アシスタントです。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
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
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LM Studio APIに接続できません: {exc}") from exc

    decoded = json.loads(body)
    try:
        return decoded["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LM Studio APIの応答形式が不正です: {decoded}") from exc
