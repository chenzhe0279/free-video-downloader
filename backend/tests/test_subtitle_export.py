from __future__ import annotations

import time
import unittest
from urllib.parse import unquote

import httpx
from fastapi import FastAPI

from app.api.summary import router
from app.services.summary import exporters
from app.services.summary.schemas import TranscriptSegment
from app.services.summary.tasks import SummaryTask, summary_manager

_URL = "https://www.bilibili.com/video/BV1s18cziEtw"


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(start_seconds=0, end_seconds=2.5, text="第一句话"),
        TranscriptSegment(start_seconds=65.25, end_seconds=70, text="第二句话"),
    ]


def _task(**overrides) -> SummaryTask:
    values: dict = {
        "id": "task-subtitle",
        "url": _URL,
        "client_ip": "127.0.0.1",
        "title": "测试视频",
        "duration": 120.0,
        "status": "finished",
        "stage": "已完成",
        "progress": 100.0,
        "transcript_source": "subtitle",
        "transcript_language": "zh-CN",
        "segments": _segments(),
        "finished_at": time.time(),
    }
    values.update(overrides)
    return SummaryTask(**values)


def _disposition_parts(disposition: str) -> tuple[str, str]:
    fallback = disposition.split('filename="', 1)[1].split('"', 1)[0]
    encoded = disposition.split("filename*=UTF-8''", 1)[1]
    return fallback, encoded


