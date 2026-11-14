from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """格式化为前端可解析的 SSE 事件。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
