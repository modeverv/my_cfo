from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "finance_config.yaml"


def load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except ImportError:
        # PyYAML未インストール時は簡易パーサーで key: value だけ読む
        return _simple_yaml(CONFIG_PATH)


def _simple_yaml(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current: dict[str, Any] = result
    parent_key: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, _, raw_val = stripped.partition(":")
            val = raw_val.strip()
            if line.startswith(" ") or line.startswith("\t"):
                if parent_key is not None:
                    current[key.strip()] = val or None
            else:
                parent_key = key.strip()
                current = {}
                result[parent_key] = current
    return result
