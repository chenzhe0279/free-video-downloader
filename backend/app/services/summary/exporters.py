"""字幕文件导出：把总结任务里的 ``segments`` 渲染成 SRT / VTT / TXT / Markdown。

纯内存计算，不下载、不调用模型、不消耗额度；所有时间只做格式化与补齐，
不伪造比原始分段更细的粒度（ASR 分片通常约 1 分钟）。
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import quote

from app.services.summary.prompts import format_timestamp
from app.utils import MAX_FILENAME_LENGTH, safe_filename

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注，避免运行期循环导入
    from app.services.summary.schemas import TranscriptSegment
    from app.services.summary.tasks import SummaryTask

SUBTITLE_FORMATS: tuple[str, ...] = ("srt", "vtt", "txt", "md")

SOURCE_LABELS: dict[str, str] = {
    "subtitle": "平台字幕",
    "asr": "AI语音识别",
}

MEDIA_TYPES: dict[str, str] = {
    "srt": "text/plain; charset=utf-8",
    "vtt": "text/plain; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}

DEFAULT_LAST_SECONDS = 3.0
MIN_SEGMENT_SECONDS = 0.5
DEFAULT_TITLE = "视频"

_WHITESPACE_RE = re.compile(r"\s+")
_ASCII_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")
_EXT_UNSAFE_RE = re.compile(r"[^a-z0-9]+")


class Cue(NamedTuple):
    """补齐后的单条字幕时间轴。"""

    start: float
    end: float
    text: str


def _field(segment: Any, name: str, default: Any = None) -> Any:
    if isinstance(segment, dict):
        return segment.get(name, default)
    return getattr(segment, name, default)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _inline(value: Any) -> str:
    """字幕文本单行化：换行折叠为空格，避免破坏 SRT/VTT/MD 结构。"""
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def source_label(source: str | None) -> str:
    return SOURCE_LABELS.get(str(source or ""), SOURCE_LABELS["asr"])


def valid_duration(duration: Any) -> float | None:
    value = _number(duration, 0.0)
    return value if value > 0 else None


def prepare_cues(
    segments: list[TranscriptSegment] | None,
    duration: float | None = None,
) -> list[Cue]:
    """过滤空文本并补齐每条字幕的结束时间。

    结束时间优先级：``end_seconds``（有效时）→ 下一段起点 → ``start + 3s``；
    随后被 ``duration`` 截断，并保证 ``end >= start + 0.5``。
    """
    items: list[tuple[float, float | None, str]] = []
    for segment in segments or []:
        text = _inline(_field(segment, "text", ""))
        if not text:
            continue
        start = max(0.0, _number(_field(segment, "start_seconds", 0.0)))
        raw_end = _field(segment, "end_seconds", None)
        end: float | None = None
        if raw_end is not None:
            candidate = _number(raw_end, 0.0)
            if candidate > start:
                end = candidate
        items.append((start, end, text))

    limit = valid_duration(duration)
    cues: list[Cue] = []
    for index, (start, end, text) in enumerate(items):
        if end is None and index + 1 < len(items):
            next_start = items[index + 1][0]
            if next_start > start:
                end = next_start
        if end is None:
            end = start + DEFAULT_LAST_SECONDS
        if limit is not None:
            end = min(end, limit)
        end = max(end, start + MIN_SEGMENT_SECONDS)
        cues.append(Cue(start=start, end=end, text=text))
    return cues


def _clock(seconds: float, separator: str = ",") -> str:
    total_ms = max(0, int(round(_number(seconds, 0.0) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _cues_block(
    segments: list[TranscriptSegment] | None,
    duration: float | None,
    separator: str,
) -> list[str]:
    blocks: list[str] = []
    for index, cue in enumerate(prepare_cues(segments, duration), start=1):
        start = _clock(cue.start, separator)
        end = _clock(cue.end, separator)
        blocks.append(f"{index}\n{start} --> {end}\n{cue.text}")
    return blocks


def to_srt(
    segments: list[TranscriptSegment] | None,
    duration: float | None = None,
) -> str:
    blocks = _cues_block(segments, duration, ",")
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def to_vtt(
    segments: list[TranscriptSegment] | None,
    duration: float | None = None,
) -> str:
    blocks = _cues_block(segments, duration, ".")
    if not blocks:
        return "WEBVTT\n\n"
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def to_txt(segments: list[TranscriptSegment] | None) -> str:
    lines = [cue.text for cue in prepare_cues(segments)]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def to_markdown(
    segments: list[TranscriptSegment] | None,
    *,
    title: str = "",
    source: str | None = None,
    language: str | None = None,
    duration: float | None = None,
) -> str:
    cues = prepare_cues(segments, duration)
    heading = _inline(title) or DEFAULT_TITLE
    label = source_label(source)
    language_text = _inline(language) or "自动识别"
    if source == "subtitle":
        precision = "毫秒级（保留平台原始时间轴）"
    else:
        precision = "约 1 分钟（按音频分片，非逐词时间轴）"

    lines: list[str] = [
        f"# {heading} · 字幕",
        "",
        (
            f"> 来源：{label} · 语言：{language_text} · 共 {len(cues)} 段"
            f" · 时间戳精度：{precision}"
        ),
        "",
        "## 字幕",
        "",
    ]
    lines.extend(f"- [{format_timestamp(cue.start)}] {cue.text}" for cue in cues)
    lines.extend(
        [
            "",
            "---",
            "",
            "> 本字幕由 AI 总结任务自动生成，仅供学习参考，可能存在识别或断句误差。",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_ext(ext: str | None) -> str:
    cleaned = _EXT_UNSAFE_RE.sub("", str(ext or "").lstrip(".").lower())
    return cleaned or "srt"


def subtitle_filename(task: SummaryTask, ext: str) -> str:
    """``{标题}-字幕-{平台字幕|AI语音识别}.{ext}``，总长不超过 120 字符。"""
    suffix_ext = _normalize_ext(ext)
    label = source_label(getattr(task, "transcript_source", None))
    suffix = f"-字幕-{label}.{suffix_ext}"
    title = safe_filename(
        str(getattr(task, "title", "") or ""),
        fallback=DEFAULT_TITLE,
    )
    budget = max(1, MAX_FILENAME_LENGTH - len(suffix))
    stem = title[:budget].strip(" .") or DEFAULT_TITLE
    return f"{stem}{suffix}"


def ascii_filename(filename: str) -> str:
    """生成 ``Content-Disposition: filename=`` 的纯 ASCII 兜底文件名。"""
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    cleaned = _MULTI_UNDERSCORE_RE.sub("_", _ASCII_UNSAFE_RE.sub("_", stem))
    cleaned = cleaned.strip(" ._-") or "subtitles"
    return f"{cleaned}.{ext}" if ext else cleaned


def content_disposition(filename: str) -> str:
    """RFC 6266 / RFC 5987：ASCII 兜底 + ``filename*`` 携带 UTF-8 原名。"""
    fallback = ascii_filename(filename)
    encoded = quote(filename, safe="")
    return (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{encoded}"
    )


__all__ = [
    "Cue",
    "DEFAULT_LAST_SECONDS",
    "MEDIA_TYPES",
    "MIN_SEGMENT_SECONDS",
    "SOURCE_LABELS",
    "SUBTITLE_FORMATS",
    "ascii_filename",
    "content_disposition",
    "prepare_cues",
    "source_label",
    "subtitle_filename",
    "to_markdown",
    "to_srt",
    "to_txt",
    "to_vtt",
    "valid_duration",
]
