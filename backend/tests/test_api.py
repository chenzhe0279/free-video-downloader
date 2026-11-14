from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.api.summary import router, summary_limiter
from app.services.summary.errors import SummaryQuotaError, SummaryValidationError
from app.services.summary.schemas import TranscriptSegment
from app.services.summary.settings import SummarySettings
from app.services.summary.tasks import SummaryTask, summary_manager

_URL = "https://www.bilibili.com/video/BV1s18cziEtw"


def _enabled_settings(**overrides) -> SummarySettings:
    values = {"deepseek_api_key": "test-key", "summary_rate_limit_per_minute": 100}
    values.update(overrides)
    return SummarySettings(**values)


def _disabled_settings() -> SummarySettings:
    return SummarySettings(summary_enabled=True, deepseek_api_key=None)


class SummaryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        app = FastAPI()
        app.include_router(router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        summary_manager._tasks.clear()
        summary_manager._per_ip.clear()
        summary_manager._daily.clear()
        summary_manager._cache.clear()
        summary_limiter._hits.clear()

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        summary_manager._tasks.clear()
        summary_manager._per_ip.clear()
        summary_manager._daily.clear()
        summary_manager._cache.clear()

    async def test_config_disabled_without_key(self) -> None:
        with patch(
            "app.api.summary.get_summary_settings",
            return_value=_disabled_settings(),
        ):
            response = await self.client.get("/api/summary/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertIn("VDS_DEEPSEEK_API_KEY", body["reason"])

    async def test_config_enabled(self) -> None:
        with patch(
            "app.api.summary.get_summary_settings",
            return_value=_enabled_settings(),
        ):
            response = await self.client.get("/api/summary/config")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])

    async def test_create_disabled_returns_503(self) -> None:
        with (
            patch(
                "app.api.summary.get_summary_settings",
                return_value=_disabled_settings(),
            ),
            patch("app.api.summary.validate_public_url", return_value=_URL),
        ):
            response = await self.client.post("/api/summary", json={"url": _URL})
        self.assertEqual(response.status_code, 503)
        self.assertIn("VDS_DEEPSEEK_API_KEY", response.json()["detail"])

    async def test_create_success(self) -> None:
        task = SummaryTask(id="task-1", url=_URL, client_ip="127.0.0.1")
        with (
            patch(
                "app.api.summary.get_summary_settings",
                return_value=_enabled_settings(),
            ),
            patch("app.api.summary.validate_public_url", return_value=_URL),
            patch.object(
                summary_manager,
                "create",
                AsyncMock(return_value=(task, False)),
            ),
        ):
            response = await self.client.post(
                "/api/summary", json={"url": _URL, "force": False}
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["task_id"], "task-1")
        self.assertFalse(response.json()["cached"])

    async def test_create_validation_returns_422(self) -> None:
        with (
            patch(
                "app.api.summary.get_summary_settings",
                return_value=_enabled_settings(),
            ),
            patch("app.api.summary.validate_public_url", return_value=_URL),
            patch.object(
                summary_manager,
                "create",
                AsyncMock(side_effect=SummaryValidationError("视频超过时长上限")),
            ),
        ):
            response = await self.client.post("/api/summary", json={"url": _URL})
        self.assertEqual(response.status_code, 422)
        self.assertIn("时长上限", response.json()["detail"])

    async def test_create_quota_returns_429(self) -> None:
        with (
            patch(
                "app.api.summary.get_summary_settings",
                return_value=_enabled_settings(),
            ),
            patch("app.api.summary.validate_public_url", return_value=_URL),
            patch.object(
                summary_manager,
                "create",
                AsyncMock(side_effect=SummaryQuotaError("今日额度已用完")),
            ),
        ):
            response = await self.client.post("/api/summary", json={"url": _URL})
        self.assertEqual(response.status_code, 429)

    async def test_get_task_and_transcript_and_delete(self) -> None:
        task = SummaryTask(
            id="task-2",
            url=_URL,
            client_ip="127.0.0.1",
            title="测试视频",
            duration=60,
            status="finished",
            stage="已完成",
            progress=100,
            transcript_source="asr",
            segments=[
                TranscriptSegment(start_seconds=0, end_seconds=60, text="逐字稿内容")
            ],
            finished_at=time.time(),
        )
        summary_manager._tasks[task.id] = task

        response = await self.client.get(f"/api/summary/{task.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "finished")

        response = await self.client.get(f"/api/summary/{task.id}/transcript")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["segments"][0]["text"], "逐字稿内容")

        response = await self.client.delete(f"/api/summary/{task.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(summary_manager.get(task.id))

    async def test_missing_task_returns_404(self) -> None:
        response = await self.client.get("/api/summary/not-found")
        self.assertEqual(response.status_code, 404)
        response = await self.client.delete("/api/summary/not-found")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
