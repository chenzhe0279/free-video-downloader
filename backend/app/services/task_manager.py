from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp

from app.config import get_settings, resolve_ffmpeg
from app.services.ytdlp_service import YtdlpError, probe

_SAFE_NAME = re.compile(r"[^\w\-. ()\[\]\u4e00-\u9fa5]+")


def _safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", name).strip(" .")
    return (cleaned or "video")[:120]


@dataclass
class DownloadTask:
    id: str
    url: str
    option_id: str
    selector: str
    audio_only: bool
    client_ip: str
    title: str = ""
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

    def all_tasks(self) -> list[DownloadTask]:
        return list(self._tasks.values())

    # ---- lifecycle ----
    async def start(self, url: str, option_id: str, client_ip: str) -> DownloadTask:
        normalized = await probe(url)
        option = next((o for o in normalized["options"] if o["id"] == option_id), None)
        if option is None:
            raise YtdlpError(f"未找到格式选项：{option_id}")

        task = DownloadTask(
            id=uuid.uuid4().hex[:16],
            url=url,
            option_id=option_id,
            selector=option["selector"],
            audio_only=bool(option["audio_only"]),
            client_ip=client_ip,
            title=normalized["title"],
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
                info = await asyncio.to_thread(self._download_sync, task, ydl_opts)
            filepath = self._extract_filepath(info)
            if not filepath or not os.path.exists(filepath):
                raise YtdlpError("下载完成但未找到文件")

            size = os.path.getsize(filepath)
            if size > settings.max_file_size_bytes:
                os.remove(filepath)
                raise YtdlpError(
                    f"文件超过大小上限（{size / 1024**3:.2f}GB > "
                    f"{settings.max_file_size_bytes / 1024**3:.0f}GB）"
                )

            task.filepath = filepath
            task.filename = _safe_filename(Path(filepath).name)
            task.total_bytes = size
            task.downloaded_bytes = size
            task.progress = 100.0
            task.status = "finished"
            task.finished_at = time.time()
        except YtdlpError as exc:
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

    def _download_sync(self, task: DownloadTask, ydl_opts: dict[str, Any]) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(task.url, download=True)

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
    def purge_expired(self) -> int:
        settings = get_settings()
        now = time.time()
        removed = 0
        for task in list(self._tasks.values()):
            if task.finished_at is None:
                continue
            if now - task.finished_at < settings.file_ttl_seconds:
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
