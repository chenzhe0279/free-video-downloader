from __future__ import annotations

import unittest

from app.services.summary.markdown import build_markdown
from app.services.summary.schemas import (
    MindmapNode,
    SummaryChapter,
    SummaryConcept,
    SummaryKeyPoint,
    SummaryPayload,
)

_META = {
    "title": "测试视频",
    "platform": "BiliBili",
    "uploader": "作者",
    "duration": 120,
    "url": "https://example.com/video",
    "transcript_source": "asr",
    "model": "deepseek-flash",
}


def _payload(**overrides) -> SummaryPayload:
    values = {
        "tldr": "一句话总结",
        "overview": "内容概述",
        "keywords": ["AI", "视频总结"],
        "chapters": [
            SummaryChapter(
                start_seconds=0,
                title="第一章",
                summary="章节小结",
                key_points=["要点 A"],
            )
        ],
        "key_points": [
            SummaryKeyPoint(title="核心要点", detail="具体解释", timestamp_seconds=60)
        ],
        "concepts": [SummaryConcept(term="概念", explanation="解释")],
        "mindmap": MindmapNode(title="根节点", children=[MindmapNode(title="子节点")]),
    }
    values.update(overrides)
    return SummaryPayload(**values)


class MarkdownRenderTests(unittest.TestCase):
    def test_timestamps_become_seek_links(self) -> None:
        markdown = build_markdown(_payload(), _META)
        self.assertIn("### [00:00](#t=0) 第一章", markdown)
        self.assertIn("1. **核心要点** [01:00](#t=60)", markdown)

    def test_missing_timestamp_has_no_link(self) -> None:
        markdown = build_markdown(
            _payload(
                key_points=[
                    SummaryKeyPoint(title="没有时间", detail="", timestamp_seconds=None)
                ]
            ),
            _META,
        )
        self.assertIn("1. **没有时间**", markdown)
        self.assertNotIn("1. **没有时间** [", markdown)

    def test_special_characters_are_escaped(self) -> None:
        markdown = build_markdown(
            _payload(
                tldr="[恶意](javascript:alert(1)) *强调*",
                chapters=[
                    SummaryChapter(
                        start_seconds=0,
                        title="章节 [x](y)",
                        summary="含 <b> 标签",
                    )
                ],
                key_points=[
                    SummaryKeyPoint(
                        title="要点 *a*", detail="详情 [b]", timestamp_seconds=0
                    )
                ],
                concepts=[SummaryConcept(term="术语_a", explanation="解释|内容")],
            ),
            _META,
        )
        self.assertIn(r"\[恶意\]", markdown)
        self.assertNotIn("[恶意](", markdown)
        self.assertIn(r"\*强调\*", markdown)
        self.assertIn(r"章节 \[x\](y)", markdown)
        self.assertIn(r"\<b\>", markdown)
        self.assertIn(r"\*a\*", markdown)
        self.assertIn(r"\[b\]", markdown)
        self.assertIn(r"术语\_a", markdown)
        self.assertIn(r"解释\|内容", markdown)

    def test_newlines_are_folded(self) -> None:
        markdown = build_markdown(
            _payload(overview="第一行\n第二行\n\n第三行"), _META
        )
        self.assertIn("第一行 第二行 第三行", markdown)
        self.assertNotIn("第一行\n第二行", markdown)

    def test_keywords_are_code_spans(self) -> None:
        markdown = build_markdown(_payload(keywords=["AI", "a|b"]), _META)
        self.assertIn("`AI` `a|b`", markdown)

    def test_sections_and_disclaimer_are_kept(self) -> None:
        markdown = build_markdown(_payload(), _META)
        for section in (
            "# 测试视频",
            "## 一句话总结",
            "## 内容概述",
            "## 关键词",
            "## 章节大纲",
            "## 核心要点",
            "## 关键概念",
            "## 思维导图",
            "AI 语音识别",
            "AI 生成内容可能存在偏差",
        ):
            self.assertIn(section, markdown)


if __name__ == "__main__":
    unittest.main()
