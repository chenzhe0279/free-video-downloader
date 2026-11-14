from __future__ import annotations

from typing import Any

from app.services.summary.prompts import format_timestamp
from app.services.summary.schemas import MindmapNode, SummaryPayload


def _render_mindmap(node: MindmapNode | None, depth: int = 0) -> list[str]:
    if node is None or not node.title.strip():
        return []
    lines = [f"{'  ' * depth}- {node.title.strip()}"]
    for child in node.children[:12]:
        lines.extend(_render_mindmap(child, depth + 1))
    return lines


def build_markdown(payload: SummaryPayload, meta: dict[str, Any]) -> str:
    title = str(meta.get("title") or "视频总结")
    platform = str(meta.get("platform") or "")
    uploader = str(meta.get("uploader") or "")
    duration = meta.get("duration")
    url = str(meta.get("url") or "")
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

    if payload.tldr:
        lines.extend(["## 一句话总结", "", payload.tldr.strip(), ""])
    if payload.overview:
        lines.extend(["## 内容概述", "", payload.overview.strip(), ""])

    if payload.keywords:
        lines.extend(
            [
                "## 关键词",
                "",
                " ".join(f"`{item}`" for item in payload.keywords if item),
                "",
            ]
        )

    if payload.chapters:
        lines.extend(["## 章节大纲", ""])
        for chapter in payload.chapters:
            stamp = format_timestamp(chapter.start_seconds)
            chapter_title = chapter.title.strip() or "未命名章节"
            lines.append(f"### [{stamp}] {chapter_title}")
            if chapter.summary.strip():
                lines.extend(["", chapter.summary.strip()])
            if chapter.key_points:
                lines.append("")
                for point in chapter.key_points:
                    lines.append(f"- {point.strip()}")
            lines.append("")

    if payload.key_points:
        lines.extend(["## 核心要点", ""])
        for index, point in enumerate(payload.key_points, start=1):
            stamp = (
                f" [{format_timestamp(point.timestamp_seconds)}]"
                if point.timestamp_seconds is not None
                else ""
            )
            point_title = point.title.strip() or f"要点 {index}"
            detail = point.detail.strip()
            lines.append(f"{index}. **{point_title}**{stamp}")
            if detail:
                lines.append(f"   {detail}")
        lines.append("")

    if payload.concepts:
        lines.extend(["## 关键概念", ""])
        for concept in payload.concepts:
            term = concept.term.strip()
            explanation = concept.explanation.strip()
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
