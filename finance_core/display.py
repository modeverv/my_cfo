from __future__ import annotations

import unicodedata


def display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def fit(s: str, cols: int) -> str:
    """cols 表示列幅に収まるよう切り詰め、右側をスペースで埋める。"""
    result, width = [], 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if width + cw > cols:
            break
        result.append(c)
        width += cw
    return "".join(result) + " " * (cols - width)
