from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VDS_", env_file=".env", extra="ignore")

    download_dir: Path = ROOT_DIR / "runtime" / "downloads"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"

    # 存储策略：完成后保留时长 / 单文件大小上限
    file_ttl_seconds: int = 3600
    # 「下载到本地」模式：合并完成后暂存多久（浏览器从这里取走文件，随后自动清理）
    local_file_ttl_seconds: int = 900
    max_file_size_bytes: int = 2 * 1024**3

    # 并发控制
    max_concurrent_per_ip: int = 3
    max_concurrent_total: int = 8

    # 频率限制（每分钟）
    probe_rate_limit_per_minute: int = 20
    download_rate_limit_per_minute: int = 30

    # 缓存与有效期
    probe_cache_ttl_seconds: int = 1200
    direct_link_ttl_seconds: int = 1800

    cleanup_interval_seconds: int = 300

    cors_origins: list[str] = ["*"]

    def ensure_dirs(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def resolve_ffmpeg() -> str | None:
    """优先用系统 ffmpeg，缺失时回退到 imageio-ffmpeg 自带二进制。"""
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
