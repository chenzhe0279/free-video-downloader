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


class WatermarkInfo(BaseModel):
    available: bool = False
    label: str | None = None


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
    watermark: WatermarkInfo = Field(default_factory=WatermarkInfo)


# server：服务端转存（文件保留 1 小时）
# local：服务端合并/转码后立即传回本机，服务器只做临时中转
DownloadMode = Literal["server", "direct", "proxy", "local"]
# preview：只为「在线浏览」准备一个可播放副本，保留时长与「下载到本地」一致
TaskMode = Literal["server", "local", "preview"]


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    option_id: str = Field(..., min_length=1, max_length=64)
    mode: DownloadMode = "server"
    remove_watermark: bool = False


class TaskStatus(BaseModel):
    task_id: str
    mode: TaskMode = "server"
    status: Literal["queued", "downloading", "processing", "cleaning", "finished", "error"]
    progress: float = 0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    size: int | None = None
    download_url: str | None = None
    expires_in: int | None = None
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


class LocalStreamResponse(BaseModel):
    """单文件格式的「下载到本地」：不落盘，直接由浏览器从代理流式取回。"""

    mode: Literal["local"]
    stream_url: str
    filename: str | None = None
    expires_in: int


class PreviewRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    option_id: str = Field(..., min_length=1, max_length=64)


class PreviewResponse(BaseModel):
    """在线预览地址：

    - proxy：单文件直链，走服务端代理补全防盗链请求头，不落盘；
    - file：预览副本已在服务端就绪，可直接 Range 播放；
    - task：音视频分离，需要先由服务端合并，用 task_id 轮询进度。
    """

    mode: Literal["proxy", "file", "task"]
    preview_url: str | None = None
    task_id: str | None = None
    filename: str | None = None
    expires_in: int | None = None
