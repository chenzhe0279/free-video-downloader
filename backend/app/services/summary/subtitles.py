from __future__ import annotations

import html
import json
import re
from typing import Any

from app.services.summary.schemas import TranscriptSegment

# 扩展名优先级：越低越优先
_SUPPORTED_EXTENSIONS = {"vtt": 0, "srt": 1, "ass": 2, "json3": 3, "json": 4}
# 弹幕、直播聊天等不是语音内容
_EXCLUDED_LANGUAGES = {"danmaku", "live_chat", "chat"}
_LANGUAGE_PRIORITY = (
    "zh-hans",
    "zh-cn",
    "zh",
    "zh-hant",
    "zh-tw",
    "zh-hk",
    "en",
    "ja",
    "ko",
    "es",
    "fr",
    "de",
    "ru",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")


def _language_rank(language: str) -> float:
    lowered = language.lower()
    for index, code in enumerate(_LANGUAGE_PRIORITY):
        if lowered == code:
            return float(index)
    for index, code in enumerate(_LANGUAGE_PRIORITY):
        if lowered.startswith(code + "-") or code.startswith(lowered + "-"):
            return index + 0.5
    return 100.0


def pick_subtitle(info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """从 yt-dlp 原始信息中选择最合适的字幕。

    手动字幕优先于自动字幕；语言优先中文/英文；排除弹幕与直播聊天。
    """
    best: tuple[tuple[float, int, int], str, dict[str, Any]] | None = None
    for key, automatic in (("subtitles", False), ("automatic_captions", True)):
        mapping = info.get(key) or {}
        if not isinstance(mapping, dict):
            continue
        for language, entries in mapping.items():
            if not isinstance(entries, list):
                continue
            language_text = str(language)
            lowered = language_text.lower()
            if lowered in _EXCLUDED_LANGUAGES or "danmaku" in lowered:
                continue
            language_rank = _language_rank(lowered)
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                ext = str(entry.get("ext") or "").lower()
                url = entry.get("url")
                if not url or ext not in _SUPPORTED_EXTENSIONS:
                    continue
                score = (
                    language_rank,
                    0 if not automatic else 1,
                    _SUPPORTED_EXTENSIONS[ext],
                )
                if best is None or score < best[0]:
                    best = (score, language_text, entry)
    if best is None:
        return None
    return best[1], best[2]


def clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = _TAG_RE.sub("", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _to_seconds(raw: str) -> float | None:
    candidate = (raw or "").strip().replace(",", ".")
    if not candidate:
        return None
    parts = candidate.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(candidate)
    except (TypeError, ValueError):
        return None


def _parse_timed_text(text: str) -> list[TranscriptSegment]:
    """解析 VTT / SRT：两种格式的时间戳行都包含 ``-->``。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        left, _, right = line.partition("-->")
        start = _to_seconds(left.strip())
        end_token = right.strip().split(" ")[0] if right.strip() else ""
        end = _to_seconds(end_token)
        index += 1
        body_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            body_lines.append(lines[index].strip())
            index += 1
        body = clean_text(" ".join(body_lines))
        if start is None or not body:
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=max(0.0, start),
                end_seconds=max(0.0, end) if end is not None else None,
                text=body,
            )
        )
    return segments


def _parse_ass(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped.lower().startswith("dialogue:"):
            continue
        payload = stripped.split(":", 1)[1] if ":" in stripped else ""
        parts = payload.split(",", 9)
        if len(parts) < 10:
            continue
        start = _to_seconds(parts[1].strip())
        end = _to_seconds(parts[2].strip())
        body = _ASS_OVERRIDE_RE.sub("", parts[9])
        body = body.replace("\\N", " ").replace("\\n", " ")
        body = clean_text(body)
        if start is None or not body:
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=max(0.0, start),
                end_seconds=max(0.0, end) if end is not None else None,
                text=body,
            )
        )
    return segments


def _parse_bilibili_json(text: str) -> list[TranscriptSegment]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, list):
        return []
    segments: list[TranscriptSegment] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("from") or 0)
            end = float(item.get("to") or 0)
        except (TypeError, ValueError):
            continue
        content = clean_text(str(item.get("content") or ""))
        if not content:
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=max(0.0, start),
                end_seconds=max(0.0, end),
                text=content,
            )
        )
    return segments


def _parse_json3(text: str) -> list[TranscriptSegment]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        return []
    segments: list[TranscriptSegment] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segs = event.get("segs")
        if not isinstance(segs, list):
            continue
        body = clean_text(
            "".join(str(seg.get("utf8") or "") for seg in segs if isinstance(seg, dict))
        )
        if not body:
            continue
        try:
            start = float(event.get("tStartMs") or 0) / 1000
            duration = float(event.get("dDurationMs") or 0) / 1000
        except (TypeError, ValueError):
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=max(0.0, start),
                end_seconds=max(0.0, start + duration) if duration else None,
                text=body,
            )
        )
    return segments


def _dedupe_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """去掉空段、完全重复段，以及 YouTube 滚动字幕的重复前缀。"""
    result: list[TranscriptSegment] = []
    previous_full = ""
    for segment in segments:
        full = clean_text(segment.text)
        if not full:
            continue
        if full == previous_full:
            continue
        text = full
        if previous_full and full.startswith(previous_full):
            text = full[len(previous_full) :].strip()
            if not text:
                previous_full = full
                continue
        result.append(
            TranscriptSegment(
                start_seconds=max(0.0, float(segment.start_seconds or 0)),
                end_seconds=segment.end_seconds,
                text=text,
            )
        )
        previous_full = full
    return result


def parse_subtitle(text: str, ext: str) -> list[TranscriptSegment]:
    suffix = (ext or "").lower().lstrip(".")
    if suffix in {"vtt", "srt"}:
        segments = _parse_timed_text(text)
    elif suffix == "ass":
        segments = _parse_ass(text)
    elif suffix == "json3":
        segments = _parse_json3(text)
    elif suffix == "json":
        segments = _parse_bilibili_json(text)
    else:
        segments = []
    return _dedupe_segments(segments)


def segments_to_blocks(
    segments: list[TranscriptSegment],
    max_chars: int = 800,
) -> list[tuple[float, str]]:
    """把短字幕合并成带起始时间的长段落，减少 prompt 碎片。"""
    blocks: list[tuple[float, str]] = []
    current_start: float | None = None
    current_parts: list[str] = []
    current_length = 0
    previous_end: float | None = None

    def flush() -> None:
        nonlocal current_start, current_parts, current_length
        if current_start is not None and current_parts:
            blocks.append((current_start, " ".join(current_parts).strip()))
        current_start = None
        current_parts = []
        current_length = 0

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        gap = (
            segment.start_seconds - previous_end
            if previous_end is not None
            else 0
        )
        if current_start is None:
            current_start = segment.start_seconds
        elif gap > 30 or current_length + len(text) > max_chars:
            flush()
            current_start = segment.start_seconds
        current_parts.append(text)
        current_length += len(text) + 1
        if segment.end_seconds is not None:
            previous_end = segment.end_seconds
        else:
            previous_end = segment.start_seconds
    flush()
    return blocks


def transcript_chars(segments: list[TranscriptSegment]) -> int:
    return sum(len(segment.text) for segment in segments)
