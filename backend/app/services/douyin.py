from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
TTWID_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
TTWID_PAYLOAD = {
    "region": "cn",
    "aid": 1768,
    "needFid": False,
    "service": "www.ixigua.com",
    "migrate_info": {"ticket": "", "source": "node"},
    "cbUrlProtocol": "https",
    "union": True,
}
SHARE_PAGE = "https://www.iesdouyin.com/share/video/{aweme_id}/"
DOWNLOAD_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Referer": "https://www.douyin.com/",
}
_TTWID_TTL = 12 * 3600
_ITEM_TTL = 1200
_ID_RE = re.compile(r"\d{8,24}")

_ttwid_lock = threading.Lock()
_ttwid_cache: tuple[str, float] | None = None
_item_lock = threading.Lock()
_item_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class DouyinError(Exception):
    pass


def is_douyin_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return (
        host == "douyin.com"
        or host.endswith(".douyin.com")
        or host == "iesdouyin.com"
        or host.endswith(".iesdouyin.com")
    )


def _extract_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("modal_id", "item_ids", "aweme_id", "group_id"):
        for value in query.get(key, []):
            match = _ID_RE.search(value)
            if match:
                return match.group(0)
    for pattern in (
        r"/video/(\d{8,24})",
        r"/note/(\d{8,24})",
        r"/share/video/(\d{8,24})",
        r"/(\d{8,24})(?:/|$)",
    ):
        match = re.search(pattern, parsed.path or "")
        if match:
            return match.group(1)
    match = re.search(r"(?:modal_id|aweme_id|item_ids|group_id)=(\d{8,24})", url)
    return match.group(1) if match else None


def extract_aweme_id(url: str) -> str:
    candidate = (url or "").strip()
    if re.fullmatch(r"\d{8,24}", candidate):
        return candidate

    video_id = _extract_from_url(candidate)
    if video_id:
        return video_id

    host = (urlparse(candidate).hostname or "").lower()
    if host.endswith("v.douyin.com"):
        try:
            with httpx.Client(
                headers={"User-Agent": MOBILE_UA},
                follow_redirects=True,
                timeout=20,
            ) as client:
                response = client.get(candidate)
            video_id = _extract_from_url(str(response.url))
            if video_id:
                return video_id
            for pattern in (
                r"(?:modal_id|aweme_id|itemId)\"?\s*[:=]\s*\"?(\d{8,24})",
                r"\b(\d{8,24})\b",
            ):
                match = re.search(pattern, response.text or "")
                if match:
                    return match.group(1)
        except httpx.HTTPError as exc:
            raise DouyinError(f"抖音短链解析失败：{exc}") from exc

    raise DouyinError("无法从链接中识别抖音视频 ID")


def _get_ttwid(force: bool = False) -> str:
    global _ttwid_cache
    with _ttwid_lock:
        if not force and _ttwid_cache and time.time() < _ttwid_cache[1]:
            return _ttwid_cache[0]
        try:
            with httpx.Client(
                headers={"User-Agent": MOBILE_UA},
                follow_redirects=True,
                timeout=20,
            ) as client:
                response = client.post(TTWID_URL, json=TTWID_PAYLOAD)
                response.raise_for_status()
                token = client.cookies.get("ttwid")
                if not token:
                    for header in response.headers.get_list("set-cookie"):
                        match = re.search(r"(?:^|,\s*)ttwid=([^;]+)", header)
                        if match:
                            token = match.group(1)
                            break
        except httpx.HTTPError as exc:
            raise DouyinError(f"抖音匿名校验初始化失败：{exc}") from exc

        if not token:
            raise DouyinError("抖音匿名校验初始化失败")
        _ttwid_cache = (token, time.time() + _TTWID_TTL)
        return token


def _decode_b64url(value: str) -> bytes:
    normalized = value.replace("-", "+").replace("_", "/")
    normalized += "=" * (-len(normalized) % 4)
    return base64.b64decode(normalized)


def _is_waf_challenge(html: str) -> bool:
    return "Please wait..." in html and "wci=" in html and "cs=" in html


