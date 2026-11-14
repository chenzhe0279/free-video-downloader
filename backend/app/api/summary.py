from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.deps import client_ip, enforce_rate
from app.security import SlidingWindowLimiter, UnsafeUrlError, validate_public_url
from app.services.summary import exporters
from app.services.summary.errors import (
    SummaryBusyError,
    SummaryDisabledError,
    SummaryQuotaError,
    SummaryValidationError,
)
from app.services.summary.schemas import (
    SummaryConfigResponse,
    SummaryCreateResponse,
    SummaryDeleteResponse,
    SummaryRequest,
    SummaryTaskStatus,
    SummaryTranscriptResponse,
)
from app.services.summary.settings import get_summary_settings
from app.services.summary.stream import summary_event_stream
from app.services.summary.tasks import summary_manager

router = APIRouter(prefix="/api/summary", tags=["summary"])
logger = logging.getLogger("vds.summary.api")

SubtitleFormat = Literal["srt", "vtt", "txt", "md"]

_settings = get_summary_settings()
summary_limiter = SlidingWindowLimiter(_settings.summary_rate_limit_per_minute)


@router.get("/config", response_model=SummaryConfigResponse, summary="查询 AI 总结配置")
async def summary_config() -> SummaryConfigResponse:
    settings = get_summary_settings()
    reason: str | None = None
    if not settings.summary_enabled:
        reason = "功能已关闭（VDS_SUMMARY_ENABLED=false）"
    elif not settings.api_key:
        reason = "后端未配置 VDS_DEEPSEEK_API_KEY"
    return SummaryConfigResponse(
        enabled=settings.enabled,
        provider="deepseek",
        model=settings.deepseek_model,
        max_duration_seconds=settings.summary_max_duration_seconds,
        daily_limit_per_ip=settings.summary_daily_limit_per_ip,
        rate_limit_per_minute=settings.summary_rate_limit_per_minute,
        asr_chunk_seconds=settings.summary_asr_chunk_seconds,
        qa_enabled=settings.qa_available,
        qa_daily_limit_per_ip=settings.qa_daily_limit_per_ip,
        qa_rate_limit_per_minute=settings.qa_rate_limit_per_minute,
        qa_max_question_chars=settings.qa_max_question_chars,
        reason=reason,
    )


@router.post(
    "",
    response_model=SummaryCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建 AI 视频总结任务",
)
async def create_summary(payload: SummaryRequest, request: Request) -> SummaryCreateResponse:
    try:
        url = validate_public_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_summary_settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "AI 视频总结未启用：请在 backend/.env 配置 "
                "VDS_DEEPSEEK_API_KEY 后重启后端"
            ),
        )

    enforce_rate(summary_limiter, request, "AI 总结请求")
    try:
        task, cached = await summary_manager.create(
            url,
            client_ip(request),
            force=payload.force,
        )
    except SummaryDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (SummaryQuotaError, SummaryBusyError) as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except SummaryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("创建 AI 总结任务失败")
        raise HTTPException(status_code=500, detail=f"创建 AI 总结任务失败：{exc}") from exc

    return SummaryCreateResponse(
        task_id=task.id,
        status=task.status,  # type: ignore[arg-type]
        cached=cached,
    )


@router.get(
    "/{task_id}",
    response_model=SummaryTaskStatus,
    summary="查询 AI 总结任务状态",
)
async def get_summary_task(task_id: str) -> SummaryTaskStatus:
    task = summary_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return summary_manager.serialize(task)


@router.get(
    "/{task_id}/stream",
    summary="AI 总结进度与内容流（SSE）",
    response_class=StreamingResponse,
)
async def stream_summary_task(task_id: str, request: Request) -> StreamingResponse:
    """不展示进度条：未完成推状态，完成后把已生成的 Markdown 逐块下发。"""
    if summary_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return StreamingResponse(
        summary_event_stream(task_id, request, get_summary_settings()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/{task_id}/transcript",
    response_model=SummaryTranscriptResponse,
    summary="获取 AI 总结的完整文稿",
)
async def get_summary_transcript(task_id: str) -> SummaryTranscriptResponse:
    task = summary_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return summary_manager.transcript(task)


@router.get(
    "/{task_id}/subtitles",
    response_class=Response,
    summary="下载 AI 总结字幕文件（SRT/VTT/TXT/Markdown）",
)
async def download_summary_subtitles(
    task_id: str,
    format: SubtitleFormat = "srt",
) -> Response:
    task = summary_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    if not exporters.prepare_cues(task.segments, task.duration):
        raise HTTPException(status_code=409, detail="字幕尚未生成，请等待总结完成")

    try:
        if format == "md":
            body = exporters.to_markdown(
                task.segments,
                title=task.title,
                source=task.transcript_source,
                language=task.transcript_language,
                duration=task.duration,
            )
        elif format == "txt":
            body = exporters.to_txt(task.segments)
        elif format == "vtt":
            body = exporters.to_vtt(task.segments, task.duration)
        else:
            body = exporters.to_srt(task.segments, task.duration)
    except Exception as exc:  # pragma: no cover - 纯格式化，防御性兜底
        logger.exception("生成字幕文件失败：task=%s format=%s", task_id, format)
        raise HTTPException(status_code=500, detail="字幕生成失败") from exc

    filename = exporters.subtitle_filename(task, format)
    return Response(
        content=body,
        media_type=exporters.MEDIA_TYPES[format],
        headers={
            "Content-Disposition": exporters.content_disposition(filename),
            "Cache-Control": "no-store",
        },
    )


@router.delete(
    "/{task_id}",
    response_model=SummaryDeleteResponse,
    summary="取消/删除 AI 总结任务",
)
async def delete_summary_task(task_id: str) -> SummaryDeleteResponse:
    if not summary_manager.delete(task_id):
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return SummaryDeleteResponse()
