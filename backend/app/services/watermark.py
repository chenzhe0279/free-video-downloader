from __future__ import annotations

import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import resolve_ffmpeg

_PROFILES_PATH = Path(__file__).resolve().parent.parent / "data" / "watermark_profiles.json"
_VIDEO_SIZE_RE = re.compile(r"Video:.*?(\d{2,5})x(\d{2,5})")


class WatermarkError(Exception):
    pass


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, dict[str, Any]]:
    try:
        raw = _PROFILES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise WatermarkError(f"水印配置读取失败：{exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WatermarkError(f"水印配置格式错误：{exc}") from exc
    return data if isinstance(data, dict) else {}


def get_profile(video_id: str | None) -> dict[str, Any] | None:
    if not video_id:
        return None
    return _load_profiles().get(video_id)


def watermark_info(video_id: str | None) -> dict[str, Any]:
    profile = get_profile(video_id)
    if profile is None:
        return {"available": False, "label": None}
    return {"available": True, "label": profile.get("label")}


def _probe_size(ffmpeg: str, path: Path) -> tuple[int, int]:
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WatermarkError(f"读取视频信息失败：{exc}") from exc
    match = _VIDEO_SIZE_RE.search(result.stderr or "")
    if match is None:
        raise WatermarkError("无法读取视频分辨率")
    return int(match.group(1)), int(match.group(2))


def _scaled_regions(
    profile: dict[str, Any],
    width: int,
    height: int,
) -> list[tuple[int, int, int, int]]:
    reference = profile.get("reference") or [width, height]
    ref_width = int(reference[0]) or width
    ref_height = int(reference[1]) or height
    scale_x = width / ref_width
    scale_y = height / ref_height
    boxes: list[tuple[int, int, int, int]] = []
    for raw in profile.get("regions") or []:
        try:
            x, y, w, h = (int(value) for value in raw[:4])
        except (TypeError, ValueError):
            continue
        left = max(1, round(x * scale_x))
        top = max(1, round(y * scale_y))
        box_w = min(width - left - 1, max(4, round(w * scale_x)))
        box_h = min(height - top - 1, max(4, round(h * scale_y)))
        if box_w < 4 or box_h < 4:
            continue
        boxes.append((left, top, box_w, box_h))
    return boxes


def remove_watermark(src: Path, dst: Path, profile: dict[str, Any]) -> Path:
    """用 delogo 在固定区域做插值填补，输出去水印 H.264 MP4。

    说明：removelogo 的填补质量更好，但在 1080P 下比 delogo 慢约 50 倍
    （实测 68 秒视频需要十分钟以上），因此这里选择可接受的 delogo。
    """
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise WatermarkError("未找到 ffmpeg，无法去水印")

    width, height = _probe_size(ffmpeg, src)
    boxes = _scaled_regions(profile, width, height)
    if not boxes:
        raise WatermarkError("水印区域配置为空")

    filters = ",".join(
        f"delogo=x={x}:y={y}:w={w}:h={h}:show=0" for x, y, w, h in boxes
    )
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vf",
        filters,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        dst.unlink(missing_ok=True)
        raise WatermarkError(f"去水印失败：{exc}") from exc

    if result.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        dst.unlink(missing_ok=True)
        message = (result.stderr or "").strip().splitlines()
        tail = message[-1] if message else "ffmpeg 返回非零状态"
        raise WatermarkError(f"去水印失败：{tail}")

    return dst
