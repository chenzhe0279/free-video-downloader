from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import download, preview, probe, qa, stream, summary
from app.config import get_settings, resolve_ffmpeg
from app.services.cleanup import cleanup_loop
from app.services.summary.tasks import summary_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("vds")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    logger.info("下载目录：%s", settings.download_dir)
    logger.info("ffmpeg：%s", resolve_ffmpeg() or "未找到（高清晰度合并将不可用）")
    task = asyncio.create_task(cleanup_loop(), name="vds-cleanup")
    summary_manager.start_cleanup()
    try:
        yield
    finally:
        task.cancel()
        summary_manager.stop_cleanup()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="万能视频下载站 API",
    description="基于 yt-dlp 的多平台视频解析与下载服务",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Range", "Accept-Ranges"],
)

app.include_router(probe.router)
app.include_router(preview.router)
app.include_router(download.router)
app.include_router(stream.router)
app.include_router(summary.router)
app.include_router(qa.router)


@app.get("/api/health", tags=["meta"], summary="健康检查")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "ffmpeg": bool(resolve_ffmpeg()),
            "max_file_size_gb": round(settings.max_file_size_bytes / 1024**3, 2),
            "file_ttl_seconds": settings.file_ttl_seconds,
            "local_file_ttl_seconds": settings.local_file_ttl_seconds,
        }
    )


if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")
else:
    logger.warning("未找到前端构建产物：%s（开发模式请用 Vite dev server）", settings.frontend_dist)
