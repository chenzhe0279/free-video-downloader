from __future__ import annotations

import asyncio
import time
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.services.summary.errors import SummaryQuotaError, SummaryValidationError
from app.services.summary.schemas import SummaryPayload, SummaryStats
from app.services.summary.settings import SummarySettings
from app.services.summary.tasks import (
    CacheEntry,
    SummaryTask,
    SummaryTaskManager,
)

_URL = "https://www.bilibili.com/video/BV1s18cziEtw"


def _normalized(**overrides):
    data = {
        "id": "BV1s18cziEtw",
        "url": _URL,
        "title": "测试视频",
        "duration": 60,
        "platform": "bilibili",
        "uploader": "作者",
        "thumbnail": None,
        "is_playlist": False,
    }
    data.update(overrides)
    return data


class TaskManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = SummaryTaskManager()
        self.settings = SummarySettings(deepseek_api_key="test-key")

    async def test_reject_playlist(self) -> None:
        with (
            patch(
                "app.services.summary.tasks.get_summary_settings",
                return_value=self.settings,
            ),
            patch(
                "app.services.summary.tasks.media.probe",
                AsyncMock(return_value=_normalized(is_playlist=True)),
            ),
        ):
            with self.assertRaises(SummaryValidationError):
                await self.manager.create(_URL, "127.0.0.1")

    async def test_reject_over_duration(self) -> None:
        with (
            patch(
                "app.services.summary.tasks.get_summary_settings",
                return_value=self.settings,
            ),
            patch(
                "app.services.summary.tasks.media.probe",
                AsyncMock(return_value=_normalized(duration=99999)),
            ),
        ):
            with self.assertRaises(SummaryValidationError) as ctx:
                await self.manager.create(_URL, "127.0.0.1")
            self.assertIn("超过 AI 总结上限", str(ctx.exception))

    async def test_daily_quota(self) -> None:
        self.manager._daily_date = date.today()
        self.manager._daily["127.0.0.1"] = 1
        with self.assertRaises(SummaryQuotaError):
            self.manager._check_daily(
                "127.0.0.1",
                self.settings.model_copy(update={"summary_daily_limit_per_ip": 1}),
            )

    async def test_cache_roundtrip(self) -> None:
        task = SummaryTask(
            id="t1",
            url=_URL,
            client_ip="127.0.0.1",
            title="测试视频",
            duration=60,
            platform="bilibili",
            transcript_source="asr",
            segments=[],
            summary=SummaryPayload(tldr="一句话", overview="概述"),
            stats=SummaryStats(asr_seconds=60, model="deepseek-flash"),
        )
        key = self.manager._cache_key(_normalized())
        self.manager._put_cache(key, task, _normalized())
        entry = self.manager._get_cached(key)
        self.assertIsNotNone(entry)
        assert entry is not None
        cached_task = self.manager._task_from_cache(_URL, "127.0.0.1", entry)
        self.assertTrue(cached_task.cached)
        self.assertEqual(cached_task.status, "finished")
        self.assertEqual(cached_task.summary.tldr, "一句话")
        self.assertTrue(cached_task.stats.cached)

    async def test_cache_expiry(self) -> None:
        entry = CacheEntry(
            key="expired",
            summary=SummaryPayload(),
            segments=[],
            source="asr",
            language=None,
            meta={},
            stats=SummaryStats(),
            expires_at=time.time() - 1,
        )
        self.manager._cache["expired"] = entry
        self.assertIsNone(self.manager._get_cached("expired"))
        self.assertNotIn("expired", self.manager._cache)

    async def test_delete_releases_slot(self) -> None:
        task = SummaryTask(id="t2", url=_URL, client_ip="1.1.1.1")
        self.manager._tasks[task.id] = task
        self.manager._per_ip["1.1.1.1"] = 1
        self.assertTrue(self.manager.delete(task.id))
        self.assertIsNone(self.manager.get(task.id))
        self.assertNotIn("1.1.1.1", self.manager._per_ip)
        self.assertFalse(self.manager.delete(task.id))

    async def test_delete_running_task_cancels(self) -> None:
        async def slow_transcript(*args, **kwargs):
            await asyncio.sleep(10)
            raise AssertionError("should be cancelled")

        with (
            patch(
                "app.services.summary.tasks.get_summary_settings",
                return_value=self.settings,
            ),
            patch(
                "app.services.summary.tasks.media.probe",
                AsyncMock(return_value=_normalized()),
            ),
            patch.object(
                self.manager, "_acquire_transcript", side_effect=slow_transcript
            ),
        ):
            task, cached = await self.manager.create(_URL, "127.0.0.1")
            self.assertFalse(cached)
            await asyncio.sleep(0.05)
            self.assertTrue(self.manager.delete(task.id))
            await asyncio.sleep(0.1)
            self.assertEqual(task.status, "cancelled")
            self.assertNotIn("127.0.0.1", self.manager._per_ip)

    async def test_purge_expired(self) -> None:
        task = SummaryTask(
            id="t3",
            url=_URL,
            client_ip="1.1.1.1",
            status="finished",
            finished_at=time.time() - 10,
            ttl_seconds=1,
        )
        self.manager._tasks[task.id] = task
        self.assertEqual(self.manager.purge_expired(), 1)
        self.assertIsNone(self.manager.get(task.id))


if __name__ == "__main__":
    unittest.main()
