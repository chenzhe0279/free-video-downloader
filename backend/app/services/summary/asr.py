from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import resolve_ffmpeg
from app.services.summary.deepseek import DeepSeekClient, DeepSeekError
from app.services.summary.schemas import TranscriptSegment

_ASR_MAX_BYTES = 8 * 1024 * 1024
_WHITESPACE_RE = re.compile(r"\s+")


class AsrError(Exception):
    pass


@dataclass
class AsrChunk:
    index: int
    start_seconds: float
    end_seconds: float | None
    path: Path
    content_type: str


def _run_ffmpeg(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsrError(f"ffmpeg 执行失败：{exc}") from exc


def _last_error_line(result: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "ffmpeg 返回非零状态"


def _split_sync(
    audio_path: Path,
    target_dir: Path,
    duration: float | None,
    chunk_seconds: int,
) -> list[AsrChunk]:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise AsrError("未找到 ffmpeg，无法处理音频")
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        raise AsrError("音频文件不存在或为空")

    target_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(target_dir / "chunk_%03d.ogg")
    common_tail = [
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-reset_timestamps",
        "1",
    ]
    opus_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "libopus",
        "-b:a",
        "48k",
        *common_tail,
        output_pattern,
    ]
    result = _run_ffmpeg(opus_cmd)
    files = sorted(target_dir.glob("chunk_*.ogg"))
    content_type = "audio/ogg"
    suffix = ".ogg"

    if result.returncode != 0 or not files:
        for stale in target_dir.glob("chunk_*.ogg"):
            stale.unlink(missing_ok=True)
        wav_pattern = str(target_dir / "chunk_%03d.wav")
        wav_cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            *common_tail,
            wav_pattern,
        ]
        result = _run_ffmpeg(wav_cmd)
        files = sorted(target_dir.glob("chunk_*.wav"))
        content_type = "audio/wav"
        suffix = ".wav"

    if result.returncode != 0 or not files:
        raise AsrError(f"音频分片失败：{_last_error_line(result)}")

    chunks: list[AsrChunk] = []
    for index, path in enumerate(files):
        size = path.stat().st_size
        if size <= 512:
            continue
        if size > _ASR_MAX_BYTES:
            raise AsrError("单个音频分片超过 AI 服务 8 MiB 限制")
        start = float(index * chunk_seconds)
        end = (
            min(start + chunk_seconds, float(duration))
            if duration and duration > 0
            else None
        )
        if end is not None and end - start < 0.5:
            continue
        chunks.append(
            AsrChunk(
                index=index,
                start_seconds=start,
                end_seconds=end,
                path=Path(str(path)),
                content_type=content_type,
            )
        )
    if not chunks:
        raise AsrError("音频分片为空，视频可能没有音轨")
    # 保证路径扩展名与 content_type 一致（ffmpeg 模板已保证，这里只做防御）
    for chunk in chunks:
        if chunk.path.suffix != suffix:  # pragma: no cover - defensive
            raise AsrError("音频分片格式不一致")
    return chunks


async def split_audio(
    audio_path: Path,
    target_dir: Path,
    duration: float | None,
    chunk_seconds: int,
) -> list[AsrChunk]:
    return await asyncio.to_thread(
        _split_sync, audio_path, target_dir, duration, chunk_seconds
    )


def _convert_to_wav_sync(source: Path) -> Path:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise AsrError("未找到 ffmpeg，无法转换音频")
    target = source.with_suffix(".wav")
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    result = _run_ffmpeg(cmd, timeout=300)
    if result.returncode != 0 or not target.exists() or target.stat().st_size <= 0:
        raise AsrError(f"音频转 WAV 失败：{_last_error_line(result)}")
    return target


async def _transcribe_one(
    chunk: AsrChunk,
    client: DeepSeekClient,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        try:
            return await client.transcribe(chunk.path, content_type=chunk.content_type)
        except DeepSeekError as exc:
            # 少数环境可能不接受 Ogg Opus；按官方支持的 WAV 再试一次
            if exc.status_code == 400 and chunk.path.suffix.lower() != ".wav":
                wav_path = await asyncio.to_thread(_convert_to_wav_sync, chunk.path)
                return await client.transcribe(wav_path, content_type="audio/wav")
            raise


ProgressCallback = Callable[[int, int, int], None]


async def transcribe_chunks(
    chunks: list[AsrChunk],
    client: DeepSeekClient,
    *,
    concurrency: int = 4,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[TranscriptSegment], float]:
    """并发识别分片并合并为按时间排序的逐字稿。

    Returns:
        ``(segments, asr_seconds)``；``asr_seconds`` 用于费用估算。
    """
    if not chunks:
        raise AsrError("没有可识别的音频分片")

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[int, dict] = {}
    done = 0

    async def _worker(chunk: AsrChunk) -> None:
        nonlocal done
        result = await _transcribe_one(chunk, client, semaphore)
        results[chunk.index] = result
        done += 1
        if progress_callback is not None:
            try:
                progress_callback(done, len(chunks), chunk.index + 1)
            except Exception:  # pragma: no cover - 进度回调不应影响主流程
                pass

    tasks = [asyncio.create_task(_worker(chunk)) for chunk in chunks]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    segments: list[TranscriptSegment] = []
    asr_seconds = 0.0
    for chunk in chunks:
        payload = results.get(chunk.index) or {}
        text = _WHITESPACE_RE.sub(" ", str(payload.get("text") or "")).strip()
        try:
            duration_ms = int(payload.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        if duration_ms > 0:
            chunk_duration = duration_ms / 1000
            asr_seconds += chunk_duration
            end = chunk.start_seconds + chunk_duration
        else:
            chunk_duration = (
                (chunk.end_seconds - chunk.start_seconds)
                if chunk.end_seconds is not None
                else 0
            )
            asr_seconds += max(0.0, chunk_duration)
            end = chunk.end_seconds
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=chunk.start_seconds,
                end_seconds=end,
                text=text,
            )
        )

    if not segments:
        raise AsrError("未识别到语音内容，可能是纯音乐或无对白视频")
    return segments, round(asr_seconds, 2)
