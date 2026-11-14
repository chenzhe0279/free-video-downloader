from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services import media
from app.services.media import MediaError
from app.services.summary import asr, source, subtitles, summarizer
from app.services.summary.deepseek import DeepSeekClient, DeepSeekError
from app.services.summary.errors import (
    SummaryBusyError,
    SummaryDisabledError,
    SummaryError,
    SummaryQuotaError,
    SummaryValidationError,
)
from app.services.summary.schemas import (
    SummaryPayload,
    SummaryStats,
    SummaryTaskStatus,
    SummaryTranscriptResponse,
    TranscriptResult,
    TranscriptSegment,
)
from app.services.summary.settings import SummarySettings, get_summary_settings

logger = logging.getLogger("vds.summary.tasks")


@dataclass
class SummaryTask:
    id: str
    url: str
    client_ip: str
    force: bool = False
    title: str = ""
    duration: float | None = None
    platform: str | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    video_id: str = ""
    status: str = "queued"
    stage: str = "排队中"
    message: str | None = None
    progress: float = 0.0
    transcript_source: str | None = None
    transcript_language: str | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    summary: SummaryPayload | None = None
    error: str | None = None
    cached: bool = False
    stats: SummaryStats = field(default_factory=SummaryStats)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    ttl_seconds: int = 1800
    cancel_requested: bool = False
    slot_released: bool = False
    directory: Path | None = None
    runner: asyncio.Task | None = None


@dataclass
class CacheEntry:
    key: str
    summary: SummaryPayload
    segments: list[TranscriptSegment]
    source: str
    language: str | None
    meta: dict[str, Any]
    stats: SummaryStats
    expires_at: float


class SummaryTaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, SummaryTask] = {}
        self._per_ip: dict[str, int] = {}
        self._daily: dict[str, int] = {}
        self._daily_date: date | None = None
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(get_summary_settings().summary_max_concurrent)
        self._cleanup_task: asyncio.Task | None = None

    # ---- settings / cache ----
    @staticmethod
    def _settings() -> SummarySettings:
        return get_summary_settings()

    @staticmethod
    def _cache_key(normalized: dict[str, Any]) -> str:
        settings = get_summary_settings()
        platform = str(normalized.get("platform") or "unknown")
        video_id = str(normalized.get("id") or "")
        if not video_id or video_id == "video":
            video_id = str(normalized.get("url") or "")
        return (
            f"{settings.summary_prompt_version}:"
            f"{settings.deepseek_model}:{platform}:{video_id}"
        )

    def _evict_cache(self) -> None:
        settings = self._settings()
        now = time.time()
        for key in list(self._cache):
            if self._cache[key].expires_at <= now:
                self._cache.pop(key, None)
        while len(self._cache) > settings.summary_cache_max_entries:
            self._cache.popitem(last=False)

    def _get_cached(self, key: str) -> CacheEntry | None:
        self._evict_cache()
        entry = self._cache.get(key)
        if entry is None:
            return None
        self._cache.move_to_end(key)
        return entry

    def _put_cache(
        self,
        key: str,
        task: SummaryTask,
        normalized: dict[str, Any],
    ) -> None:
        if task.summary is None:
            return
        settings = self._settings()
        self._evict_cache()
        self._cache[key] = CacheEntry(
            key=key,
            summary=task.summary.model_copy(deep=True),
            segments=[segment.model_copy() for segment in task.segments],
            source=task.transcript_source or "asr",
            language=task.transcript_language,
            meta={
                "title": task.title,
                "duration": task.duration,
                "platform": task.platform,
                "thumbnail": task.thumbnail,
                "uploader": task.uploader,
                "url": task.url,
                "video_id": task.video_id,
            },
            stats=task.stats.model_copy(deep=True),
            expires_at=time.time() + settings.summary_cache_ttl_seconds,
        )
        self._cache.move_to_end(key)
        while len(self._cache) > settings.summary_cache_max_entries:
            self._cache.popitem(last=False)

    def _task_from_cache(
        self,
        url: str,
        client_ip: str,
        entry: CacheEntry,
    ) -> SummaryTask:
        settings = self._settings()
        task = SummaryTask(
            id=uuid.uuid4().hex[:16],
            url=url,
            client_ip=client_ip,
            title=str(entry.meta.get("title") or ""),
            duration=entry.meta.get("duration"),
            platform=entry.meta.get("platform"),
            thumbnail=entry.meta.get("thumbnail"),
            uploader=entry.meta.get("uploader"),
            video_id=str(entry.meta.get("video_id") or ""),
            status="finished",
            stage="已完成（缓存）",
            progress=100.0,
            transcript_source=entry.source,  # type: ignore[assignment]
            transcript_language=entry.language,
            segments=[segment.model_copy() for segment in entry.segments],
            summary=entry.summary.model_copy(deep=True),
            cached=True,
            stats=entry.stats.model_copy(deep=True),
            finished_at=time.time(),
            ttl_seconds=settings.summary_task_ttl_seconds,
        )
        task.stats.cached = True
        self._tasks[task.id] = task
        return task

    # ---- capacity / quota ----
    def _active_for_ip(self, client_ip: str) -> int:
        return self._per_ip.get(client_ip, 0)

    def _check_daily(self, client_ip: str, settings: SummarySettings) -> None:
        today = date.today()
        if self._daily_date != today:
            self._daily_date = today
            self._daily.clear()
        limit = settings.summary_daily_limit_per_ip
        if limit > 0 and self._daily.get(client_ip, 0) >= limit:
            raise SummaryQuotaError(
                f"今日 AI 总结次数已达上限（{limit} 次），请明天再试或调高 "
                "VDS_SUMMARY_DAILY_LIMIT_PER_IP"
            )

    def _increment_daily(self, client_ip: str) -> None:
        self._daily[client_ip] = self._daily.get(client_ip, 0) + 1

    def _release_slot(self, task: SummaryTask) -> None:
        if task.slot_released:
            return
        task.slot_released = True
        remaining = self._per_ip.get(task.client_ip, 0) - 1
        if remaining > 0:
            self._per_ip[task.client_ip] = remaining
        else:
            self._per_ip.pop(task.client_ip, None)

    # ---- public API ----
    def get(self, task_id: str) -> SummaryTask | None:
        return self._tasks.get(task_id)

    def touch(self, task_id: str) -> SummaryTask | None:
        """问答等后续操作时滑动延长已完成的总结任务 TTL。"""
        task = self._tasks.get(task_id)
        if task is not None and task.status == "finished":
            task.finished_at = time.time()
        return task

    async def create(
        self,
        url: str,
        client_ip: str,
        *,
        force: bool = False,
    ) -> tuple[SummaryTask, bool]:
        settings = self._settings()
        if not settings.enabled:
            raise SummaryDisabledError(
                "AI 视频总结未启用，请在 backend/.env 配置 VDS_DEEPSEEK_API_KEY 后重启后端"
            )
        try:
            normalized = await media.probe(url)
        except MediaError as exc:
            raise SummaryValidationError(str(exc)) from exc

        if normalized.get("is_playlist"):
            raise SummaryValidationError("暂不支持合集/播放列表，请粘贴单个视频链接")
        duration = normalized.get("duration")
        try:
            duration_value = float(duration) if duration is not None else 0.0
        except (TypeError, ValueError):
            duration_value = 0.0
        if duration_value <= 0:
            raise SummaryValidationError("无法确定视频时长，直播或时长未知的视频暂不支持 AI 总结")
        if duration_value > settings.summary_max_duration_seconds:
            limit_minutes = settings.summary_max_duration_seconds // 60
            actual_minutes = round(duration_value / 60, 1)
            raise SummaryValidationError(
                f"视频约 {actual_minutes} 分钟，超过 AI 总结上限 {limit_minutes} 分钟；"
                "可调高 VDS_SUMMARY_MAX_DURATION_SECONDS 后重启后端"
            )

        cache_key = self._cache_key(normalized)
        if not force:
            cached = self._get_cached(cache_key)
            if cached is not None:
                logger.info("summary cache hit: %s", cache_key)
                return self._task_from_cache(url, client_ip, cached), True

        async with self._lock:
            if self._active_for_ip(client_ip) >= settings.summary_max_concurrent_per_ip:
                raise SummaryBusyError(
                    f"同时进行的 AI 总结任务已达上限"
                    f"（{settings.summary_max_concurrent_per_ip} 个），请稍后再试"
                )
            self._check_daily(client_ip, settings)

            task = SummaryTask(
                id=uuid.uuid4().hex[:16],
                url=url,
                client_ip=client_ip,
                force=force,
                title=str(normalized.get("title") or ""),
                duration=duration_value,
                platform=normalized.get("platform"),
                thumbnail=normalized.get("thumbnail"),
                uploader=normalized.get("uploader"),
                video_id=str(normalized.get("id") or ""),
                ttl_seconds=settings.summary_task_ttl_seconds,
            )
            self._tasks[task.id] = task
            self._per_ip[client_ip] = self._active_for_ip(client_ip) + 1
            self._increment_daily(client_ip)
            task.runner = asyncio.create_task(
                self._run(task, normalized),
                name=f"vds-summary-{task.id}",
            )
            return task, False

    def delete(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.cancel_requested = True
        if task.runner is not None and not task.runner.done():
            task.runner.cancel()
        self._tasks.pop(task_id, None)
        if task.status in {"queued", "fetching", "transcribing", "summarizing"}:
            task.status = "cancelled"
            task.stage = "已取消"
            task.message = "任务已取消"
            task.finished_at = time.time()
        self._release_slot(task)
        if task.directory is not None:
            shutil.rmtree(task.directory, ignore_errors=True)
        return True

    def serialize(self, task: SummaryTask) -> SummaryTaskStatus:
        expires_in = None
        if task.status == "finished" and task.finished_at is not None:
            expires_in = max(
                0,
                int(task.ttl_seconds - (time.time() - task.finished_at)),
            )
        return SummaryTaskStatus(
            task_id=task.id,
            status=task.status,  # type: ignore[arg-type]
            stage=task.stage,
            progress=round(task.progress, 2),
            message=task.message,
            title=task.title,
            duration=task.duration,
            platform=task.platform,
            thumbnail=task.thumbnail,
            uploader=task.uploader,
            cached=task.cached,
            transcript_source=task.transcript_source,  # type: ignore[arg-type]
            transcript_language=task.transcript_language,
            stats=task.stats.model_copy(),
            summary=task.summary,
            error=task.error,
            expires_in=expires_in,
        )

    def transcript(self, task: SummaryTask) -> SummaryTranscriptResponse:
        return SummaryTranscriptResponse(
            task_id=task.id,
            source=task.transcript_source,  # type: ignore[arg-type]
            language=task.transcript_language,
            segments=task.segments,
        )

    # ---- lifecycle ----
    def _update(
        self,
        task: SummaryTask,
        status: str,
        stage: str,
        progress: float,
        message: str | None = None,
    ) -> None:
        task.status = status
        task.stage = stage
        task.progress = max(0.0, min(100.0, float(progress)))
        task.message = message

    @staticmethod
    def _check_cancel(task: SummaryTask) -> None:
        if task.cancel_requested:
            raise asyncio.CancelledError()

    async def _run(
        self,
        task: SummaryTask,
        normalized: dict[str, Any],
    ) -> None:
        settings = self._settings()
        started = time.monotonic()
        target_dir = get_settings().download_dir / "summary" / task.id
        task.directory = target_dir
        try:
            async with self._semaphore:
                self._check_cancel(task)
                self._update(task, "fetching", "准备总结", 3, "正在解析视频信息…")
                transcript = await self._acquire_transcript(
                    task, normalized, target_dir, settings
                )
                self._check_cancel(task)

                task.transcript_source = transcript.source
                task.transcript_language = transcript.language
                task.segments = [segment.model_copy() for segment in transcript.segments]
                chars = sum(len(segment.text) for segment in task.segments)
                asr_cost = None
                if transcript.asr_seconds > 0:
                    asr_cost = round(
                        transcript.asr_seconds / 3600 * settings.summary_asr_price_per_hour_cny,
                        4,
                    )
                task.stats = SummaryStats(
                    chunks=transcript.chunks,
                    asr_seconds=transcript.asr_seconds,
                    transcript_chars=chars,
                    segments=len(task.segments),
                    model=settings.deepseek_model,
                    cached=False,
                    asr_cost_estimate_cny=asr_cost,
                )

                self._check_cancel(task)
                self._update(task, "summarizing", "生成总结", 85, "正在生成结构化总结…")
                client = DeepSeekClient(settings)
                try:
                    payload, usage = await summarizer.summarize(
                        client,
                        normalized,
                        transcript,
                        settings,
                        progress_callback=lambda message: self._update(
                            task, "summarizing", "生成总结", 92, message
                        ),
                    )
                finally:
                    await client.aclose()
                self._check_cancel(task)

                task.summary = payload
                task.stats.elapsed_seconds = round(time.monotonic() - started, 2)
                task.status = "finished"
                task.stage = "已完成"
                task.progress = 100.0
                task.message = None
                task.finished_at = time.time()
                task.cached = False
                self._put_cache(self._cache_key(normalized), task, normalized)
                logger.info(
                    "summary task %s finished in %.1fs (chunks=%s, source=%s, tokens=%s)",
                    task.id,
                    task.stats.elapsed_seconds,
                    task.stats.chunks,
                    task.transcript_source,
                    (usage.get("usage") or {}).get("total_tokens"),
                )
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.stage = "已取消"
            task.message = "任务已取消"
            task.finished_at = time.time()
        except (SummaryError, source.SourceError, asr.AsrError, DeepSeekError, MediaError) as exc:
            task.status = "error"
            task.stage = "总结失败"
            task.error = str(exc)
            task.message = None
            task.finished_at = time.time()
            logger.warning("summary task %s failed: %s", task.id, exc)
        except Exception as exc:  # pragma: no cover - defensive
            task.status = "error"
            task.stage = "总结失败"
            task.error = f"总结失败：{exc}"
            task.message = None
            task.finished_at = time.time()
            logger.exception("summary task %s crashed", task.id)
        finally:
            if task.summary is not None and task.status == "finished":
                task.stats.elapsed_seconds = round(time.monotonic() - started, 2)
            shutil.rmtree(target_dir, ignore_errors=True)
            task.directory = None
            self._release_slot(task)

    async def _acquire_transcript(
        self,
        task: SummaryTask,
        normalized: dict[str, Any],
        target_dir: Path,
        settings: SummarySettings,
    ) -> TranscriptResult:
        url = task.url
        if str(normalized.get("platform") or "").lower() == "douyin":
            return await self._douyin_transcript(task, normalized, target_dir, settings)

        info = await source.raw_info(url)
        if info.get("is_live"):
            raise SummaryValidationError("直播暂不支持 AI 总结，请在直播结束后再试")
        self._update(task, "fetching", "获取字幕", 8, "正在检查平台字幕…")

        picked = subtitles.pick_subtitle(info)
        if picked is not None:
            language, entry = picked
            try:
                text = await source.fetch_text(
                    str(entry.get("url") or ""),
                    video_url=url,
                )
                segments = subtitles.parse_subtitle(text, str(entry.get("ext") or ""))
                if len(segments) > 0 and subtitles.transcript_chars(segments) >= 20:
                    self._update(
                        task,
                        "fetching",
                        "获取字幕",
                        28,
                        f"已获取平台字幕（{language}）",
                    )
                    return TranscriptResult(
                        source="subtitle",
                        language=language,
                        segments=segments,
                        asr_seconds=0,
                        chunks=0,
                    )
                logger.info("字幕内容过短，回退 ASR：%s", language)
            except (source.SourceError, ValueError) as exc:
                logger.info("字幕不可用，回退 ASR：%s", exc)

        self._update(task, "fetching", "下载音频", 12, "正在下载音频用于语音识别…")
        audio_path = await source.download_audio(
            url,
            target_dir,
            settings.summary_max_audio_bytes,
        )
        self._check_cancel(task)
        duration = normalized.get("duration") or info.get("duration")
        return await self._transcribe_audio_file(
            task, audio_path, duration, target_dir, settings
        )

    async def _douyin_transcript(
        self,
        task: SummaryTask,
        normalized: dict[str, Any],
        target_dir: Path,
        settings: SummarySettings,
    ) -> TranscriptResult:
        options = normalized.get("options") or []
        option = options[0] if options else {}
        direct_url = str(option.get("direct_url") or "")
        headers = option.get("headers") or {}
        if not direct_url:
            raise SummaryValidationError("抖音视频没有可用的无水印地址，无法总结")
        self._update(task, "fetching", "下载视频", 12, "正在下载抖音视频用于语音识别…")
        video_path = await source.download_douyin_video(
            direct_url,
            headers,
            target_dir,
            settings.summary_max_audio_bytes,
        )
        self._check_cancel(task)
        return await self._transcribe_audio_file(
            task, video_path, task.duration, target_dir, settings
        )

    async def _transcribe_audio_file(
        self,
        task: SummaryTask,
        audio_path: Path,
        duration: float | None,
        target_dir: Path,
        settings: SummarySettings,
    ) -> TranscriptResult:
        self._update(task, "transcribing", "切分音频", 20, "正在切分音频…")
        chunks = await asr.split_audio(
            audio_path,
            target_dir,
            duration,
            settings.summary_asr_chunk_seconds,
        )
        self._check_cancel(task)
        self._update(
            task,
            "transcribing",
            "语音识别",
            30,
            f"正在识别第 1/{len(chunks)} 段音频…",
        )

        client = DeepSeekClient(settings)
        try:
            def progress(done: int, total: int, _current: int) -> None:
                ratio = done / total if total else 0
                self._update(
                    task,
                    "transcribing",
                    "语音识别",
                    30 + 50 * ratio,
                    f"正在识别第 {done}/{total} 段音频…",
                )

            segments, asr_seconds = await asr.transcribe_chunks(
                chunks,
                client,
                concurrency=settings.summary_asr_concurrency,
                progress_callback=progress,
            )
        finally:
            await client.aclose()
        self._check_cancel(task)
        return TranscriptResult(
            source="asr",
            language=None,
            segments=segments,
            asr_seconds=asr_seconds,
            chunks=len(chunks),
        )

    # ---- cleanup ----
    def purge_expired(self) -> int:
        now = time.time()
        removed = 0
        for task in list(self._tasks.values()):
            if task.finished_at is None:
                continue
            if now - task.finished_at < task.ttl_seconds:
                continue
            self._tasks.pop(task.id, None)
            self._release_slot(task)
            if task.directory is not None:
                shutil.rmtree(task.directory, ignore_errors=True)
            removed += 1
        self._evict_cache()
        return removed

    async def cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(300)
                removed = self.purge_expired()
                if removed:
                    logger.info("清理 AI 总结任务：%d 个", removed)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - never kill the loop
                logger.exception("AI 总结清理任务异常")

    def start_cleanup(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self.cleanup_loop(), name="vds-summary-cleanup"
            )

    def stop_cleanup(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None


summary_manager = SummaryTaskManager()