class SubtitleExporterTests(unittest.TestCase):
    # ---- SRT / VTT ----
    def test_srt_timestamps_sequence_and_blank_lines(self) -> None:
        body = exporters.to_srt(_segments(), 120)
        self.assertEqual(
            body,
            "1\n00:00:00,000 --> 00:00:02,500\n第一句话\n\n"
            "2\n00:01:05,250 --> 00:01:10,000\n第二句话\n",
        )

    def test_vtt_header_and_timestamps(self) -> None:
        body = exporters.to_vtt(_segments(), 120)
        self.assertTrue(body.startswith("WEBVTT\n\n"))
        self.assertEqual(
            body,
            "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.500\n第一句话\n\n"
            "2\n00:01:05.250 --> 00:01:10.000\n第二句话\n",
        )
        self.assertNotIn(",000 -->", body)

    def test_empty_segments_render_empty_files(self) -> None:
        self.assertEqual(exporters.to_srt([], None), "")
        self.assertEqual(exporters.to_txt([]), "")
        self.assertEqual(exporters.to_vtt([], None), "WEBVTT\n\n")

    # ---- 时间补齐规则 ----
    def test_end_falls_back_to_next_start(self) -> None:
        cues = exporters.prepare_cues(
            [
                TranscriptSegment(start_seconds=0, text="一"),
                TranscriptSegment(start_seconds=4.25, text="二"),
                TranscriptSegment(start_seconds=12, text="三"),
            ]
        )
        self.assertEqual([cue.end for cue in cues], [4.25, 12.0, 15.0])
        body = exporters.to_srt(
            [TranscriptSegment(start_seconds=0, text="一")], None
        )
        self.assertIn("00:00:00,000 --> 00:00:03,000", body)

    def test_last_segment_uses_three_seconds(self) -> None:
        cues = exporters.prepare_cues([TranscriptSegment(start_seconds=10, text="最后")])
        self.assertEqual(cues[0].start, 10.0)
        self.assertEqual(cues[0].end, 13.0)

    def test_duration_clamps_end(self) -> None:
        cues = exporters.prepare_cues(
            [TranscriptSegment(start_seconds=0, end_seconds=999, text="超长")], 60
        )
        self.assertEqual(cues[0].end, 60.0)

        cues = exporters.prepare_cues(
            [TranscriptSegment(start_seconds=58, text="尾段")], 60
        )
        self.assertEqual(cues[0].end, 60.0)

    def test_end_never_collapses_below_start(self) -> None:
        cues = exporters.prepare_cues(
            [TranscriptSegment(start_seconds=59.8, end_seconds=59.9, text="边界")], 59.8
        )
        self.assertGreater(cues[0].end, cues[0].start)
        self.assertGreaterEqual(cues[0].end - cues[0].start, 0.5)

    def test_invalid_end_is_ignored(self) -> None:
        cues = exporters.prepare_cues(
            [
                TranscriptSegment(start_seconds=5, end_seconds=5, text="相等"),
                TranscriptSegment(start_seconds=10, end_seconds=8, text="倒序"),
            ]
        )
        self.assertEqual([cue.end for cue in cues], [10.0, 13.0])

    def test_empty_text_filtered(self) -> None:
        cues = exporters.prepare_cues(
            [
                TranscriptSegment(start_seconds=0, end_seconds=1, text=""),
                TranscriptSegment(start_seconds=1, end_seconds=2, text="  \n\t "),
                TranscriptSegment(start_seconds=3, end_seconds=5, text=" 有效内容 "),
            ]
        )
        self.assertEqual([cue.text for cue in cues], ["有效内容"])
        body = exporters.to_srt(
            [
                TranscriptSegment(start_seconds=0, end_seconds=1, text=""),
                TranscriptSegment(start_seconds=3, end_seconds=5, text="有效内容"),
            ],
            None,
        )
        self.assertEqual(body, "1\n00:00:03,000 --> 00:00:05,000\n有效内容\n")

    def test_filtered_empty_segment_not_used_as_next_start(self) -> None:
        cues = exporters.prepare_cues(
            [
                TranscriptSegment(start_seconds=0, text="一"),
                TranscriptSegment(start_seconds=5, text=""),
                TranscriptSegment(start_seconds=8, text="三"),
            ]
        )
        self.assertEqual(
            [(cue.start, cue.end) for cue in cues],
            [(0.0, 8.0), (8.0, 11.0)],
        )

    def test_multiline_text_collapsed(self) -> None:
        cues = exporters.prepare_cues(
            [
                TranscriptSegment(
                    start_seconds=0, end_seconds=1, text="第一行\n第二行\r\n第三行"
                )
            ]
        )
        self.assertEqual(cues[0].text, "第一行 第二行 第三行")

    # ---- TXT / MD ----
    def test_txt_has_no_timestamps(self) -> None:
        body = exporters.to_txt(_segments())
        self.assertEqual(body, "第一句话\n第二句话\n")
        self.assertNotIn("-->", body)
        self.assertNotIn("00:00", body)

    def test_markdown_metadata_and_timestamps(self) -> None:
        body = exporters.to_markdown(
            _segments(),
            title="测试视频",
            source="subtitle",
            language="zh-CN",
            duration=120,
        )
        self.assertTrue(body.startswith("# 测试视频 · 字幕\n"))
        self.assertIn("> 来源：平台字幕 · 语言：zh-CN · 共 2 段", body)
        self.assertIn("毫秒级", body)
        self.assertIn("## 字幕", body)
        self.assertIn("- [00:00] 第一句话", body)
        self.assertIn("- [01:05] 第二句话", body)
        self.assertIn("仅供学习参考", body)

    def test_markdown_asr_labels_and_fallbacks(self) -> None:
        body = exporters.to_markdown(
            [TranscriptSegment(start_seconds=0, end_seconds=60, text="一整个分片")],
            title="",
            source="asr",
            language=None,
            duration=None,
        )
        self.assertTrue(body.startswith("# 视频 · 字幕\n"))
        self.assertIn("AI语音识别", body)
        self.assertIn("自动识别", body)
        self.assertIn("约 1 分钟", body)
        self.assertIn("- [00:00] 一整个分片", body)

    # ---- 文件名 ----
    def test_filename_contains_label_and_extension(self) -> None:
        task = _task(title="测试视频", transcript_source="subtitle")
        self.assertEqual(
            exporters.subtitle_filename(task, "srt"),
            "测试视频-字幕-平台字幕.srt",
        )
        self.assertEqual(
            exporters.subtitle_filename(task, ".vtt"),
            "测试视频-字幕-平台字幕.vtt",
        )
        task.transcript_source = "asr"
        name = exporters.subtitle_filename(task, "md")
        self.assertIn("字幕", name)
        self.assertEqual(name, "测试视频-字幕-AI语音识别.md")
        self.assertTrue(name.endswith(".md"))

    def test_filename_empty_title_falls_back(self) -> None:
        task = _task(title="")
        self.assertEqual(
            exporters.subtitle_filename(task, "srt"),
            "视频-字幕-平台字幕.srt",
        )

    def test_filename_length_respects_safe_filename_limit(self) -> None:
        task = _task(title="超长标题" * 60)
        name = exporters.subtitle_filename(task, "srt")
        self.assertEqual(len(name), 120)
        self.assertTrue(name.endswith("-字幕-平台字幕.srt"))

    def test_chinese_filename_and_ascii_fallback(self) -> None:
        task = _task(title="中文标题/带<非法>字符")
        filename = exporters.subtitle_filename(task, "srt")
        self.assertEqual(filename, "中文标题_带_非法_字符-字幕-平台字幕.srt")

        disposition = exporters.content_disposition(filename)
        self.assertTrue(disposition.startswith("attachment; "))
        fallback, encoded = _disposition_parts(disposition)
        self.assertEqual(fallback, "subtitles.srt")
        self.assertTrue(fallback.isascii())
        self.assertNotIn("字幕", encoded)
        self.assertNotIn(" ", encoded)
        self.assertEqual(unquote(encoded), filename)

    def test_ascii_fallback_keeps_latin_words(self) -> None:
        filename = "Python 教程-字幕-AI语音识别.srt"
        fallback = exporters.ascii_filename(filename)
        self.assertTrue(fallback.isascii())
        self.assertTrue(fallback.endswith(".srt"))
        self.assertIn("Python", fallback)


