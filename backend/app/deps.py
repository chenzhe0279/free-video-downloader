from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import get_settings
from app.security import SlidingWindowLimiter

_settings = get_settings()

probe_limiter = SlidingWindowLimiter(_settings.probe_rate_limit_per_minute)
download_limiter = SlidingWindowLimiter(_settings.download_rate_limit_per_minute)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def enforce_rate(limiter: SlidingWindowLimiter, request: Request, label: str) -> None:
    ip = client_ip(request)
    if limiter.allow(ip):
        return
    retry_after = limiter.retry_after(ip)
    raise HTTPException(
        status_code=429,
        detail=f"{label}过于频繁，请 {retry_after} 秒后再试",
        headers={"Retry-After": str(retry_after)},
    )
