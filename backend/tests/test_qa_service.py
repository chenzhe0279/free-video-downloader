from __future__ import annotations

import unittest

from app.services.qa.errors import QaGateError, QaQuotaError, QaValidationError
from app.services.qa.service import QaService
from app.services.summary.schemas import SummaryPayload
from app.services.summary.settings import SummarySettings
from app.services.summary.tasks import SummaryTask


def _task() -> SummaryTask:
    return SummaryTask(
        id="task-1",
        url="https://example.com/video",
        client_ip="127.0.0.1",
        title="测试视频",
        summary=SummaryPayload(markdown="# 测试\n\n[00:00] 开场"),
    )


class FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    async def chat_json(self, messages, *, max_tokens=6000, temperature=0.2):
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return content, {"usage": {"total_tokens": 10}, "finish_reason": "stop"}

    async def stream_chat(self, messages, *, max_tokens=1200, temperature=0.3):
        for token in ["你", "好"]:
            yield token


class QaServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = SummarySettings(
            deepseek_api_key="test-key",
            qa_daily_limit_per_ip=1,
            qa_max_question_chars=20,
            qa_max_history_messages=4,
        )
        self.service = QaService(self.settings)

    def test_validate_question(self) -> None:
        with self.assertRaises(QaValidationError):
            self.service.validate_question("   ")
        with self.assertRaises(QaValidationError):
            self.service.validate_question("a" * 21)
        self.assertEqual(self.service.validate_question("  你好  "), "你好")

    def test_daily_quota(self) -> None:
        self.service.check_daily("127.0.0.1")
        self.service.increment_daily("127.0.0.1")
        with self.assertRaises(QaQuotaError):
            self.service.check_daily("127.0.0.1")

    def test_prepare_history(self) -> None:
        history = [
            ("user", "一"),
            ("assistant", "二"),
            ("user", "三"),
            ("assistant", "四"),
            ("user", "五"),
            ("assistant", "六"),
        ]
        prepared = self.service.prepare_history(
            [{"role": role, "content": text} for role, text in history]
        )
        self.assertEqual([item["content"] for item in prepared], ["三", "四", "五", "六"])

    async def test_gate_relevant(self) -> None:
        client = FakeClient(['{"relevant": true, "reason": "在问视频"}'])
        relevant, _ = await self.service.check_relevance(
            client, _task(), "视频讲了什么？", []
        )
        self.assertTrue(relevant)

    async def test_gate_unrelated(self) -> None:
        client = FakeClient(['{"relevant": false, "reason": "在问天气"}'])
        relevant, _ = await self.service.check_relevance(
            client, _task(), "今天天气怎么样？", []
        )
        self.assertFalse(relevant)

    async def test_gate_retry_invalid_json(self) -> None:
        client = FakeClient(
            ["不是 JSON", '{"relevant": true, "reason": "在问视频"}']
        )
        relevant, _ = await self.service.check_relevance(
            client, _task(), "视频讲了什么？", []
        )
        self.assertTrue(relevant)
        self.assertEqual(client.calls, 2)

    async def test_gate_fails_closed(self) -> None:
        client = FakeClient(["不是 JSON", "还是不是 JSON"])
        with self.assertRaises(QaGateError):
            await self.service.check_relevance(
                client, _task(), "视频讲了什么？", []
            )

    async def test_stream_answer(self) -> None:
        client = FakeClient([])
        tokens = [
            token
            async for token in self.service.stream_answer(
                client, _task(), "视频讲了什么？", []
            )
        ]
        self.assertEqual(tokens, ["你", "好"])


if __name__ == "__main__":
    unittest.main()