class SubtitleApiTests(unittest.IsolatedAsyncioTestCase):
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

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        summary_manager._tasks.clear()
        summary_manager._per_ip.clear()
        summary_manager._daily.clear()
        summary_manager._cache.clear()

    async def test_download_all_formats(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        expectations = {
            "srt": (
                "text/plain; charset=utf-8",
                "1\n00:00:00,000 --> 00:00:02,500\n第一句话",
            ),
            "vtt": (
                "text/plain; charset=utf-8",
                "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.500",
            ),
            "txt": ("text/plain; charset=utf-8", "第一句话\n第二句话\n"),
            "md": ("text/markdown; charset=utf-8", "# 测试视频 · 字幕"),
        }
        for fmt, (media_type, marker) in expectations.items():
            with self.subTest(format=fmt):
                response = await self.client.get(
                    f"/api/summary/{task.id}/subtitles?format={fmt}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], media_type)
                self.assertEqual(response.headers["cache-control"], "no-store")
                disposition = response.headers["content-disposition"]
                self.assertTrue(disposition.startswith("attachment; "))
                self.assertIn("filename*=UTF-8''", disposition)
                fallback, encoded = _disposition_parts(disposition)
                self.assertTrue(fallback.isascii())
                self.assertTrue(fallback.endswith(f".{fmt}"))
                self.assertEqual(unquote(encoded), exporters.subtitle_filename(task, fmt))
                self.assertIn(marker, response.text)

    async def test_default_format_is_srt(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        response = await self.client.get(f"/api/summary/{task.id}/subtitles")
        self.assertEqual(response.status_code, 200)
        self.assertIn("-->", response.text)
        self.assertNotIn("WEBVTT", response.text)
        self.assertTrue(response.headers["content-disposition"].startswith("attachment; "))
        fallback, _ = _disposition_parts(response.headers["content-disposition"])
        self.assertEqual(fallback, "subtitles.srt")

    async def test_missing_task_returns_404(self) -> None:
        response = await self.client.get("/api/summary/not-found/subtitles")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "总结任务不存在或已过期")

    async def test_empty_segments_returns_409(self) -> None:
        task = _task(segments=[])
        summary_manager._tasks[task.id] = task
        response = await self.client.get(f"/api/summary/{task.id}/subtitles")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "字幕尚未生成，请等待总结完成")

    async def test_blank_segments_returns_409(self) -> None:
        task = _task(
            segments=[TranscriptSegment(start_seconds=0, text="  \n ")]
        )
        summary_manager._tasks[task.id] = task
        response = await self.client.get(
            f"/api/summary/{task.id}/subtitles?format=md"
        )
        self.assertEqual(response.status_code, 409)

    async def test_invalid_format_returns_422(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        for fmt in ("ass", "SRT", "json", ""):
            with self.subTest(format=fmt):
                response = await self.client.get(
                    f"/api/summary/{task.id}/subtitles?format={fmt}"
                )
                self.assertEqual(response.status_code, 422)

    async def test_asr_markdown_labels(self) -> None:
        task = _task(transcript_source="asr", transcript_language=None)
        summary_manager._tasks[task.id] = task
        response = await self.client.get(
            f"/api/summary/{task.id}/subtitles?format=md"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/markdown; charset=utf-8")
        self.assertIn("AI语音识别", response.text)
        self.assertIn("自动识别", response.text)
        self.assertIn("约 1 分钟", response.text)
        _, encoded = _disposition_parts(response.headers["content-disposition"])
        self.assertEqual(unquote(encoded), "测试视频-字幕-AI语音识别.md")

    async def test_download_does_not_consume_quota_or_extend_ttl(self) -> None:
        task = _task()
        summary_manager._tasks[task.id] = task
        before = (task.finished_at, task.ttl_seconds, task.status, task.progress)
        await self.client.get(f"/api/summary/{task.id}/subtitles?format=vtt")
        await self.client.get(f"/api/summary/{task.id}/subtitles?format=md")
        self.assertEqual(
            (task.finished_at, task.ttl_seconds, task.status, task.progress),
            before,
        )
        self.assertEqual(summary_manager._daily, {})
        self.assertEqual(summary_manager._per_ip, {})
        self.assertIs(summary_manager.get(task.id), task)


if __name__ == "__main__":
    unittest.main()
