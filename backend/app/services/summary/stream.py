"""AI 总结的进度与内容流（SSE）。

前端不再展示进度条：创建任务后直接连上本流，未完成时收到 ``state`` 事件，
用来渲染“正在总结中……”的思考动画；完成后先收到 ``meta``（完整任务状态），
再把已经生成好的 Markdown 逐块下发 ``delta``，最后 ``done``。
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Iterator

from app.services.qa.sse import sse_event
from app.services.summary.settings import SummarySettings
from app.services.summary.tasks import summary_manager

logger = logging.getLogger("vds.summary.stream")

# 心跳：长时间没有状态变化时定期发注释行，避免中间代理掐断连接
_KEEPALIVE_SECONDS = 12.0


def iter_markdown_chunks(markdown: str, chunk_chars: int = 80) -> Iterator[str]:
    """把 Markdown 切成固定长度的片段，保证 ``"".join(chunks) == markdown``。

    优先在整行边界切分；超长行按长度硬切，避免一次性下发导致“跳字”。
    """
    if not markdown:
        return
    size = max(16, int(chunk_chars))
    buffer = ""
    for line in markdown.splitlines(keepends=True):
        if len(buffer) + len(line) <= size:
            buffer += line
            continue
        if buffer:
            yield buffer
            buffer = ""
        while len(line) > size:
            yield line[:size]
            line = line[size:]
        buffer = line
    if buffer:
        yield buffer


async def summary_event_stream(
    task_id: str,
    request: object,
    settings: SummarySettings,
) -> AsyncIterator[str]:
    """把任务状态与最终内容封装成统一的事件流。"""
    last_state: dict[str, object] | None = None
    idle = 0.0
    poll = max(0.2, float(settings.summary_stream_poll_seconds))
    interval = max(0.0, settings.summary_stream_interval_ms / 1000)
    try:
        while True:
            if await request.is_disconnected():  # type: ignore[attr-defined]
                return

            task = summary_manager.get(task_id)
            if task is None:
                yield sse_event("gone", {"message": "总结任务不存在或已过期"})
                return
            if task.status == "cancelled":
                yield sse_event("cancelled", {"message": task.message or "任务已取消"})
                return
            if task.status == "error":
                yield sse_event("error", {"message": task.error or "总结失败，请稍后重试"})
                return
            if task.status == "finished" and task.summary is not None:
                payload = summary_manager.serialize(task).model_dump(mode="json")
                yield sse_event("meta", payload)
                markdown = task.summary.markdown or ""
                for chunk in iter_markdown_chunks(markdown, settings.summary_stream_chunk_chars):
                    if await request.is_disconnected():  # type: ignore[attr-defined]
                        return
                    yield sse_event("delta", {"text": chunk})
                    if interval:
                        await asyncio.sleep(interval)
                yield sse_event("done", payload)
                return

            state: dict[str, object] = {
                "status": task.status,
                "stage": task.stage,
                "message": task.message,
            }
            if state != last_state:
                yield sse_event("state", state)
                last_state = state
                idle = 0.0
            else:
                idle += poll
                if idle >= _KEEPALIVE_SECONDS:
                    yield ": keep-alive\n\n"
                    idle = 0.0
            await asyncio.sleep(poll)
    except asyncio.CancelledError:
        raise
    except Exception:  # pragma: no cover - 防御性兜底
        logger.exception("summary stream crashed task=%s", task_id)
        yield sse_event("error", {"message": "总结流中断，请稍后重试"})
