from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from app.deps import client_ip, enforce_rate, download_limiter
from app.schemas import (
    DirectLinkResponse,
    DownloadRequest,
    ProxyLinkResponse,
    TaskStatus,
)
from app.security import UnsafeUrlError, validate_public_url
from app.services import media
from app.services.task_manager import manager
from app.services.watermark import get_profile
from app.config import get_settings
from app.api.stream import token_store
from app.utils import build_filename

router = APIRouter(prefix="/api", tags=["download"])


def _find_option(normalized: dict, option_id: str) -> dict:
    option = next((o for o in normalized["options"] if o["id"] == option_id), None)
    if option is None:
        raise HTTPException(status_code=422, detail=f"未找到格式选项：{option_id}")
    return option


@router.post("/download", summary="创建下载（下载到本地 / 服务端转存 / 直链 / 代理）")
async def create_download(payload: DownloadRequest, request: Request) -> dict:
    enforce_rate(download_limiter, request, "下载请求")
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
    filename = build_filename(normalized.get("title"), option.get("label"), option.get("ext"))

    remove_watermark = bool(payload.remove_watermark) and not bool(option["audio_only"])
    if remove_watermark and get_profile(normalized.get("id")) is None:
        raise HTTPException(status_code=422, detail="该视频没有可用的去水印配置")
    if payload.mode in ("direct", "proxy") and payload.remove_watermark:
        raise HTTPException(
            status_code=422,
            detail="直链 / 代理模式不支持去水印，请改用「下载到本地」或「服务端转存」",
        )

    if payload.mode in ("server", "local"):
        ip = client_ip(request)

        # 单文件格式无需合并：直接给浏览器一个带文件名的代理流，服务器不落盘。
        if (
            payload.mode == "local"
            and option["progressive"]
            and option.get("direct_format_id")
            and not option["audio_only"]
            and not remove_watermark
        ):
            try:
                resolved = await media.resolve_direct(url, payload.option_id)
            except media.MediaError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            token = token_store.put(
                {
                    "url": resolved["url"],
                    "headers": resolved["headers"],
                    "filename": filename,
                },
                ttl=settings.direct_link_ttl_seconds,
            )
            return {
                "mode": "local",
                "stream_url": f"/api/proxy/{token}",
                "filename": filename,
                "expires_in": settings.direct_link_ttl_seconds,
            }

        if not manager.can_start(ip):
            raise HTTPException(
                status_code=429,
                detail=f"同时下载数量已达上限（{settings.max_concurrent_per_ip} 个），请等待完成后再试",
            )
        try:
            task = await manager.start(
                url,
                payload.option_id,
                ip,
                mode=payload.mode,
                remove_watermark=remove_watermark,
            )
        except media.MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "mode": payload.mode,
            "task_id": task.id,
            "option_id": payload.option_id,
            "filename": filename,
            "file_ttl_seconds": task.ttl_seconds,
        }

    try:
        resolved = await media.resolve_direct(url, payload.option_id)
    except media.MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.mode == "direct":
        return DirectLinkResponse(
            mode="direct",
            url=resolved["url"],
            filename=filename,
            expires_in=settings.direct_link_ttl_seconds,
        ).model_dump()

    token = token_store.put(
        {"url": resolved["url"], "headers": resolved["headers"], "filename": filename},
        ttl=settings.direct_link_ttl_seconds,
    )
    return ProxyLinkResponse(
        mode="proxy",
        proxy_url=f"/api/proxy/{token}",
        filename=filename,
        expires_in=settings.direct_link_ttl_seconds,
    ).model_dump()


@router.get("/tasks/{task_id}", response_model=TaskStatus, summary="查询下载进度")
async def get_task(task_id: str) -> TaskStatus:
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    expires_in = None
    if task.status == "finished" and task.finished_at is not None:
        expires_in = max(0, int(task.ttl_seconds - (time.time() - task.finished_at)))
    return TaskStatus(
        task_id=task.id,
        mode="local" if task.mode == "local" else "server",
        status=task.status,  # type: ignore[arg-type]
        progress=task.progress,
        downloaded_bytes=task.downloaded_bytes,
        total_bytes=task.total_bytes,
        speed=task.speed,
        eta=task.eta,
        filename=task.filename,
        size=task.total_bytes if task.status == "finished" else None,
        download_url=f"/api/files/{task.id}" if task.status == "finished" else None,
        expires_in=expires_in,
        error=task.error,
    )


@router.delete("/tasks/{task_id}", summary="主动删除任务与文件")
async def delete_task(task_id: str) -> dict[str, str]:
    if manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    manager.discard(task_id)
    return {"status": "deleted"}
