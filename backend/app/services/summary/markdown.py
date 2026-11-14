from __future__ import annotations

import re
from typing import Any

from app.services.summary.prompts import format_timestamp
from app.services.summary.schemas import MindmapNode, SummaryPayload

# AI 输出是“文本”，不能直接当 Markdown 语法使用：先把换行折叠成空格，
# 再转义会破坏结构或制造链接的特殊字符。
_WHITESPACE_RE = re.compile(r"\s+")
_MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]<>|])")


def _inline(value: Any) -> str:
    """把一段 AI 文本变成安全的单行 Markdown 行内文本。"""
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def _code_span(value: Any) -> str:
    """关键词放进行内代码，代码内部的字符无需再转义；反引号替换为单引号。"""
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip().replace("`", "'")
    return f"`{text}`" if text else ""


def _timestamp_link(seconds: float | None) -> str:
    """生成可被前端识别的 ``[mm:ss](#t=秒)`` 链接；无时间戳时返回空串。"""
    if seconds is None:
        return ""
    try:
        value = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return ""
    return f"[{format_timestamp(value)}](#t={int(value)})"


def _render_mindmap(node: MindmapNode | None, depth: int = 0) -> list[str]:
    if node is None or not node.title.strip():
        return []
    lines = [f"{'  ' * depth}- {_inline(node.title)}"]
    for child in node.children[:12]:
        lines.extend(_render_mindmap(child, depth + 1))
    return lines


def build_markdown(payload: SummaryPayload, meta: dict[str, Any]) -> str:
    title = _inline(meta.get("title") or "视频总结")
    platform = _inline(meta.get("platform") or "")
    uploader = _inline(meta.get("uploader") or "")
    duration = meta.get("duration")
    url = str(meta.get("url") or "").strip()
    source = "平台字幕" if meta.get("transcript_source") == "subtitle" else "AI 语音识别"
    model = str(meta.get("model") or "deepseek-flash")

    header_bits = [bit for bit in (platform, uploader) if bit]
    if duration:
        header_bits.append(f"时长 {format_timestamp(float(duration))}")
    lines: list[str] = [f"# {title}", ""]
    if header_bits:
        lines.append(f"> {' · '.join(header_bits)}")
    if url:
        lines.append(f"> 原视频：{url}")
    lines.append("")

    if payload.tldr.strip():
        lines.extend(["## 一句话总结", "", _inline(payload.tldr), ""])
    if payload.overview.strip():
        lines.extend(["## 内容概述", "", _inline(payload.overview), ""])

    keywords = [_code_span(item) for item in payload.keywords if item and item.strip()]
    if keywords:
        lines.extend(["## 关键词", "", " ".join(keywords), ""])

    if payload.chapters:
        lines.extend(["## 章节大纲", ""])
        for chapter in payload.chapters:
            stamp = _timestamp_link(chapter.start_seconds)
            heading = _inline(chapter.title.strip() or "未命名章节")
            lines.append(f"### {stamp} {heading}".rstrip())
            if chapter.summary.strip():
                lines.extend(["", _inline(chapter.summary)])
            if chapter.key_points:
                lines.append("")
                for point in chapter.key_points:
                    point_text = _inline(point)
                    if point_text:
                        lines.append(f"- {point_text}")
            lines.append("")

    if payload.key_points:
        lines.extend(["## 核心要点", ""])
        for index, point in enumerate(payload.key_points, start=1):
            point_title = _inline(point.title.strip() or f"要点 {index}")
            stamp = _timestamp_link(point.timestamp_seconds)
            suffix = f" {stamp}" if stamp else ""
            lines.append(f"{index}. **{point_title}**{suffix}")
            detail = _inline(point.detail)
            if detail:
                lines.append(f"   {detail}")
        lines.append("")

    if payload.concepts:
        lines.extend(["## 关键概念", ""])
        for concept in payload.concepts:
            term = _inline(concept.term.strip())
            explanation = _inline(concept.explanation)
            if term:
                lines.append(f"- **{term}**：{explanation}")
        lines.append("")

    mindmap_lines = _render_mindmap(payload.mindmap)
    if mindmap_lines:
        lines.extend(["## 思维导图", "", *mindmap_lines, ""])

    lines.extend(
        [
            "---",
            "",
            f"> 本笔记由万能视频下载站 AI 视频总结自动生成（{model}，逐字稿来源：{source}）。",
            "> AI 生成内容可能存在偏差，请结合原视频核对；仅用于学习与个人研究。",
            "",
        ]
    )
    return "\n".join(lines)
