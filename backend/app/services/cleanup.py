from __future__ import annotations

import asyncio
import logging
import shutil

from app.config import get_settings
from app.services.task_manager import manager

logger = logging.getLogger("vds.cleanup")


def _purge_orphan_dirs() -> int:
    """删除磁盘上已无对应任务记录的目录（例如进程重启后遗留）。"""
    settings = get_settings()
    if not settings.download_dir.exists():
        return 0
    known = {task.id for task in manager.all_tasks()}
    removed = 0
    for child in settings.download_dir.iterdir():
        if not child.is_dir() or child.name in known:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed


async def cleanup_loop() -> None:
    settings = get_settings()
    while True:
        try:
            await asyncio.sleep(settings.cleanup_interval_seconds)
            expired = manager.purge_expired()
            orphans = _purge_orphan_dirs()
            if expired or orphans:
                logger.info("清理完成：过期任务 %d 个，孤儿目录 %d 个", expired, orphans)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - never kill the loop
            logger.exception("清理任务异常")
