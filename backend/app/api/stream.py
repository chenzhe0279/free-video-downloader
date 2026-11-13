from __future__ import annotations

import mimetypes
import re
import secrets
import time
from pathlib import Path
from typing import Any, AsyncIterator, Iterator
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps import client_ip, enforce_rate, download_limiter
from app.services.task_manager import manager

router = APIRouter(prefix="/api", tags=["stream"])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK = 1024 * 256


class TokenStore:
    """Short-lived in-memory registry for proxy links."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def put(self, payload: dict[str, Any], ttl: int) -> str:
        self._evict()
        token = secrets.token_urlsafe(16)
        self._items[token] = (time.time() + ttl, payload)
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        self._evict()
        entry = self._items.get(token)
        return entry[1] if entry else None

    def _evict(self) -> None:
        now = time.time()
        for token, (expires_at, _) in list(self._items.items()):
            if expires_at <= now:
                self._items.pop(token, None)


token_store = TokenStore()


def _content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode() or "video.mp4"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/files/{task_id}", summary="下载服务端已保存的文件（支持断点续传）")
async def serve_file(task_id: str, request: Request):
    task = manager.get(task_id)
    if task is None or task.status != "finished" or not task.filepath:
        raise HTTPException(status_code=404, detail="文件不存在或已过期，请重新下载")

    path = Path(task.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件已被清理，请重新下载")

    size = path.stat().st_size
    filename = task.filename or path.name
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": _content_disposition(filename),
        "Cache-Control": "no-store",
    }

    # 传输期间禁止清理线程删除文件
    manager.begin_serve(task_id)

    def body(start: int, length: int) -> Iterator[bytes]:
        try:
            yield from _iter_file(path, start, length)
        finally:
            manager.end_serve(task_id)

    try:
        range_header = request.headers.get("range")
        if range_header:
            match = _RANGE_RE.match(range_header.strip())
            if match:
                start_raw, end_raw = match.groups()
                start = int(start_raw) if start_raw else 0
                end = int(end_raw) if end_raw else size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    raise HTTPException(
                        status_code=416,
                        detail="请求范围无效",
                        headers={"Content-Range": f"bytes */{size}"},
                    )
                length = end - start + 1
                return StreamingResponse(
                    body(start, length),
                    status_code=206,
                    media_type=media_type,
                    headers={
                        **base_headers,
                        "Content-Range": f"bytes {start}-{end}/{size}",
                        "Content-Length": str(length),
                    },
                )

        return StreamingResponse(
            body(0, size),
            media_type=media_type,
            headers={**base_headers, "Content-Length": str(size)},
        )
    except BaseException:
        manager.end_serve(task_id)
        raise


@router.get("/proxy/{token}", summary="代理转发直链（透传 Range 与防盗链请求头）")
async def proxy_stream(token: str, request: Request):
    enforce_rate(download_limiter, request, "代理下载请求")

    entry = token_store.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="代理链接已过期，请重新发起下载")

    forward_headers = dict(entry.get("headers") or {})
    forward_headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )
    range_header = request.headers.get("range")
    if range_header:
        forward_headers["Range"] = range_header

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=300.0),
    )
    try:
        upstream_request = client.build_request("GET", entry["url"], headers=forward_headers)
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"上游连接失败：{exc}") from exc

    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"上游返回 {upstream.status_code}，该链接可能受限，请改用服务端下载",
        )

    passthrough = {}
    for header in ("content-type", "content-length", "content-range", "accept-ranges"):
        value = upstream.headers.get(header)
        if value:
            passthrough[header] = value
    passthrough.setdefault("Accept-Ranges", "bytes")
    download_name = entry.get("filename") or (
        f"video-{client_ip(request).replace(':', '_')}.mp4"
    )
    passthrough["Content-Disposition"] = _content_disposition(download_name)
    passthrough["Cache-Control"] = "no-store"

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes(_CHUNK):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        headers=passthrough,
    )