def _solve_waf_challenge(client: httpx.Client, html: str, page_url: str) -> bool:
    """Solve Douyin's JS WAF proof-of-work challenge.

    Adapted from rathodpratham-dev/douyin_video_downloader (MIT).
    """
    match = re.search(r'wci="([^"]+)"\s*,\s*cs="([^"]+)"', html)
    if not match:
        return False
    cookie_name, challenge_blob = match.groups()
    try:
        challenge = json.loads(_decode_b64url(challenge_blob).decode("utf-8"))
        prefix = _decode_b64url(challenge["v"]["a"])
        expected = _decode_b64url(challenge["v"]["c"]).hex()
    except (KeyError, ValueError, TypeError):
        return False

    solved: int | None = None
    for candidate in range(1_000_001):
        digest = hashlib.sha256(prefix + str(candidate).encode("utf-8")).hexdigest()
        if digest == expected:
            solved = candidate
            break
    if solved is None:
        return False

    challenge["d"] = base64.b64encode(str(solved).encode("utf-8")).decode("utf-8")
    cookie_value = base64.b64encode(
        json.dumps(challenge, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8")
    domain = urlparse(page_url).hostname or "www.iesdouyin.com"
    client.cookies.set(cookie_name, cookie_value, domain=domain, path="/")
    return True


def _extract_router_data(html: str) -> dict[str, Any]:
    marker = re.search(r"window\._ROUTER_DATA\s*=\s*", html)
    if not marker:
        return {}
    start = marker.end()
    while start < len(html) and html[start].isspace():
        start += 1
    if start >= len(html) or html[start] != "{":
        return {}

    depth = 0
    in_string = False
    escaped = False
    for cursor in range(start, len(html)):
        char = html[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : cursor + 1])
                except ValueError:
                    return {}
    return {}


def _find_item(router_data: dict[str, Any]) -> dict[str, Any]:
    loader = router_data.get("loaderData") or {}
    if not isinstance(loader, dict):
        return {}
    for node in loader.values():
        if not isinstance(node, dict):
            continue
        video_info = node.get("videoInfoRes")
        if not isinstance(video_info, dict):
            continue
        items = video_info.get("item_list") or []
        if items and isinstance(items[0], dict):
            return items[0]
    return {}


def _fetch_item(aweme_id: str) -> dict[str, Any]:
    share_url = SHARE_PAGE.format(aweme_id=aweme_id)
    page_headers = {
        "User-Agent": MOBILE_UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    last_error: DouyinError | None = None
    for attempt in range(2):
        ttwid = _get_ttwid(force=attempt == 1)
        try:
            with httpx.Client(
                headers=page_headers,
                follow_redirects=True,
                timeout=30,
            ) as client:
                response = client.get(share_url, cookies={"ttwid": ttwid})
                response.raise_for_status()
                html = response.text or ""
                if _is_waf_challenge(html) and _solve_waf_challenge(client, html, share_url):
                    response = client.get(share_url, cookies={"ttwid": ttwid})
                    response.raise_for_status()
                    html = response.text or ""
                item = _find_item(_extract_router_data(html))
                if item:
                    return item
                last_error = DouyinError(
                    "抖音分享页未返回视频数据（可能已删除、私密，或需要 App 打开）"
                )
        except httpx.HTTPError as exc:
            last_error = DouyinError(f"抖音分享页请求失败：{exc}")
    raise last_error or DouyinError("抖音解析失败")


def _head_size(url: str) -> int | None:
    try:
        with httpx.Client(
            headers=DOWNLOAD_HEADERS,
            follow_redirects=True,
            timeout=15,
        ) as client:
            response = client.head(url)
            if response.status_code != 200:
                return None
            length = int(response.headers.get("content-length") or 0)
            return length or None
    except (httpx.HTTPError, ValueError):
        return None


def _pick_quality(
    clean_url: str,
    video: dict[str, Any],
) -> tuple[str, int | None, int | None]:
    height_hint = int(video.get("height") or 0) or None
    base_size = _head_size(clean_url)
    best_url = clean_url
    best_size = base_size
    best_height = height_hint

    if "ratio=720p" in clean_url:
        for ratio, height in (("1080p", 1080), ("720p", 720)):
            candidate = clean_url.replace("ratio=720p", f"ratio={ratio}")
            size = _head_size(candidate)
            if size and (best_size is None or size > best_size):
                best_url = candidate
                best_size = size
                best_height = height

    return best_url, best_size, best_height


def _build_result(url: str, aweme_id: str, item: dict[str, Any]) -> dict[str, Any]:
    video = item.get("video") or {}
    play_urls = ((video.get("play_addr") or {}).get("url_list")) or []
    images = item.get("images") or []
    if not play_urls:
        if images:
            raise DouyinError("该抖音链接是图文/图集，当前版本仅支持视频")
        raise DouyinError("抖音视频没有可用的播放地址")

    clean_url = str(play_urls[0]).replace("playwm", "play")
    if clean_url.startswith("http://"):
        clean_url = "https://" + clean_url[len("http://") :]
    clean_url, filesize, height = _pick_quality(clean_url, video)

    author = item.get("author") or {}
    cover_urls = ((video.get("cover") or {}).get("url_list")) or []
    duration_ms = video.get("duration") or 0
    title = item.get("desc") or f"douyin_{aweme_id}"
    label = f"{height}P 无水印" if height else "无水印原画"

    option = {
        "id": "douyin",
        "label": label,
        "note": "无水印直链，无需 Cookie",
        "height": height,
        "ext": "mp4",
        "filesize": filesize,
        "fps": None,
        "progressive": True,
        "direct_format_id": "douyin",
        "audio_only": False,
        "selector": "",
        "direct_url": clean_url,
        "headers": dict(DOWNLOAD_HEADERS),
    }
    return {
        "id": aweme_id,
        "url": url,
        "title": title,
        "thumbnail": cover_urls[0] if cover_urls else None,
        "duration": round(duration_ms / 1000, 3) if duration_ms else None,
        "uploader": author.get("nickname"),
        "platform": "douyin",
        "is_playlist": False,
        "entry_count": None,
        "options": [option],
        "subtitles": [],
        "watermark": {"available": False, "label": None},
    }


def _probe_sync(url: str) -> dict[str, Any]:
    aweme_id = extract_aweme_id(url)
    now = time.time()
    with _item_lock:
        cached = _item_cache.get(aweme_id)
        if cached and now - cached[0] < _ITEM_TTL:
            return cached[1]

    item = _fetch_item(aweme_id)
    result = _build_result(url, aweme_id, item)
    with _item_lock:
        _item_cache[aweme_id] = (now, result)
    return result


async def probe(url: str) -> dict[str, Any]:
    return await asyncio.to_thread(_probe_sync, url)


async def resolve_direct(url: str, option_id: str) -> dict[str, Any]:
    normalized = await probe(url)
    option = next((opt for opt in normalized["options"] if opt["id"] == option_id), None)
    if option is None:
        raise DouyinError(f"未找到格式选项：{option_id}")
    if not option.get("direct_url"):
        raise DouyinError("该抖音视频没有可用的无水印地址")
    return {
        "url": option["direct_url"],
        "headers": option.get("headers") or {},
        "option": option,
    }
