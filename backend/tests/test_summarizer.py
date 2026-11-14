from __future__ import annotations

import json
import unittest

from app.services.summary.deepseek import parse_json_object
from app.services.summary.schemas import (
    SummaryChapter,
    SummaryKeyPoint,
    SummaryPayload,
    TranscriptResult,
    TranscriptSegment,
)
from app.services.summary.settings import SummarySettings
from app.services.summary.summarizer import (
    normalize_payload,
    summarize,
)
from app.services.summary.markdown import build_markdown


def _payload() -> SummaryPayload:
    return SummaryPayload(
        tldr="",
        overview="这是一段整体概述，说明视频的背景与结论。",
        keywords=["AI", "AI", "视频总结"],
        chapters=[
            SummaryChapter(
                start_seconds=999,
                end_seconds=10,
                title="第一章",
                summary="第一章小结",
                key_points=["要点 A"],
            ),
            SummaryChapter(
                start_seconds=30,
                end_seconds=20,
                title="第一章",
                summary="重复标题应被去掉",
            ),
        ],
        key_points=[
            SummaryKeyPoint(title="", detail="没有标题的要点", timestamp_seconds=999),
            SummaryKeyPoint(title="重复", detail="重复", timestamp_seconds=1),
            SummaryKeyPoint(title="重复", detail="重复", timestamp_seconds=2),
        ],
        concepts=[],
        mindmap=None,
    )


class NormalizeTests(unittest.TestCase):
    def test_normalizes_timestamps_and_fallbacks(self) -> None:
        result = normalize_payload(_payload(), duration=100, title="测试视频")
        self.assertTrue(result.tldr)
        self.assertEqual(result.chapters[0].start_seconds, 100.0)
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(result.keywords, ["AI", "视频总结"])
        self.assertLessEqual(len(result.key_points), 12)
        self.assertIsNotNone(result.mindmap)
        self.assertEqual(result.mindmap.title, "测试视频")
        self.assertTrue(result.mindmap.children)

    def test_markdown_contains_sections(self) -> None:
        result = normalize_payload(_payload(), duration=100, title="测试视频")
        markdown = build_markdown(
            result,
            {
                "title": "测试视频",
                "uploader": "作者",
                "platform": "bilibili",
                "duration": 100,
                "url": "https://example.com",
                "transcript_source": "asr",
                "model": "deepseek-flash",
            },
        )
        self.assertIn("# 测试视频", markdown)
        self.assertIn("## 章节大纲", markdown)
        self.assertIn("## 核心要点", markdown)
        self.assertIn("AI 语音识别", markdown)

    def test_timestamps_snap_to_transcript_markers(self) -> None:
        result = normalize_payload(
            _payload(),
            duration=100,
            title="测试视频",
            allowed_starts=[0, 60],
        )
        self.assertTrue(
            all(chapter.start_seconds in {0, 60} for chapter in result.chapters)
        )
        self.assertTrue(
            all(
                point.timestamp_seconds in {None, 0, 60}
                for point in result.key_points
            )
        )


class JsonExtractionTests(unittest.TestCase):
    def test_code_fence(self) -> None:
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_around_json(self) -> None:
        self.assertEqual(parse_json_object('结果如下：{"a": 1} 谢谢'), {"a": 1})

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_object("not json")


class FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def chat_json(self, messages, *, max_tokens=6000, temperature=0.2):
        self.messages.append(messages)
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return content, {"usage": {"total_tokens": 10}, "finish_reason": "stop"}


class SummarizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarize_with_fake_client(self) -> None:
        payload = {
            "tldr": "一句话",
            "overview": "概述",
            "keywords": ["AI"],
            "chapters": [
                {
                    "start_seconds": 0,
                    "end_seconds": 60,
                    "title": "章节",
                    "summary": "小结",
                    "key_points": ["要点"],
                }
            ],
            "key_points": [{"title": "要点", "detail": "解释", "timestamp_seconds": 0}],
            "concepts": [],
            "mindmap": {"title": "主题", "children": []},
        }
        client = FakeClient([json.dumps(payload, ensure_ascii=False)])
        settings = SummarySettings(deepseek_api_key="test-key")
        transcript = TranscriptResult(
            source="asr",
            segments=[
                TranscriptSegment(start_seconds=0, end_seconds=60, text="这是逐字稿内容。" * 10)
            ],
            asr_seconds=60,
            chunks=1,
        )
        result, usage = await summarize(
            client,  # type: ignore[arg-type]
            {"title": "视频", "duration": 60, "platform": "bilibili"},
            transcript,
            settings,
        )
        self.assertEqual(result.tldr, "一句话")
        self.assertIn("## 一句话总结", result.markdown)
        self.assertEqual(usage["usage"]["total_tokens"], 10)

    async def test_retry_invalid_json(self) -> None:
        payload = {
            "tldr": "重试成功",
            "overview": "概述",
            "chapters": [{"start_seconds": 0, "title": "章节", "key_points": []}],
            "key_points": [],
        }
        client = FakeClient(["这不是 JSON", json.dumps(payload, ensure_ascii=False)])
        settings = SummarySettings(deepseek_api_key="test-key")
        transcript = TranscriptResult(
            source="asr",
            segments=[TranscriptSegment(start_seconds=0, text="逐字稿" * 20)],
        )
        result, _ = await summarize(
            client,  # type: ignore[arg-type]
            {"title": "视频", "duration": 60},
            transcript,
            settings,
        )
        self.assertEqual(result.tldr, "重试成功")
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
