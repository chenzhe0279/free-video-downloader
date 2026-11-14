from __future__ import annotations

import asyncio
import json
import time
import unittest
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI

from app.api import summary as summary_api
from app.services.summary.schemas import SummaryPayload
from app.services.summary.settings import SummarySettings
from app.services.summary.stream import iter_markdown_chunks, summary_event_stream
from app.services.summary.tasks import SummaryTask, summary_manager

_URL = "https://example.com/video"
_MARKDOWN = (
    "# 测试视频\n\n"
    "## 一句话总结\n\n"
    "这是一段用于验证流式分块的总结正文，长度足够覆盖多个 chunk。\n\n"
    "## 关键词\n\n- 巡演\n- 独白\n- 死亡疑问\n"
)


class FakeRequest:
    def __init__(self, disconnect_after: int | None = None) -> None:
        self.calls = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.disconnect_after is not None and self.calls > self.disconnect_after


def _settings(**kwargs: Any) -> SummarySettings:
    base: dict[str, Any] = {
        "deepseek_api_key": "test-key",
        "summary_stream_poll_seconds": 0.2,
        "summary_stream_interval_ms": 0,
        "summary_stream_chunk_chars": 40,
    }
    base.update(kwargs)
    return SummarySettings(**base)


def _task(status: str = "finished") -> SummaryTask:
    return SummaryTask(
        id="task-stream",
        url=_URL,
        client_ip="127.0.0.1",
        title="测试视频",
        duration=68.0,
        status=status,
        stage="生成总结",
        progress=90.0,
        message="正在生成结构化总结…",
        finished_at=time.time() if status == "finished" else None,
        summary=SummaryPayload(
            tldr="测试总结",
            markdown=_MARKDOWN,
            chapters=[{"title": "第一章"}],
        )
        if status == "finished"
        else None,
    )


def parse_events(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        name = "message"
        data: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((name, data))
    return events


async def collect(stream: AsyncIterator[str]) -> list[tuple[str, dict[str, Any]]]:
    return parse_events("".join([chunk async for chunk in stream]))


class MarkdownChunkTests(unittest.TestCase):
    def test_chunks_round_trip(self) -> None:
        chunks = list(iter_markdown_chunks(_MARKDOWN, 40))
        self.assertGreater(len(chunks), 2)
        self.assertEqual("".join(chunks), _MARKDOWN)
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))

    def test_long_single_line_is_split(self) -> None:
        text = "x" * 250
        chunks = list(iter_markdown_chunks(text, 40))
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))

    def test_empty_markdown(self) -> None:
        self.assertEqual(list(iter_markdown_chunks("", 40)), [])


class SummaryStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        summary_manager._tasks.clear()

    async def asyncTearDown(self) -> None:
        summary_manager._tasks.clear()

    async def test_finished_task_streams_meta_deltas_done(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        events = await collect(
            summary_event_stream(task.id, FakeRequest(), _settings())
        )
        names = [name for name, _ in events]
        self.assertEqual(names[0], "meta")
        self.assertEqual(names[-1], "done")
        self.assertTrue(all(name == "delta" for name in names[1:-1]))
        self.assertGreaterEqual(names.count("delta"), 3)

        text = "".join(data["text"] for name, data in events if name == "delta")
        self.assertEqual(text, _MARKDOWN)
        meta = events[0][1]
        self.assertEqual(meta["task_id"], task.id)
        self.assertEqual(meta["status"], "finished")
        self.assertEqual(meta["summary"]["markdown"], _MARKDOWN)
        self.assertEqual(events[-1][1]["task_id"], task.id)

    async def test_unfinished_task_emits_state_only(self) -> None:
        task = _task(status="transcribing")
        summary_manager._tasks[task.id] = task

        async def first_event() -> list[tuple[str, dict[str, Any]]]:
            collected: list[str] = []
            async for chunk in summary_event_stream(task.id, FakeRequest(), _settings()):
                collected.append(chunk)
                break
            return parse_events("".join(collected))

        events = await asyncio.wait_for(first_event(), timeout=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "state")
        self.assertEqual(events[0][1]["status"], "transcribing")
        self.assertEqual(events[0][1]["stage"], "生成总结")
        self.assertEqual(events[0][1]["message"], "正在生成结构化总结…")

    async def test_unfinished_then_finished_switches_to_meta(self) -> None:
        task = _task(status="transcribing")
        summary_manager._tasks[task.id] = task

        async def collect_after_finish() -> list[tuple[str, dict[str, Any]]]:
            collected: list[str] = []
            async for chunk in summary_event_stream(task.id, FakeRequest(), _settings()):
                collected.append(chunk)
                events = parse_events("".join(collected))
                if len(events) == 1:
                    # 模拟后台任务在等待期间完成
                    task.status = "finished"
                    task.summary = SummaryPayload(
                        tldr="测试总结", markdown=_MARKDOWN, chapters=[{"title": "第一章"}]
                    )
                    task.finished_at = time.time()
                if events and events[-1][0] == "done":
                    break
            return parse_events("".join(collected))

        events = await asyncio.wait_for(collect_after_finish(), timeout=5)
        names = [name for name, _ in events]
        self.assertEqual(names[0], "state")
        self.assertEqual(names[1], "meta")
        self.assertEqual(names[-1], "done")
        self.assertGreater(names.count("delta"), 0)

    async def test_state_is_not_repeated(self) -> None:
        task = _task(status="transcribing")
        summary_manager._tasks[task.id] = task
        request = FakeRequest(disconnect_after=5)
        events = await collect(summary_event_stream(task.id, request, _settings()))
        self.assertEqual([name for name, _ in events], ["state"])
        self.assertTrue(events)  # 断开后不应出现 error/done

    async def test_state_event_does_not_expose_progress(self) -> None:
        task = _task(status="transcribing")
        summary_manager._tasks[task.id] = task
        events = await collect(
            summary_event_stream(task.id, FakeRequest(disconnect_after=2), _settings())
        )
        self.assertEqual([name for name, _ in events], ["state"])
        # 前端不再展示进度条：state 只带阶段文案，不带 progress/百分比
        self.assertEqual(set(events[0][1]), {"status", "stage", "message"})
        self.assertNotIn("progress", events[0][1])

    async def test_error_task_emits_error(self) -> None:
        task = _task(status="error")
        task.error = "语音识别失败"
        summary_manager._tasks[task.id] = task
        events = await collect(
            summary_event_stream(task.id, FakeRequest(), _settings())
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "error")
        self.assertIn("语音识别失败", events[0][1]["message"])

    async def test_cancelled_task_emits_cancelled(self) -> None:
        task = _task(status="cancelled")
        summary_manager._tasks[task.id] = task
        events = await collect(
            summary_event_stream(task.id, FakeRequest(), _settings())
        )
        self.assertEqual(events[0][0], "cancelled")

    async def test_missing_task_emits_gone(self) -> None:
        events = await collect(
            summary_event_stream("missing", FakeRequest(), _settings())
        )
        self.assertEqual(events[0][0], "gone")

    async def test_disconnect_stops_delta_stream(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        events = await collect(
            summary_event_stream(task.id, FakeRequest(disconnect_after=2), _settings())
        )
        names = [name for name, _ in events]
        self.assertEqual(names[0], "meta")
        self.assertNotIn("done", names)


class SummaryStreamApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        app = FastAPI()
        app.include_router(summary_api.router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        summary_manager._tasks.clear()

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        summary_manager._tasks.clear()

    async def test_missing_task_returns_404(self) -> None:
        response = await self.client.get("/api/summary/nope/stream")
        self.assertEqual(response.status_code, 404)

    async def test_finished_task_returns_event_stream(self) -> None:
        from unittest.mock import patch

        task = _task()
        summary_manager._tasks[task.id] = task
        with patch.object(
            summary_api,
            "get_summary_settings",
            return_value=_settings(),
        ):
            response = await self.client.get(f"/api/summary/{task.id}/stream")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        events = parse_events(response.text)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[-1][0], "done")

    async def test_finished_task_headers_and_empty_markdown(self) -> None:
        from unittest.mock import patch

        task = _task()
        task.summary = SummaryPayload(tldr="没有正文", markdown="")
        summary_manager._tasks[task.id] = task
        with patch.object(
            summary_api,
            "get_summary_settings",
            return_value=_settings(),
        ):
            response = await self.client.get(f"/api/summary/{task.id}/stream")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        events = parse_events(response.text)
        # 没有 Markdown 正文时直接 meta → done，不产生空 delta
        self.assertEqual([name for name, _ in events], ["meta", "done"])
