from __future__ import annotations

import unittest

from app.services.qa.prompts import (
    NOT_MENTIONED,
    build_answer_messages,
    build_gate_messages,
    build_material,
    suggest_questions,
    trim_history,
)
from app.services.summary.schemas import SummaryPayload, TranscriptSegment
from app.services.summary.tasks import SummaryTask


def _task() -> SummaryTask:
    summary = SummaryPayload(
        tldr="一句话总结",
        overview="概述",
        keywords=["AI", "视频"],
        chapters=[{"title": "第一章", "start_seconds": 0}],
        markdown="# 标题\n\n## 章节\n\n[00:00] 开场\n[01:00] 结论",
    )
    return SummaryTask(
        id="task-1",
        url="https://example.com/video",
        client_ip="127.0.0.1",
        title="测试视频",
        uploader="测试作者",
        platform="bilibili",
        duration=90,
        summary=summary,
        segments=[TranscriptSegment(start_seconds=0, text="逐字稿机密内容")],
    )


class QaPromptTests(unittest.TestCase):
    def test_build_material_uses_summary_only(self) -> None:
        material = build_material(_task(), max_chars=12000)
        self.assertIn("测试视频", material)
        self.assertIn("开场", material)
        self.assertIn("测试作者", material)
        self.assertIn("01:30", material)
        self.assertNotIn("逐字稿机密内容", material)

    def test_build_material_truncates(self) -> None:
        material = build_material(_task(), max_chars=50)
        self.assertLessEqual(len(material), 80)
        self.assertIn("材料过长", material)

    def test_trim_history(self) -> None:
        history = [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "一"},
            {"role": "assistant", "content": "二"},
            {"role": "user", "content": "三"},
            {"role": "assistant", "content": "四"},
            {"role": "user", "content": "五"},
            {"role": "assistant", "content": "六"},
            {"role": "user", "content": "  "},
        ]
        trimmed = trim_history(history, max_messages=4)
        self.assertEqual(
            [item["content"] for item in trimmed], ["三", "四", "五", "六"]
        )
        self.assertTrue(
            all(item["role"] in {"user", "assistant"} for item in trimmed)
        )

    def test_gate_messages_include_material_and_question(self) -> None:
        messages = build_gate_messages("材料内容", "核心观点是什么？", [], max_history=2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("相关", messages[0]["content"])
        self.assertIn("材料内容", messages[1]["content"])
        self.assertIn("核心观点是什么？", messages[1]["content"])

    def test_answer_messages_include_history_and_current_question(self) -> None:
        messages = build_answer_messages(
            "材料内容",
            "第一点再展开",
            [
                {"role": "user", "content": "视频讲了什么？"},
                {"role": "assistant", "content": "讲了三个要点。"},
            ],
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(NOT_MENTIONED, messages[0]["content"])
        self.assertEqual(messages[1]["content"], "视频讲了什么？")
        self.assertEqual(messages[-1]["content"], "第一点再展开")

    def test_suggestions_dedupe_and_limit(self) -> None:
        summary = SummaryPayload(
            chapters=[
                {"title": "第一章"},
                {"title": "第一章"},
                {"title": "第二章"},
                {"title": "第三章"},
            ]
        )
        suggestions = suggest_questions(summary)
        self.assertEqual(suggestions[0], "用三句话总结这个视频")
        self.assertLessEqual(len(suggestions), 4)
        self.assertEqual(len(set(suggestions)), len(suggestions))


if __name__ == "__main__":
    unittest.main()
