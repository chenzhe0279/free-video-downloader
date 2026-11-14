from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.deps import client_ip, enforce_rate
from app.security import SlidingWindowLimiter, UnsafeUrlError, validate_public_url
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
from app.services.summary.tasks import summary_manager

router = APIRouter(prefix="/api/summary", tags=["summary"])
logger = logging.getLogger("vds.summary.api")

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
    "/{task_id}/transcript",
    response_model=SummaryTranscriptResponse,
    summary="获取 AI 总结的完整文稿",
)
async def get_summary_transcript(task_id: str) -> SummaryTranscriptResponse:
    task = summary_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return summary_manager.transcript(task)


@router.delete(
    "/{task_id}",
    response_model=SummaryDeleteResponse,
    summary="取消/删除 AI 总结任务",
)
async def delete_summary_task(task_id: str) -> SummaryDeleteResponse:
    if not summary_manager.delete(task_id):
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期")
    return SummaryDeleteResponse()
