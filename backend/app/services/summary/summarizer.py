from __future__ import annotations

import logging
from typing import Any, Callable

from pydantic import ValidationError

from app.services.summary.deepseek import DeepSeekClient, parse_json_object
from app.services.summary.errors import SummaryError
from app.services.summary.markdown import build_markdown
from app.services.summary.prompts import (
    SYSTEM_PROMPT,
    build_correction_message,
    build_user_prompt,
)
from app.services.summary.schemas import (
    MindmapNode,
    SummaryChapter,
    SummaryConcept,
    SummaryKeyPoint,
    SummaryPayload,
    TranscriptResult,
)
from app.services.summary.settings import SummarySettings
from app.services.summary.subtitles import segments_to_blocks, transcript_chars

logger = logging.getLogger("vds.summary.pipeline")

ProgressCallback = Callable[[str], None]


def _clamp(value: Any, duration: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if duration and duration > 0:
        number = min(number, float(duration))
    return round(max(0.0, number), 2)


def _snap(value: Any, duration: float | None, allowed: list[float] | None) -> float | None:
    """把模型给出的时间戳吸附到逐字稿真实出现过的标记上。"""
    clamped = _clamp(value, duration)
    if clamped is None or not allowed:
        return clamped
    return min(allowed, key=lambda item: abs(item - clamped))


def _transcript_blocks(transcript: TranscriptResult) -> list[tuple[float, str]]:
    """ASR 每个分片单独成块，保留分片起点；字幕按长度合并。"""
    if transcript.source == "asr":
        return [
            (float(segment.start_seconds), segment.text.strip())
            for segment in transcript.segments
            if segment.text.strip()
        ]
    return segments_to_blocks(transcript.segments)


def _clean_text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _dedupe_strings(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _clean_mindmap(node: MindmapNode | None, depth: int, budget: list[int]) -> MindmapNode | None:
    if node is None or depth > 2 or budget[0] <= 0:
        return None
    title = _clean_text(node.title, 120)
    if not title:
        return None
    budget[0] -= 1
    children: list[MindmapNode] = []
    for child in node.children[:10]:
        cleaned = _clean_mindmap(child, depth + 1, budget)
        if cleaned is not None:
            children.append(cleaned)
        if budget[0] <= 0:
            break
    return MindmapNode(title=title, children=children)


def _fallback_mindmap(title: str, chapters: list[SummaryChapter]) -> MindmapNode:
    children: list[MindmapNode] = []
    for chapter in chapters[:8]:
        points = [
            MindmapNode(title=point[:80])
            for point in chapter.key_points[:4]
            if point.strip()
        ]
        children.append(
            MindmapNode(
                title=chapter.title.strip() or "未命名章节",
                children=points,
            )
        )
    return MindmapNode(title=title.strip() or "视频主题", children=children)


def normalize_payload(
    payload: SummaryPayload,
    *,
    duration: float | None,
    title: str,
    allowed_starts: list[float] | None = None,
) -> SummaryPayload:
    """对模型输出做服务端归一化，不信任其时间戳与数量。"""
    tldr = _clean_text(payload.tldr, 200)
    overview = _clean_text(payload.overview, 1200)
    if not tldr and overview:
        tldr = overview[:80]
    if not overview and tldr:
        overview = tldr
    if not tldr and not overview:
        raise SummaryError("AI 返回的总结内容为空")

    keywords = _dedupe_strings([_clean_text(item, 40) for item in payload.keywords], 10)

    chapters: list[SummaryChapter] = []
    seen_titles: set[str] = set()
    for raw in payload.chapters:
        chapter_title = _clean_text(raw.title, 120)
        if not chapter_title or chapter_title in seen_titles:
            continue
        seen_titles.add(chapter_title)
        start = _snap(raw.start_seconds, duration, allowed_starts) or 0.0
        end = _clamp(raw.end_seconds, duration)
        if end is not None and end <= start:
            end = None
        chapters.append(
            SummaryChapter(
                start_seconds=start,
                end_seconds=end,
                title=chapter_title,
                summary=_clean_text(raw.summary, 1000),
                key_points=_dedupe_strings(
                    [_clean_text(point, 300) for point in raw.key_points], 6
                ),
            )
        )
    chapters.sort(key=lambda chapter: chapter.start_seconds)
    chapters = chapters[:12]
    if not chapters:
        chapters = [
            SummaryChapter(
                start_seconds=0.0,
                end_seconds=float(duration) if duration else None,
                title="内容概览",
                summary=overview,
                key_points=[],
            )
        ]

    key_points: list[SummaryKeyPoint] = []
    seen_points: set[tuple[str, str]] = set()
    for raw in payload.key_points:
        point_title = _clean_text(raw.title, 120)
        detail = _clean_text(raw.detail, 1000)
        if not point_title and detail:
            point_title = detail[:40]
        if not point_title and not detail:
            continue
        marker = (point_title, detail)
        if marker in seen_points:
            continue
        seen_points.add(marker)
        key_points.append(
            SummaryKeyPoint(
                title=point_title,
                detail=detail,
                timestamp_seconds=_snap(
                    raw.timestamp_seconds, duration, allowed_starts
                ),
            )
        )
        if len(key_points) >= 12:
            break
    if not key_points:
        for chapter in chapters:
            for point in chapter.key_points:
                key_points.append(
                    SummaryKeyPoint(
                        title=point[:40],
                        detail=point,
                        timestamp_seconds=chapter.start_seconds,
                    )
                )
                if len(key_points) >= 8:
                    break
            if len(key_points) >= 8:
                break

    concepts: list[SummaryConcept] = []
    seen_terms: set[str] = set()
    for raw in payload.concepts:
        term = _clean_text(raw.term, 80)
        if not term or term in seen_terms:
            continue
        seen_terms.add(term)
        concepts.append(
            SummaryConcept(term=term, explanation=_clean_text(raw.explanation, 500))
        )
        if len(concepts) >= 8:
            break

    budget = [40]
    mindmap = _clean_mindmap(payload.mindmap, 0, budget)
    if mindmap is None or not mindmap.children:
        mindmap = _fallback_mindmap(title, chapters)

    return SummaryPayload(
        tldr=tldr,
        overview=overview,
        keywords=keywords,
        chapters=chapters,
        key_points=key_points,
        concepts=concepts,
        mindmap=mindmap,
        markdown="",
    )


async def summarize(
    client: DeepSeekClient,
    normalized: dict[str, Any],
    transcript: TranscriptResult,
    settings: SummarySettings,
    progress_callback: ProgressCallback | None = None,
) -> tuple[SummaryPayload, dict[str, Any]]:
    chars = transcript_chars(transcript.segments)
    if chars <= 0:
        raise SummaryError("逐字稿为空，无法生成总结")
    if chars > settings.summary_max_transcript_chars:
        raise SummaryError(
            f"逐字稿过长（{chars} 字），超过当前上限 "
            f"{settings.summary_max_transcript_chars} 字；请缩短视频或调高环境变量"
        )

    blocks = _transcript_blocks(transcript)
    if not blocks:
        raise SummaryError("逐字稿为空，无法生成总结")
    allowed_starts = sorted({0.0, *(round(start, 2) for start, _ in blocks)})

    title = str(normalized.get("title") or "未知标题")
    meta = {
        "title": title,
        "uploader": normalized.get("uploader"),
        "platform": normalized.get("platform"),
        "duration": normalized.get("duration"),
        "url": normalized.get("url"),
        "transcript_source": transcript.source,
        "model": settings.deepseek_model,
    }
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_prompt(
                meta,
                blocks,
                transcript_source=transcript.source,
                language=transcript.language,
            ),
        },
    ]

    max_tokens = 6000
    last_error: Exception | None = None
    usage: dict[str, Any] = {}
    for attempt in range(2):
        if progress_callback is not None:
            try:
                progress_callback("正在生成结构化总结…")
            except Exception:  # pragma: no cover - 进度回调不应影响主流程
                pass
        content, response_meta = await client.chat_json(messages, max_tokens=max_tokens)
        usage = response_meta
        if response_meta.get("finish_reason") == "length" and attempt == 0:
            max_tokens = 8000
            continue
        try:
            raw = parse_json_object(content)
            payload = SummaryPayload.model_validate(raw)
            payload = normalize_payload(
                payload,
                duration=normalized.get("duration"),
                title=title,
                allowed_starts=allowed_starts,
            )
            payload.markdown = build_markdown(payload, meta)
            return payload, usage
        except (ValueError, ValidationError, SummaryError) as exc:
            last_error = exc
            if attempt == 0:
                messages = [*messages, build_correction_message(str(exc)[:300])]
                continue
            break

    logger.warning("总结 JSON 解析失败：%s", last_error)
    raise SummaryError("AI 返回的总结格式不正确，请重试") from last_error
