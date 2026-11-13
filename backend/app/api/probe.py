from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.deps import enforce_rate, probe_limiter
from app.schemas import ProbeRequest, ProbeResponse
from app.security import UnsafeUrlError, validate_public_url
from app.services import media

router = APIRouter(prefix="/api", tags=["probe"])

_INTERNAL_OPTION_KEYS = {"selector", "direct_url", "headers"}


@router.post("/probe", response_model=ProbeResponse, summary="解析视频链接")
async def probe_media(payload: ProbeRequest, request: Request) -> ProbeResponse:
    enforce_rate(probe_limiter, request, "解析请求")
    try:
        url = validate_public_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        data = await media.probe(url)
    except media.MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    options = [
        {key: value for key, value in opt.items() if key not in _INTERNAL_OPTION_KEYS}
        for opt in data["options"]
    ]
    return ProbeResponse(**{**data, "options": options})
