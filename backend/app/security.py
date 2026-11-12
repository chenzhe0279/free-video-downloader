from __future__ import annotations

import ipaddress
import socket
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class UnsafeUrlError(ValueError):
    pass


def _is_public_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(raw: str) -> str:
    """Reject anything that could be used to reach internal services (SSRF)."""
    candidate = (raw or "").strip()
    if not candidate:
        raise UnsafeUrlError("请输入视频链接")
    if len(candidate) > 2048:
        raise UnsafeUrlError("链接过长")

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("仅支持 http / https 链接")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("链接缺少域名")
    if host in BLOCKED_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeUrlError("不允许访问该地址")

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise UnsafeUrlError("域名解析失败，请检查链接") from exc

    for address in addresses:
        if not _is_public_ip(address):
            raise UnsafeUrlError("不允许访问内网地址")

    return candidate


class SlidingWindowLimiter:
    """Tiny in-memory rate limiter; no external dependency needed."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True

    def retry_after(self, key: str) -> int:
        bucket = self._hits.get(key)
        if not bucket:
            return 0
        return max(1, int(self.window - (time.monotonic() - bucket[0])))
