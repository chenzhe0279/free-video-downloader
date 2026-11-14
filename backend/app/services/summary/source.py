from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yt_dlp

from app.config import resolve_ffmpeg
from app.security import UnsafeUrlError, validate_public_url
from app.services.summary.settings import get_summary_settings

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_INFO_TTL_SECONDS = 1200
_INFO_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class SourceError(Exception):
    pass


def _base_ydl_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "ffmpeg_location": resolve_ffmpeg(),
    }


def _raw_info_sync(url: str) -> dict[str, Any]:
    try:
        with yt_dlp.YoutubeDL({**_base_ydl_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise SourceError(str(exc) or "视频信息解析失败") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise SourceError(f"视频信息解析异常：{exc}") from exc
    if not isinstance(info, dict):
        raise SourceError("视频信息解析结果为空")
    return info


async def raw_info(url: str) -> dict[str, Any]:
    """获取 yt-dlp 原始信息（含字幕 URL）；短时缓存避免重复提取。"""
    now = time.monotonic()
    cached = _INFO_CACHE.get(url)
    if cached is not None and now - cached[0] < _INFO_TTL_SECONDS:
        return cached[1]
    info = await asyncio.to_thread(_raw_info_sync, url)
    _INFO_CACHE[url] = (now, info)
    return info


def _find_downloaded(target_dir: Path, stem: str) -> Path | None:
    matches = sorted(target_dir.glob(f"{stem}.*"))
    for path in matches:
        if path.suffix.lower() in {".part", ".ytdl"}:
            continue
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _download_audio_sync(url: str, target_dir: Path, max_bytes: int) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_base_ydl_opts(),
        "format": "bestaudio/best",
        "outtmpl": str(target_dir / "audio.%(ext)s"),
        "max_filesize": max_bytes,
        "retries": 3,
        "concurrent_fragment_downloads": 2,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        if "larger than max" in message.lower():
            raise SourceError("音频文件超过大小上限，暂不支持总结") from exc
        raise SourceError(f"音频下载失败：{message}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise SourceError(f"音频下载异常：{exc}") from exc

    path = _find_downloaded(target_dir, "audio")
    if path is None and isinstance(info, dict):
        for entry in info.get("requested_downloads") or []:
            candidate = entry.get("filepath") if isinstance(entry, dict) else None
            if candidate and Path(candidate).is_file():
                path = Path(candidate)
                break
    if path is None or path.stat().st_size <= 0:
        raise SourceError("音频下载完成但没有找到文件")
    if path.stat().st_size > max_bytes:
        path.unlink(missing_ok=True)
        raise SourceError("音频文件超过大小上限，暂不支持总结")
    return path


async def download_audio(url: str, target_dir: Path, max_bytes: int | None = None) -> Path:
    settings = get_summary_settings()
    limit = max_bytes or settings.summary_max_audio_bytes
    return await asyncio.to_thread(_download_audio_sync, url, target_dir, limit)


async def download_douyin_video(
    url: str,
    headers: dict[str, str],
    target_dir: Path,
    max_bytes: int | None = None,
) -> Path:
    """抖音直链是音视频合一的 mp4；下载后由 ffmpeg 抽取音频。"""
    settings = get_summary_settings()
    limit = max_bytes or settings.summary_max_audio_bytes
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "source.mp4"

    def _run() -> Path:
        request_headers = {"User-Agent": _UA, **(headers or {})}
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(20.0, read=300.0),
            ) as client:
                with client.stream("GET", url, headers=request_headers) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length") or 0)
                    if total and total > limit:
                        raise SourceError("抖音视频超过大小上限，暂不支持总结")
                    written = 0
                    with path.open("wb") as handle:
                        for chunk in response.iter_bytes(256 * 1024):
                            if not chunk:
                                continue
                            written += len(chunk)
                            if written > limit:
                                raise SourceError("抖音视频超过大小上限，暂不支持总结")
                            handle.write(chunk)
                    if total and written < total:
                        raise SourceError(f"抖音视频下载不完整（{written}/{total} 字节）")
        except httpx.HTTPError as exc:
            path.unlink(missing_ok=True)
            raise SourceError(f"抖音视频下载失败：{exc}") from exc
        except SourceError:
            path.unlink(missing_ok=True)
            raise
        if not path.exists() or path.stat().st_size <= 0:
            raise SourceError("抖音视频下载完成但没有文件")
        return path

    return await asyncio.to_thread(_run)


def _referer_for(video_url: str) -> str:
    parsed = urlparse(video_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return "https://www.bilibili.com/"


async def fetch_text(
    url: str,
    *,
    video_url: str = "",
    max_bytes: int = 5 * 1024 * 1024,
) -> str:
    """获取字幕文本；限制大小并校验目标地址，防止 SSRF。"""
    try:
        safe_url = validate_public_url(url)
    except UnsafeUrlError as exc:
        raise SourceError(f"字幕地址不可访问：{exc}") from exc

    headers = {
        "User-Agent": _UA,
        "Accept": "*/*",
        "Referer": _referer_for(video_url),
    }
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=60.0),
        ) as client:
            response = await client.get(safe_url, headers=headers)
    except httpx.HTTPError as exc:
        raise SourceError(f"字幕下载失败：{exc}") from exc
    if response.status_code >= 400:
        raise SourceError(f"字幕下载失败（HTTP {response.status_code}）")
    if len(response.content) > max_bytes:
        raise SourceError("字幕文件超过大小上限")
    return response.text
