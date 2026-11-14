from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.api import qa as qa_api
from app.services.qa.errors import QaGateError, QaQuotaError, QaValidationError
from app.services.summary.schemas import SummaryPayload
from app.services.summary.settings import SummarySettings
from app.services.summary.tasks import SummaryTask, summary_manager

_URL = "https://example.com/video"


def _task() -> SummaryTask:
    return SummaryTask(
        id="task-qa",
        url=_URL,
        client_ip="127.0.0.1",
        title="测试视频",
        status="finished",
        finished_at=time.time(),
        summary=SummaryPayload(
            tldr="测试总结",
            markdown="# 测试视频\n\n[00:00] 开场",
            chapters=[{"title": "第一章"}],
        ),
    )


class FakeQaService:
    def __init__(self, *, relevant: bool = True, gate_error: bool = False) -> None:
        self.relevant = relevant
        self.gate_error = gate_error
        self.streamed = False

    def validate_question(self, question: str) -> str:
        return question.strip()

    def prepare_history(self, history):
        return []

    def check_daily(self, ip: str) -> None:
        return None

    def increment_daily(self, ip: str) -> None:
        return None

    async def check_relevance(self, *args, **kwargs):
        if self.gate_error:
            raise QaGateError("判断失败")
        return self.relevant, {}

    def suggestions(self, task):
        return ["第一章讲了什么？"]

    async def stream_answer(self, *args, **kwargs):
        self.streamed = True
        yield "你"
        yield "好"


class ValidationFailService(FakeQaService):
    def validate_question(self, question: str) -> str:
        raise QaValidationError("问题过长")


class QuotaFailService(FakeQaService):
    def check_daily(self, ip: str) -> None:
        raise QaQuotaError("今日额度已用完")


class QaApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        app = FastAPI()
        app.include_router(qa_api.router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        summary_manager._tasks.clear()
        qa_api.qa_limiter._hits.clear()
        self.settings = SummarySettings(deepseek_api_key="test-key")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        summary_manager._tasks.clear()
        qa_api.qa_limiter._hits.clear()

    async def test_missing_task_returns_404(self) -> None:
        with patch.object(
            qa_api, "get_summary_settings", return_value=self.settings
        ):
            response = await self.client.post(
                "/api/summary/nope/ask", json={"question": "你好"}
            )
        self.assertEqual(response.status_code, 404)

    async def test_unfinished_summary_returns_409(self) -> None:
        task = _task()
        task.status = "summarizing"
        summary_manager._tasks[task.id] = task
        with patch.object(
            qa_api, "get_summary_settings", return_value=self.settings
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "你好"}
            )
        self.assertEqual(response.status_code, 409)

    async def test_disabled_returns_503(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        with patch.object(
            qa_api,
            "get_summary_settings",
            return_value=SummarySettings(deepseek_api_key="test-key", qa_enabled=False),
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "你好"}
            )
        self.assertEqual(response.status_code, 503)

    async def test_unrelated_streams_refusal(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        fake = FakeQaService(relevant=False)
        with (
            patch.object(qa_api, "qa_service", fake),
            patch.object(qa_api, "get_summary_settings", return_value=self.settings),
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "今天天气怎么样？"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        body = response.text
        self.assertIn("event: status", body)
        self.assertIn("event: refusal", body)
        self.assertIn("event: done", body)
        self.assertIn("与当前视频内容相关", body)
        self.assertFalse(fake.streamed)

    async def test_relevant_streams_tokens(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        fake = FakeQaService(relevant=True)
        with (
            patch.object(qa_api, "qa_service", fake),
            patch.object(qa_api, "get_summary_settings", return_value=self.settings),
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "视频讲了什么？"}
            )
        body = response.text
        self.assertIn('"phase": "checking"', body)
        self.assertIn('"phase": "answering"', body)
        self.assertIn("event: token", body)
        self.assertIn("你", body)
        self.assertIn("好", body)
        self.assertIn("event: done", body)
        self.assertTrue(fake.streamed)

    async def test_gate_error_streams_error(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        fake = FakeQaService(gate_error=True)
        with (
            patch.object(qa_api, "qa_service", fake),
            patch.object(qa_api, "get_summary_settings", return_value=self.settings),
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "视频讲了什么？"}
            )
        self.assertIn("event: error", response.text)
        self.assertIn("判断失败", response.text)

    async def test_validation_and_quota_errors(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        with (
            patch.object(qa_api, "qa_service", ValidationFailService()),
            patch.object(qa_api, "get_summary_settings", return_value=self.settings),
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "问题"}
            )
        self.assertEqual(response.status_code, 422)

        with (
            patch.object(qa_api, "qa_service", QuotaFailService()),
            patch.object(qa_api, "get_summary_settings", return_value=self.settings),
        ):
            response = await self.client.post(
                f"/api/summary/{task.id}/ask", json={"question": "问题"}
            )
        self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
