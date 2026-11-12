from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.deps import enforce_rate, probe_limiter
from app.schemas import ProbeRequest, ProbeResponse
from app.security import UnsafeUrlError, validate_public_url
from app.services import ytdlp_service

router = APIRouter(prefix="/api", tags=["probe"])


@router.post("/probe", response_model=ProbeResponse, summary="解析视频链接")
async def probe_media(payload: ProbeRequest, request: Request) -> ProbeResponse:
    enforce_rate(probe_limiter, request, "解析请求")
    try:
        url = validate_public_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        data = await ytdlp_service.probe(url)
    except ytdlp_service.YtdlpError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    options = [{k: v for k, v in opt.items() if k != "selector"} for opt in data["options"]]
    return ProbeResponse(**{**data, "options": options})
