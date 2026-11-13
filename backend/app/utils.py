from __future__ import annotations

import re

# 文件名里不允许出现的字符（含控制字符，避免污染 Content-Disposition 响应头）
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_SPACES = re.compile(r"\s+")
_EXT = re.compile(r"[^a-z0-9]+")

MAX_FILENAME_LENGTH = 120


def safe_filename(name: str, fallback: str = "video") -> str:
    """把任意标题清洗成跨平台安全、可安全放进响应头的文件名。"""
    cleaned = _UNSAFE_CHARS.sub("_", name or "")
    cleaned = _SPACES.sub(" ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:MAX_FILENAME_LENGTH]


def build_filename(title: str | None, label: str | None, ext: str | None) -> str:
    """生成“标题 [清晰度].扩展名”形式的下载文件名。"""
    suffix = _EXT.sub("", (ext or "").lstrip(".").lower()) or "mp4"
    base = title or "video"
    if label:
        base = f"{base} [{label}]"
    # 预留后缀长度，避免扩展名被截断
    stem = safe_filename(base)[: MAX_FILENAME_LENGTH - len(suffix) - 1].strip(" .") or "video"
    return f"{stem}.{suffix}"
