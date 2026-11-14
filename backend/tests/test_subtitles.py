from __future__ import annotations

import json
import unittest

from app.services.summary.schemas import TranscriptSegment
from app.services.summary.subtitles import (
    parse_subtitle,
    pick_subtitle,
    segments_to_blocks,
    transcript_chars,
)


class SubtitleParserTests(unittest.TestCase):
    def test_vtt_parsing_and_rolling_dedupe(self) -> None:
        text = """WEBVTT

00:00:01.000 --> 00:00:03.000
Hello <c>world</c>

00:00:03.500 --> 00:00:05.000
Hello world again
"""
        segments = parse_subtitle(text, "vtt")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "Hello world")
        self.assertEqual(segments[0].start_seconds, 1.0)
        self.assertEqual(segments[1].text, "again")

    def test_srt_parsing(self) -> None:
        text = """1
00:00:01,000 --> 00:00:03,500
第一句

2
00:00:04,000 --> 00:00:06,000
第二句
"""
        segments = parse_subtitle(text, "srt")
        self.assertEqual([s.text for s in segments], ["第一句", "第二句"])
        self.assertEqual(segments[1].start_seconds, 4.0)
        self.assertEqual(segments[1].end_seconds, 6.0)

    def test_ass_parsing(self) -> None:
        text = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\an8}你好\\N世界
"""
        segments = parse_subtitle(text, "ass")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "你好 世界")
        self.assertEqual(segments[0].start_seconds, 1.0)

    def test_bilibili_json_parsing(self) -> None:
        text = json.dumps(
            {
                "font_size": 0.4,
                "body": [
                    {"from": 1.2, "to": 3.4, "content": "第一段"},
                    {"from": 3.5, "to": 5.0, "content": "第二段"},
                ],
            },
            ensure_ascii=False,
        )
        segments = parse_subtitle(text, "json")
        self.assertEqual([s.text for s in segments], ["第一段", "第二段"])
        self.assertEqual(segments[0].start_seconds, 1.2)

    def test_youtube_json3_parsing(self) -> None:
        text = json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 1000,
                        "dDurationMs": 2000,
                        "segs": [{"utf8": "hello "}, {"utf8": "world"}],
                    },
                    {"tStartMs": 4000, "dDurationMs": 1000, "segs": [{"utf8": "next"}]},
                ]
            }
        )
        segments = parse_subtitle(text, "json3")
        self.assertEqual([s.text for s in segments], ["hello world", "next"])
        self.assertEqual(segments[0].start_seconds, 1.0)

    def test_blocks_and_chars(self) -> None:
        segments = [
            TranscriptSegment(start_seconds=0, end_seconds=1, text="a" * 300),
            TranscriptSegment(start_seconds=1, end_seconds=2, text="b" * 300),
            TranscriptSegment(start_seconds=2, end_seconds=3, text="c" * 300),
        ]
        blocks = segments_to_blocks(segments, max_chars=500)
        self.assertGreaterEqual(len(blocks), 2)
        self.assertEqual(transcript_chars(segments), 900)


class SubtitlePickTests(unittest.TestCase):
    def test_excludes_danmaku(self) -> None:
        info = {
            "subtitles": {"danmaku": [{"ext": "xml", "url": "https://example.com/a.xml"}]},
            "automatic_captions": {},
        }
        self.assertIsNone(pick_subtitle(info))

    def test_prefers_manual_chinese(self) -> None:
        info = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]
            },
            "automatic_captions": {
                "en": [{"ext": "vtt", "url": "https://example.com/auto.vtt"}]
            },
        }
        picked = pick_subtitle(info)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked[0], "zh-Hans")
        self.assertEqual(picked[1]["url"], "https://example.com/manual.vtt")

    def test_prefers_chinese_auto_over_english_manual(self) -> None:
        info = {
            "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/en.vtt"}]},
            "automatic_captions": {
                "zh-Hans": [{"ext": "vtt", "url": "https://example.com/zh.vtt"}]
            },
        }
        picked = pick_subtitle(info)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked[0], "zh-Hans")

    def test_ignores_unsupported_extension(self) -> None:
        info = {
            "subtitles": {
                "zh-Hans": [{"ext": "xml", "url": "https://example.com/a.xml"}]
            }
        }
        self.assertIsNone(pick_subtitle(info))


if __name__ == "__main__":
    unittest.main()
