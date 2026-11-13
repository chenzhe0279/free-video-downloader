from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yt_dlp

from app.config import get_settings, resolve_ffmpeg
from app.services import media
from app.services.media import MediaError
from app.services.watermark import (
    WatermarkError,
    get_profile,
    remove_watermark as apply_watermark_removal,
)
from app.utils import build_filename

# 浏览器 <video> 能直接播放的容器；其余（如 B 站低清 flv）需要重新封装
_PLAYABLE_SUFFIXES = {".mp4", ".webm", ".mov", ".m4v"}


@dataclass
class DownloadTask:
    id: str
    url: str
    option_id: str
    selector: str
    audio_only: bool
    client_ip: str
    title: str = ""
    video_id: str = ""
    mode: str = "server"
    option_label: str | None = None
    remove_watermark: bool = False
    direct_url: str | None = None
    direct_headers: dict[str, str] = field(default_factory=dict)
    ttl_seconds: int = 3600
    status: str = "queued"
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    filepath: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # 正在被下载传输的计数：传输期间不能被清理线程删掉文件
    serving: int = 0


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, DownloadTask] = {}
        self._per_ip: dict[str, int] = {}
        self._semaphore = asyncio.Semaphore(get_settings().max_concurrent_total)

    # ---- capacity ----
    def active_for_ip(self, ip: str) -> int:
        return self._per_ip.get(ip, 0)

    def can_start(self, ip: str) -> bool:
        return self.active_for_ip(ip) < get_settings().max_concurrent_per_ip

    def get(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def find_preview(self, url: str, option_id: str, client_ip: str) -> DownloadTask | None:
        """复用同一 IP 下正在准备或已就绪的预览任务，避免重复合并。"""
        now = time.time()
        for task in self._tasks.values():
            if task.mode != "preview" or task.client_ip != client_ip:
                continue
            if task.url != url or task.option_id != option_id or task.status == "error":
                continue
            if task.status == "finished":
                if not task.filepath or task.finished_at is None:
                    continue
                if now - task.finished_at >= task.ttl_seconds:
                    continue
            return task
        return None

    def all_tasks(self) -> list[DownloadTask]:
        return list(self._tasks.values())

    # ---- lifecycle ----
    async def start(
        self,
        url: str,
        option_id: str,
        client_ip: str,
        mode: str = "server",
        remove_watermark: bool = False,
    ) -> DownloadTask:
        normalized = await media.probe(url)
        option = next((o for o in normalized["options"] if o["id"] == option_id), None)
        if option is None:
            raise MediaError(f"未找到格式选项：{option_id}")
        if remove_watermark and get_profile(normalized.get("id")) is None:
            raise MediaError("该视频没有可用的去水印配置")

        settings = get_settings()
        task_mode = mode if mode in ("local", "preview") else "server"
        task = DownloadTask(
            id=uuid.uuid4().hex[:16],
            url=url,
            option_id=option_id,
            selector=option.get("selector", ""),
            audio_only=bool(option["audio_only"]),
            client_ip=client_ip,
            title=normalized["title"],
            video_id=normalized.get("id") or "",
            mode=task_mode,
            option_label=option.get("label"),
            remove_watermark=remove_watermark and not bool(option["audio_only"]),
            direct_url=option.get("direct_url"),
            direct_headers=option.get("headers") or {},
            ttl_seconds=(
                settings.local_file_ttl_seconds
                if task_mode in ("local", "preview")
                else settings.file_ttl_seconds
            ),
        )
        self._tasks[task.id] = task
        self._per_ip[client_ip] = self.active_for_ip(client_ip) + 1
        asyncio.create_task(self._run(task))
        return task

    async def _run(self, task: DownloadTask) -> None:
        settings = get_settings()
        target_dir = settings.download_dir / task.id
        target_dir.mkdir(parents=True, exist_ok=True)

        def hook(payload: dict[str, Any]) -> None:
            status = payload.get("status")
            if status == "downloading":
                total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
                downloaded = payload.get("downloaded_bytes") or 0
                task.status = "downloading"
                task.downloaded_bytes = int(downloaded)
                task.total_bytes = int(total) if total else None
                if task.total_bytes:
                    task.progress = min(99.0, round(downloaded / task.total_bytes * 100, 2))
                task.speed = payload.get("speed")
                task.eta = payload.get("eta")
            elif status == "finished":
                task.status = "processing"
                task.progress = 99.0

        outtmpl = str(target_dir / "%(title).80B.%(ext)s")
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "retries": 5,
            "ffmpeg_location": resolve_ffmpeg(),
            "format": task.selector,
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "max_filesize": settings.max_file_size_bytes,
            "concurrent_fragment_downloads": 4,
            "restrictfilenames": False,
            "windowsfilenames": False,
        }
        if task.audio_only:
            ydl_opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]

        try:
            async with self._semaphore:
                task.status = "downloading"
                if task.direct_url:
                    filepath = await asyncio.to_thread(
                        self._download_direct, task, target_dir
                    )
                else:
                    info = await asyncio.to_thread(self._download_sync, task, ydl_opts)
                    filepath = self._extract_filepath(info)
                if not filepath or not os.path.exists(filepath):
                    raise MediaError("下载完成但未找到文件")

                size = os.path.getsize(filepath)
                if size > settings.max_file_size_bytes:
                    os.remove(filepath)
                    raise MediaError(
                        f"文件超过大小上限（{size / 1024**3:.2f}GB > "
                        f"{settings.max_file_size_bytes / 1024**3:.0f}GB）"
                    )

                if task.remove_watermark and not task.audio_only:
                    profile = get_profile(task.video_id)
                    if profile is None:
                        raise WatermarkError("该视频没有可用的去水印配置")
                    task.status = "cleaning"
                    task.progress = 99.0
                    task.speed = None
                    task.eta = None
                    cleaned = target_dir / "clean.mp4"
                    await asyncio.to_thread(
                        apply_watermark_removal,
                        Path(filepath),
                        cleaned,
                        profile,
                    )
                    Path(filepath).unlink(missing_ok=True)
                    filepath = str(cleaned)
                    suffix = task.option_label or "原片"
                    task.option_label = f"{suffix} · 无水印"

                # 在线预览：flv 等浏览器不能直接播放的容器重新封装成 MP4（不重编码）
                if task.mode == "preview" and not task.audio_only:
                    filepath = await asyncio.to_thread(
                        self._ensure_playable, filepath, target_dir
                    )

                size = os.path.getsize(filepath)
                task.filepath = filepath
                # 磁盘上的名字只用于定位，真正给用户的文件名单独生成（含清晰度、统一扩展名）
                task.filename = build_filename(
                    task.title, task.option_label, Path(filepath).suffix or ".mp4"
                )
                task.total_bytes = size
                task.downloaded_bytes = size
                task.progress = 100.0
                task.status = "finished"
                task.finished_at = time.time()
        except WatermarkError as exc:
            self._fail(task, str(exc), target_dir)
        except MediaError as exc:
            self._fail(task, str(exc), target_dir)
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            if "larger than max" in message.lower():
                message = "文件超过大小上限，请选择更低清晰度"
            self._fail(task, message, target_dir)
        except Exception as exc:  # pragma: no cover - defensive
            self._fail(task, f"下载失败：{exc}", target_dir)
        finally:
            remaining = self.active_for_ip(task.client_ip) - 1
            if remaining > 0:
                self._per_ip[task.client_ip] = remaining
            else:
                self._per_ip.pop(task.client_ip, None)

    def _download_direct(self, task: DownloadTask, target_dir: Path) -> str:
        """下载解析器给出的直链（抖音等），流式写入任务目录。"""
        url = task.direct_url
        if not url:
            raise MediaError("直链为空")
        settings = get_settings()
        path = target_dir / "source.mp4"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            **(task.direct_headers or {}),
        }

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(20.0, read=300.0),
            ) as client:
                with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length") or 0)
                    if total and total > settings.max_file_size_bytes:
                        raise MediaError("文件超过大小上限")
                    task.total_bytes = total or None
                    downloaded = 0
                    started = time.monotonic()
                    last_report = started
                    with path.open("wb") as handle:
                        for chunk in response.iter_bytes(256 * 1024):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            downloaded += len(chunk)
                            task.downloaded_bytes = downloaded
                            now = time.monotonic()
                            if now - last_report >= 0.5:
                                elapsed = now - started
                                speed = downloaded / elapsed if elapsed > 0 else None
                                task.speed = speed
                                if total and speed:
                                    remaining = max(0, total - downloaded)
                                    task.eta = int(remaining / speed)
                                    task.progress = min(
                                        99.0, round(downloaded / total * 100, 2)
                                    )
                                last_report = now
                    task.downloaded_bytes = downloaded
                    task.speed = None
                    task.eta = None
                    if total and downloaded < total:
                        raise MediaError(f"下载不完整（{downloaded}/{total} 字节）")
        except httpx.HTTPError as exc:
            path.unlink(missing_ok=True)
            raise MediaError(f"直链下载失败：{exc}") from exc
        except MediaError:
            path.unlink(missing_ok=True)
            raise

        if not path.exists() or path.stat().st_size == 0:
            raise MediaError("直链下载完成但没有文件")
        return str(path)

    def _download_sync(self, task: DownloadTask, ydl_opts: dict[str, Any]) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(task.url, download=True)

    def _ensure_playable(self, filepath: str, target_dir: Path) -> str:
        """把 flv 等容器无损重新封装为 MP4，供浏览器在线播放。"""
        path = Path(filepath)
        if path.suffix.lower() in _PLAYABLE_SUFFIXES:
            return filepath
        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            return filepath

        converted = target_dir / "preview.mp4"
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0?",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(converted),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError):
            return filepath
        if result.returncode != 0 or not converted.exists() or converted.stat().st_size == 0:
            converted.unlink(missing_ok=True)
            return filepath
        path.unlink(missing_ok=True)
        return str(converted)

    def _extract_filepath(self, info: dict[str, Any]) -> str | None:
        downloads = info.get("requested_downloads") or []
        for entry in downloads:
            if entry.get("filepath"):
                return entry["filepath"]
        return info.get("filepath") or info.get("_filename")

    def _fail(self, task: DownloadTask, message: str, target_dir: Path) -> None:
        task.status = "error"
        task.error = message
        task.finished_at = time.time()
        shutil.rmtree(target_dir, ignore_errors=True)

    # ---- cleanup ----
    def begin_serve(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.serving += 1

    def end_serve(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None and task.serving > 0:
            task.serving -= 1

    def purge_expired(self) -> int:
        now = time.time()
        removed = 0
        for task in list(self._tasks.values()):
            if task.finished_at is None or task.serving > 0:
                continue
            if now - task.finished_at < task.ttl_seconds:
                continue
            self.discard(task.id)
            removed += 1
        return removed

    def discard(self, task_id: str) -> None:
        task = self._tasks.pop(task_id, None)
        if task and task.filepath:
            path = Path(task.filepath)
            shutil.rmtree(path.parent, ignore_errors=True)
        else:
            shutil.rmtree(get_settings().download_dir / task_id, ignore_errors=True)


manager = TaskManager()
