from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.deps import client_ip, enforce_rate, preview_limiter
from app.schemas import PreviewRequest, PreviewResponse
from app.security import UnsafeUrlError, validate_public_url
from app.services import media
from app.services.task_manager import manager
from app.api.stream import token_store
from app.utils import build_filename

router = APIRouter(prefix="/api", tags=["preview"])

# 浏览器 <video> 能直接播放的容器；m3u8/mpd 清单与 flv 都先交给服务端处理
_PLAYABLE_EXTS = {"mp4", "webm", "mov", "m4v"}


def _find_option(normalized: dict, option_id: str) -> dict:
    option = next((o for o in normalized["options"] if o["id"] == option_id), None)
    if option is None:
        raise HTTPException(status_code=422, detail=f"未找到格式选项：{option_id}")
    return option


def _direct_playable(option: dict, resolved: dict) -> bool:
    """判断平台直链能否直接喂给 <video>。"""
    ext = str(option.get("ext") or "").lower()
    if ext and ext not in _PLAYABLE_EXTS:
        return False
    protocol = str(resolved.get("protocol") or "").lower()
    if protocol and not protocol.startswith(("http", "m3u8", "m3u8_native")):
        return False
    clean_url = str(resolved.get("url") or "").split("?")[0].lower()
    if clean_url.endswith((".m3u8", ".mpd")):
        return False
    return bool(resolved.get("url"))


@router.post("/preview", response_model=PreviewResponse, summary="准备在线播放地址")
async def prepare_preview(payload: PreviewRequest, request: Request) -> PreviewResponse:
    enforce_rate(preview_limiter, request, "预览请求")
    try:
        url = validate_public_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_settings()
    try:
        normalized = await media.probe(url)
    except media.MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    option = _find_option(normalized, payload.option_id)
    if option["audio_only"]:
        raise HTTPException(status_code=422, detail="音频选项不支持在线预览，请下载后收听")

    ip = client_ip(request)
    filename = build_filename(normalized.get("title"), option.get("label"), option.get("ext"))

    # 同一 IP 同一清晰度的预览任务直接复用，避免重复合并
    reusable = manager.find_preview(url, payload.option_id, ip)
    if reusable is not None:
        expires_in = None
        if reusable.status == "finished" and reusable.finished_at is not None:
            expires_in = max(
                0, int(reusable.ttl_seconds - (time.time() - reusable.finished_at))
            )
            return PreviewResponse(
                mode="file",
                preview_url=f"/api/files/{reusable.id}?inline=1",
                filename=reusable.filename or filename,
                expires_in=expires_in,
            )
        return PreviewResponse(
            mode="task",
            task_id=reusable.id,
            filename=reusable.filename or filename,
        )

    # 单文件直链：服务端只做代理，浏览器边下边播，秒开且不落盘
    if option.get("progressive") and option.get("direct_format_id"):
        try:
            resolved = await media.resolve_direct(url, payload.option_id)
        except media.MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if _direct_playable(option, resolved):
            token = token_store.put(
                {
                    "url": resolved["url"],
                    "headers": resolved["headers"],
                    "filename": filename,
                },
                ttl=settings.direct_link_ttl_seconds,
            )
            return PreviewResponse(
                mode="proxy",
                preview_url=f"/api/preview/proxy/{token}",
                filename=filename,
                expires_in=settings.direct_link_ttl_seconds,
            )

    # 音视频分离（或容器不可播）：服务端下载合并，完成后用 /api/files 内联播放
    if not manager.can_start(ip):
        raise HTTPException(
            status_code=429,
            detail=f"同时准备预览的数量已达上限（{settings.max_concurrent_per_ip} 个），请稍后再试",
        )
    try:
        task = await manager.start(url, payload.option_id, ip, mode="preview")
    except media.MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreviewResponse(mode="task", task_id=task.id, filename=filename)
