from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import Headers, MutableHeaders

from app.api import download, preview, probe, qa, stream, summary
from app.config import get_settings, resolve_ffmpeg
from app.membership import auth, billing
from app.membership.config import settings as membership_settings
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
    membership_worker = (
        asyncio.create_task(billing.maintenance(), name="vds-membership")
        if membership_settings().enabled else None
    )
    summary_manager.start_cleanup()
    try:
        yield
    finally:
        task.cancel()
        summary_manager.stop_cleanup()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if membership_worker:
            membership_worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await membership_worker


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
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(billing.webhook_router)

MEMBERSHIP_PATHS = ("/api/account/", "/api/billing/", "/api/payment/")


class MembershipNoStore:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(MEMBERSHIP_PATHS):
            await self.app(scope, receive, send)
            return
        if membership_settings().stripe_mode == "mock":
            peer = scope.get("client") or ("", 0)
            try:
                host = urlsplit("//" + Headers(scope=scope).get("host", "")).hostname
            except ValueError:
                host = None
            if peer[0] not in {"127.0.0.1", "::1"} or host not in {"127.0.0.1", "localhost", "::1"}:
                await JSONResponse({"detail": "模拟支付只能通过本机访问"}, status_code=404)(scope, receive, send)
                return

        async def send_private(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_private)


app.add_middleware(MembershipNoStore)


@app.exception_handler(RequestValidationError)
async def membership_input_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(MEMBERSHIP_PATHS):
        return JSONResponse({"detail": "请检查邮箱、密码长度或请求参数"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(SQLAlchemyError)
async def membership_db_error(_request, exc):
    logger.warning("会员存储暂不可用，错误类型=%s", type(exc).__name__)
    return JSONResponse({"detail": "会员存储暂不可用，请稍后重试"}, status_code=503)


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
