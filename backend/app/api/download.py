from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.deps import client_ip, enforce_rate, download_limiter
from app.schemas import (
    DirectLinkResponse,
    DownloadRequest,
    ProxyLinkResponse,
    TaskStatus,
)
from app.security import UnsafeUrlError, validate_public_url
from app.services import ytdlp_service
from app.services.task_manager import manager
from app.config import get_settings
from app.api.stream import token_store

router = APIRouter(prefix="/api", tags=["download"])


@router.post("/download", summary="创建下载（服务端 / 直链 / 代理）")
async def create_download(payload: DownloadRequest, request: Request) -> dict:
    enforce_rate(download_limiter, request, "下载请求")
    try:
        url = validate_public_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_settings()

    if payload.mode == "server":
        ip = client_ip(request)
        if not manager.can_start(ip):
            raise HTTPException(
                status_code=429,
                detail=f"同时下载数量已达上限（{settings.max_concurrent_per_ip} 个），请等待完成后再试",
            )
        try:
            task = await manager.start(url, payload.option_id, ip)
        except ytdlp_service.YtdlpError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"mode": "server", "task_id": task.id, "option_id": payload.option_id}

    try:
        resolved = await ytdlp_service.resolve_direct(url, payload.option_id)
    except ytdlp_service.YtdlpError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = resolved["option"].get("label")
    if payload.mode == "direct":
        return DirectLinkResponse(
            mode="direct",
            url=resolved["url"],
            filename=filename,
            expires_in=settings.direct_link_ttl_seconds,
        ).model_dump()

    token = token_store.put(
        {"url": resolved["url"], "headers": resolved["headers"]},
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
    return TaskStatus(
        task_id=task.id,
        status=task.status,  # type: ignore[arg-type]
        progress=task.progress,
        downloaded_bytes=task.downloaded_bytes,
        total_bytes=task.total_bytes,
        speed=task.speed,
        eta=task.eta,
        filename=task.filename,
        size=task.total_bytes if task.status == "finished" else None,
        download_url=f"/api/files/{task.id}" if task.status == "finished" else None,
        error=task.error,
    )


@router.delete("/tasks/{task_id}", summary="主动删除任务与文件")
async def delete_task(task_id: str) -> dict[str, str]:
    if manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    manager.discard(task_id)
    return {"status": "deleted"}
