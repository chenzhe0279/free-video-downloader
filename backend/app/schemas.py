from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProbeRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)


class FormatOption(BaseModel):
    id: str
    label: str
    note: str
    height: int | None = None
    ext: str | None = None
    filesize: int | None = None
    fps: float | None = None
    progressive: bool
    direct_format_id: str | None = None
    audio_only: bool = False


class ProbeResponse(BaseModel):
    id: str
    url: str
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    platform: str | None = None
    is_playlist: bool = False
    entry_count: int | None = None
    options: list[FormatOption]
    subtitles: list[str] = []


DownloadMode = Literal["server", "direct", "proxy"]


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    option_id: str = Field(..., min_length=1, max_length=64)
    mode: DownloadMode = "server"


class TaskStatus(BaseModel):
    task_id: str
    status: Literal["queued", "downloading", "processing", "finished", "error"]
    progress: float = 0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    size: int | None = None
    download_url: str | None = None
    error: str | None = None


class DirectLinkResponse(BaseModel):
    mode: Literal["direct"]
    url: str
    filename: str | None = None
    expires_in: int


class ProxyLinkResponse(BaseModel):
    mode: Literal["proxy"]
    proxy_url: str
    filename: str | None = None
    expires_in: int
