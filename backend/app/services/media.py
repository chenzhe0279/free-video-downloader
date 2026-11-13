from __future__ import annotations

from typing import Any

from app.services import douyin, ytdlp_service


class MediaError(Exception):
    """统一的解析/下载错误，API 层映射为 422。"""


async def probe(url: str) -> dict[str, Any]:
    if douyin.is_douyin_url(url):
        try:
            return await douyin.probe(url)
        except douyin.DouyinError as exc:
            raise MediaError(str(exc)) from exc
    try:
        return await ytdlp_service.probe(url)
    except ytdlp_service.YtdlpError as exc:
        raise MediaError(str(exc)) from exc


async def resolve_direct(url: str, option_id: str) -> dict[str, Any]:
    if douyin.is_douyin_url(url):
        try:
            return await douyin.resolve_direct(url, option_id)
        except douyin.DouyinError as exc:
            raise MediaError(str(exc)) from exc
    try:
        return await ytdlp_service.resolve_direct(url, option_id)
    except ytdlp_service.YtdlpError as exc:
        raise MediaError(str(exc)) from exc
