from __future__ import annotations

import asyncio
import time
from typing import Any

import yt_dlp

from app.config import get_settings, resolve_ffmpeg
from app.services.watermark import watermark_info


class YtdlpError(Exception):
    pass


def _ffmpeg_location() -> str | None:
    return resolve_ffmpeg()


_PROBE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _base_ydl_opts(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "socket_timeout": 15,
        "retries": 3,
        "ffmpeg_location": _ffmpeg_location(),
        "noplaylist": False,
    }
    if extra:
        opts.update(extra)
    return opts


async def probe(url: str) -> dict[str, Any]:
    """解析视频元数据与可用格式（不下载）。"""
    settings = get_settings()
    now = time.monotonic()
    cached = _PROBE_CACHE.get(url)
    if cached and now - cached[0] < settings.probe_cache_ttl_seconds:
        return _normalize(cached[1], url)

    loop = asyncio.get_running_loop()

    def _run() -> dict[str, Any]:
        opts = _base_ydl_opts({"skip_download": True})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise YtdlpError(str(exc) or "解析失败，请检查链接") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise YtdlpError(f"解析异常：{exc}") from exc

    info = await loop.run_in_executor(None, _run)
    _PROBE_CACHE[url] = (now, info)
    return _normalize(info, url)


def _normalize(info: dict[str, Any], url: str) -> dict[str, Any]:
    formats: list[dict[str, Any]] = info.get("formats") or []

    def _has_codec(fmt: dict[str, Any], kind: str) -> bool:
        value = fmt.get(kind)
        return value is not None and value != "none"

    progressive: list[dict[str, Any]] = [
        f for f in formats if _has_codec(f, "vcodec") and _has_codec(f, "acodec")
    ]
    video_only: list[dict[str, Any]] = [
        f for f in formats if _has_codec(f, "vcodec") and not _has_codec(f, "acodec")
    ]
    audio_only_list: list[dict[str, Any]] = [
        f for f in formats if not _has_codec(f, "vcodec") and _has_codec(f, "acodec")
    ]

    def _pick_best(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        def _score(f: dict[str, Any]) -> tuple[float, float]:
            height = f.get("height") or 0
            tbr = f.get("tbr") or f.get("vbr") or f.get("abr") or 0
            return (float(height), float(tbr))
        if not candidates:
            return None
        return max(candidates, key=_score)

    # Group usable video buckets by exact height.
    buckets: dict[int, dict[str, Any]] = {}
    for fmt in (*progressive, *video_only):
        height = fmt.get("height")
        if not height:
            continue
        current = buckets.get(int(height))
        if current is None or _fmt_tbr(fmt) > _fmt_tbr(current):
            buckets[int(height)] = fmt

    options: list[dict[str, Any]] = []

    # High-quality buckets first.
    for height in sorted(buckets, reverse=True):
        fmt = buckets[height]
        prog_candidates = [f for f in progressive if (f.get("height") or 0) == height]
        prog = prog_candidates[0] if prog_candidates else None
        audio_candidates = [
            f for f in audio_only_list if (f.get("height") or 0) <= (height + 72)
        ]
        audio = max(audio_candidates, key=_fmt_tbr) if audio_candidates else None

        if prog:
            selector = f"{_fmt_id(prog)}+ba/{_fmt_id(prog)}"
            label = f"{height}P 超清"
            note = "单文件，支持直链"
            options.append({
                "id": f"{height}p",
                "label": label,
                "note": note,
                "height": height,
                "ext": prog.get("ext"),
                "filesize": prog.get("filesize") or prog.get("filesize_approx"),
                "fps": prog.get("fps"),
                "progressive": True,
                "direct_format_id": _fmt_id(prog),
                "selector": selector,
                "audio_only": False,
            })
        else:
            vid_id = _fmt_id(fmt)
            audio_id = _fmt_id(audio) if audio else None
            if audio_id:
                selector = f"{vid_id}+{audio_id}"
            else:
                selector = f"bv*[height<={height}]+ba/b[height<={height}]"
            options.append({
                "id": f"{height}p",
                "label": f"{height}P 清晰",
                "note": "音视频分离，服务端合并后直接下载到本机",
                "height": height,
                "ext": fmt.get("ext"),
                "filesize": None,
                "fps": fmt.get("fps"),
                "progressive": False,
                "direct_format_id": None,
                "selector": selector,
                "audio_only": False,
            })

    if not options:
        # 兜底：把 yt-dlp 能找到的单文件资源当作可直链/可直接下载的选项
        single = None
        for f in sorted(formats, key=_fmt_tbr, reverse=True):
            proto = str(f.get("protocol") or "")
            fmt_id = f.get("format_id")
            if proto.startswith("http") and fmt_id:
                single = f
                break
        if single:
            options.append({
                "id": "best",
                "label": "最佳画质",
                "note": "单文件直链下载",
                "height": single.get("height"),
                "ext": single.get("ext"),
                "filesize": single.get("filesize") or single.get("filesize_approx"),
                "fps": single.get("fps"),
                "progressive": True,
                "direct_format_id": str(single.get("format_id")),
                "selector": str(single.get("format_id")),
                "audio_only": False,
            })
        else:
            options.append({
                "id": "best",
                "label": "最佳画质",
                "note": "自动选择可用格式",
                "height": None,
                "ext": None,
                "filesize": None,
                "fps": None,
                "progressive": True,
                "direct_format_id": None,
                "selector": "bv+ba/b",
                "audio_only": False,
            })

    best_audio = _pick_best(audio_only_list)
    if best_audio:
        options.append({
            "id": "audio",
            "label": "仅音频 (MP3)",
            "note": "提取音频，服务端转码后下载到本机",
            "height": None,
            "ext": "mp3",
            "filesize": best_audio.get("filesize") or best_audio.get("filesize_approx"),
            "fps": None,
            "progressive": True,
            "direct_format_id": _fmt_id(best_audio),
            "selector": "ba/b",
            "audio_only": True,
        })

    subtitles: list[str] = []
    for lang in (info.get("subtitles") or {}):
        subtitles.append(lang)
    for lang in (info.get("automatic_captions") or {}):
        if lang not in subtitles:
            subtitles.append(lang)

    return {
        "id": info.get("id") or info.get("display_id") or "video",
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or "未知标题",
        "thumbnail": _pick_thumbnail(info),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "platform": info.get("extractor") or info.get("extractor_key"),
        "is_playlist": bool(info.get("_type") == "playlist"),
        "entry_count": info.get("n_entries"),
        "options": options,
        "subtitles": subtitles[:8],
        "watermark": watermark_info(info.get("id")),
    }


def _fmt_tbr(fmt: dict[str, Any]) -> float:
    return float(fmt.get("tbr") or fmt.get("vbr") or fmt.get("abr") or 0)


def _fmt_id(fmt: dict[str, Any]) -> str:
    return str(fmt.get("format_id") or "")


def _pick_thumbnail(info: dict[str, Any]) -> str | None:
    thumbs = info.get("thumbnails") or []
    if thumbs:
        return thumbs[-1].get("url") or thumbs[-1].get("thumbnail")
    return info.get("thumbnail")


async def resolve_direct(url: str, option_id: str) -> dict[str, Any]:
    """拿某个格式的直链与请求头（用于模式 B）。支持单文件格式；不支持 HLS/DASH 清单。"""
    normalized = await probe(url)
    option = next((o for o in normalized["options"] if o["id"] == option_id), None)
    if not option:
        raise YtdlpError(f"未找到格式选项：{option_id}")
    if not option["direct_format_id"]:
        raise YtdlpError("该清晰度不支持直链，请使用服务端下载")

    loop = asyncio.get_running_loop()

    def _run() -> dict[str, Any]:
        opts = _base_ydl_opts({"skip_download": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get("formats") or []
        target = next(
            (f for f in formats if str(f.get("format_id")) == option["direct_format_id"]),
            None,
        )
        if not target:
            raise YtdlpError("无法定位该格式的直链")
        file_url = target.get("url")
        if not file_url:
            raise YtdlpError("该平台暂不提供直链")
        headers = target.get("http_headers") or {}
        # Only keep commonly safe forwarding headers.
        safe_headers = {
            k: v
            for k, v in headers.items()
            if k.lower() in ("user-agent", "referer", "origin", "accept", "accept-language")
        }
        return {
            "url": file_url,
            "headers": safe_headers,
            "protocol": target.get("protocol"),
        }

    result = await loop.run_in_executor(None, _run)
    return {
        "url": result["url"],
        "headers": result["headers"],
        "protocol": result.get("protocol"),
        "option": option,
    }
