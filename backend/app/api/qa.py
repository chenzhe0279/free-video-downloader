from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps import client_ip, enforce_rate
from app.security import SlidingWindowLimiter
from app.services.qa.errors import QaError, QaQuotaError, QaValidationError
from app.services.qa.prompts import RELATED_REFUSAL
from app.services.qa.schemas import QaAskRequest
from app.services.qa.service import qa_service
from app.services.qa.sse import sse_event
from app.services.summary.deepseek import DeepSeekClient, DeepSeekError
from app.services.summary.settings import SummarySettings, get_summary_settings
from app.services.summary.tasks import SummaryTask, summary_manager

router = APIRouter(prefix="/api", tags=["qa"])
logger = logging.getLogger("vds.qa.api")

_settings = get_summary_settings()
qa_limiter = SlidingWindowLimiter(_settings.qa_rate_limit_per_minute)


@router.post(
    "/summary/{task_id}/ask",
    summary="AI 视频问答（SSE 流式）",
    response_class=StreamingResponse,
)
async def ask_summary(
    task_id: str,
    payload: QaAskRequest,
    request: Request,
) -> StreamingResponse:
    settings = get_summary_settings()
    if not settings.qa_available:
        raise HTTPException(
            status_code=503,
            detail=(
                "AI 问答未启用：请确认 VDS_QA_ENABLED=true 且已配置 "
                "VDS_DEEPSEEK_API_KEY，然后重启后端"
            ),
        )

    task = summary_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="总结任务不存在或已过期，请重新生成总结")
    if task.status != "finished" or task.summary is None:
        raise HTTPException(status_code=409, detail="总结尚未完成，请稍后再提问")

    enforce_rate(qa_limiter, request, "AI 问答请求")
    ip = client_ip(request)
    try:
        question = qa_service.validate_question(payload.question)
        history = qa_service.prepare_history(payload.history)
        qa_service.check_daily(ip)
    except QaValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QaQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    qa_service.increment_daily(ip)
    summary_manager.touch(task_id)
    logger.info(
        "qa ask task=%s question_len=%s history=%s",
        task_id,
        len(question),
        len(history),
    )

    return StreamingResponse(
        _event_stream(task, question, history, request, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _event_stream(
    task: SummaryTask,
    question: str,
    history: list[dict[str, str]],
    request: Request,
    settings: SummarySettings,
):
    client = DeepSeekClient(settings)
    try:
        yield sse_event("status", {"phase": "checking"})
        if await request.is_disconnected():
            return

        relevant, _gate_meta = await qa_service.check_relevance(
            client, task, question, history
        )
        if not relevant:
            yield sse_event("refusal", {
                "message": RELATED_REFUSAL,
                "suggestions": qa_service.suggestions(task),
            })
            yield sse_event("done", {"finish_reason": "refusal"})
            return

        yield sse_event("status", {"phase": "answering"})
        async for token in qa_service.stream_answer(client, task, question, history):
            if await request.is_disconnected():
                logger.info("qa client disconnected task=%s", task.id)
                return
            yield sse_event("token", {"text": token})
        yield sse_event("done", {"finish_reason": "stop"})
    except (QaError, DeepSeekError) as exc:
        logger.warning("qa stream failed task=%s error=%s", task.id, exc)
        yield sse_event("error", {"message": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("qa stream crashed task=%s", task.id)
        yield sse_event("error", {"message": "问答失败，请稍后重试"})
    finally:
        await client.aclose()
