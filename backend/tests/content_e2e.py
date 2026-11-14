"""v0.6 内容体验增强的浏览器验收脚本（真实链路）。

前置条件：
- 后端已启动：http://127.0.0.1:8000（挂载最新 frontend/dist）
- Chrome 以调试端口启动：--remote-debugging-port=9222
- backend/.env 已配置可用的 DeepSeek Key（真实总结链路）

运行：
    cd backend
    .venv\\Scripts\\python.exe -m tests.content_e2e

产物写入 runtime/proof/v0.6-*。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

from tests.browser_e2e import CDP, PROOF_DIR

# Windows 控制台默认 GBK，打印含 emoji 的面板文案会 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_URL = "http://127.0.0.1:8000"
CDP_URL = "http://127.0.0.1:9222"
VIDEO_URL = "https://www.bilibili.com/video/BV1s18cziEtw"
RESULT_PATH = PROOF_DIR / "v0.6-e2e.json"


def _new_files(before: set[Path], suffix: str, directory: Path = PROOF_DIR) -> list[Path]:
    return sorted(
        path
        for path in directory.glob(f"*{suffix}")
        if path not in before and path.is_file()
    )


def _png_size(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


async def run() -> int:
    download_dir = PROOF_DIR / f"v06-downloads-{time.strftime('%H%M%S')}"
    download_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "download_dir": str(download_dir),
        "steps": [],
        "exceptions": [],
        "failures": [],
        "files": [],
        "ok": False,
    }

    def step(name: str, **payload: Any) -> None:
        entry = {"step": name, "at": round(time.time() - started, 2), **payload}
        result["steps"].append(entry)
        print(json.dumps(entry, ensure_ascii=False))

    started = time.time()
    async with httpx.AsyncClient(timeout=20) as http:
        target = (await http.put(f"{CDP_URL}/json/new?{APP_URL}")).json()
    ws_url = target["webSocketDebuggerUrl"]
    async with websockets.connect(
        ws_url,
        origin="http://127.0.0.1:9222",
        max_size=30 * 1024 * 1024,
    ) as ws:
        cdp = CDP(ws)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 1200, "deviceScaleFactor": 1, "mobile": False},
        )
        try:
            await cdp.send(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(download_dir)},
            )
            step("download-behavior", ok=True)
        except Exception as exc:  # pragma: no cover - 兼容旧 Chrome
            step("download-behavior", ok=False, error=str(exc))

        await asyncio.sleep(1.5)
        await cdp.eval("window.localStorage.clear(); true")
        step("page-ready", url=await cdp.eval("location.href"))

        # 1. 解析
        await cdp.eval(
            "(() => { const input = document.querySelector('input[inputmode=\"url\"]');"
            " if (!input) throw new Error('找不到链接输入框');"
            " const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;"
            f" setter.call(input, {json.dumps(VIDEO_URL)});"
            " input.dispatchEvent(new Event('input', { bubbles: true }));"
            " document.querySelector('form#download button[type=submit]').click();"
            " return true; })()"
        )
        await cdp.wait_for(
            "Boolean(document.querySelector('#result'))",
            bool,
            timeout=90,
            interval=1.2,
            label="解析结果",
        )
        step("probe", title=(await cdp.eval("document.querySelector('#result h2')?.innerText || ''"))[:120])

        # 2. 选中较轻量的清晰度，便于时间戳跳转
        await cdp.eval(
            "(() => { const chips = [...document.querySelectorAll('#result [role=radio]')];"
            " const target = chips.find((b) => b.textContent.includes('360P'))"
            " || chips.find((b) => b.textContent.includes('480P')) || chips[0];"
            " if (!target) return false; target.click(); return true; })()"
        )
        await asyncio.sleep(1.5)

        # 3. 生成真实 AI 总结
        clicked = await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '生成总结');"
            " if (!button) return 'no-generate-button'; button.click(); return 'clicked'; })()"
        )
        step("generate-summary", action=clicked)
        panel_text = await cdp.wait_for(
            "document.querySelector('#ai-summary')?.innerText || ''",
            lambda text: (
                "TL;DR" in text
                or "总结失败" in text
                or "AI 总结未启用" in text
                or "笔记" in text
            ),
            timeout=180,
            interval=1.2,
            label="AI 总结完成",
        )
        if "总结失败" in panel_text or "AI 总结未启用" in panel_text:
            step("summary-failed", text=panel_text[:800])
            result["ok"] = False
            result["exceptions"] = cdp.exceptions[:10]
            RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        # 3.1 v0.8 起总结以打字机输出，必须等流结束再统计 Markdown 结构
        await cdp.wait_for(
            "document.querySelector('#ai-summary')?.dataset.summaryPhase || 'idle'",
            lambda phase: phase == "done",
            timeout=120,
            interval=0.4,
            label="总结输出完成",
        )

        # 4. 笔记视图
        await cdp.wait_for(
            "Boolean(document.querySelector('#ai-summary .md-body'))",
            bool,
            timeout=20,
            interval=0.5,
            label="Markdown 笔记视图",
        )
        note_info = await cdp.eval(
            "(() => { const body = document.querySelector('#ai-summary .md-body');"
            " if (!body) return null;"
            " return { headings: body.querySelectorAll('h1,h2,h3').length,"
            " lists: body.querySelectorAll('ul,ol').length,"
            " quotes: body.querySelectorAll('blockquote').length,"
            " timestamps: body.querySelectorAll('a[href^=\"#t=\"]').length,"
            " text: body.innerText.slice(0, 160) }; })()"
        )
        step("markdown-note", **note_info)
        if not note_info or note_info["headings"] < 3 or note_info["timestamps"] < 1:
            raise RuntimeError(f"Markdown 笔记结构不完整：{note_info}")
        await cdp.eval("document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true")
        await asyncio.sleep(0.5)
        await cdp.screenshot("v0.6-summary-note.png")

        # 5. 时间戳跳转（先等预览准备好，失败不阻断其余验收）
        try:
            time_clicked = await cdp.eval(
                "(() => { const link = [...document.querySelectorAll('#ai-summary .md-body a[href^=\"#t=\"]')]"
                " .find((a) => Number((a.getAttribute('href') || '').slice(3)) > 0);"
                " if (!link) return 'no-positive-timestamp'; link.click();"
                " return link.textContent.trim(); })()"
            )
            step("timestamp-clicked", value=time_clicked)
            video_state = await cdp.wait_for(
                "(() => { const video = document.querySelector('#result video');"
                " if (!video) return { found: false };"
                " return { found: true, currentTime: video.currentTime, duration: video.duration }; })()",
                lambda state: bool(state and state.get("found") and state.get("currentTime", 0) > 0),
                timeout=120,
                interval=1.2,
                label="时间戳跳转",
            )
            step("timestamp-seek", **video_state)
        except Exception as exc:
            step("timestamp-seek-failed", error=str(exc)[:300])

        # 6. 卡片视图切换
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '卡片');"
            " if (!button) return false; button.click(); return true; })()"
        )
        await cdp.wait_for(
            "document.querySelector('#ai-summary')?.innerText.includes('TL;DR') || false",
            bool,
            timeout=10,
            interval=0.4,
            label="卡片视图",
        )
        step("cards-view", ok=True)
        await cdp.screenshot("v0.6-summary-cards.png")
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '笔记');"
            " if (button) button.click(); return true; })()"
        )
        await cdp.wait_for(
            "Boolean(document.querySelector('#ai-summary .md-body'))",
            bool,
            timeout=10,
            interval=0.4,
            label="切回笔记视图",
        )

        # 7. 思维导图
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '思维导图');"
            " if (!button) return false; button.click(); return true; })()"
        )
        await cdp.wait_for(
            "document.querySelectorAll('#ai-summary .markmap-node').length",
            lambda value: int(value or 0) >= 3,
            timeout=20,
            interval=0.8,
            label="思维导图渲染",
        )
        await cdp.eval("document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true")
        await asyncio.sleep(0.5)
        await cdp.screenshot("v0.6-mindmap-inline.png")

        fullscreen_clicked = await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim().includes('全屏'));"
            " if (!button) return false; button.click(); return true; })()"
        )
        step("mindmap-fullscreen-click", ok=fullscreen_clicked)
        await cdp.wait_for(
            "(() => { const layer = document.querySelector('.v0-6-mindmap-layer');"
            " if (!layer) return null; const rect = layer.getBoundingClientRect();"
            " return { width: rect.width, height: rect.height, nodes: layer.querySelectorAll('.markmap-node').length }; })()",
            lambda info: bool(info and info.get("width", 0) > 1000 and info.get("nodes", 0) >= 3),
            timeout=15,
            interval=0.5,
            label="导图全屏弹层",
        )
        step("mindmap-fullscreen", ok=True)
        # 等 fit 动画（350ms）结束再截图，否则会截到左上角缩略状态
        await asyncio.sleep(1.2)
        await cdp.screenshot("v0.6-mindmap-fullscreen.png")

        # 导出 PNG 2x / 3x / SVG（菜单需要先点“导出”打开）
        for label, suffix in (("PNG 2x", ".png"), ("PNG 3x", ".png"), ("SVG", ".svg")):
            before = set(download_dir.glob(f"*{suffix}"))
            opened = await cdp.eval(
                "(() => { const scope = document.querySelector('.v0-6-mindmap-layer')"
                " || document.querySelector('#ai-summary');"
                " if (!scope) return false; const buttons = [...scope.querySelectorAll('button')];"
                " const button = buttons.find((item) => item.textContent.trim() === '导出');"
                " if (!button) return false; button.click(); return true; })()"
            )
            if not opened:
                step("export-menu-missing", label=label)
                continue
            await asyncio.sleep(0.3)
            clicked = await cdp.eval(
                "(() => { const menu = document.querySelector('[role=menu][aria-label=\"思维导图导出菜单\"]');"
                " if (!menu) return false; const buttons = [...menu.querySelectorAll('button')];"
                f" const button = buttons.find((item) => item.textContent.trim().startsWith({json.dumps(label)}));"
                " if (!button) return false; button.click(); return true; })()"
            )
            if not clicked:
                step("export-skipped", label=label)
                result["failures"].append(f"未找到导出菜单项：{label}")
                continue
            deadline = time.time() + 30
            found: list[Path] = []
            while time.time() < deadline:
                found = _new_files(before, suffix, download_dir)
                if found:
                    break
                await asyncio.sleep(1)
            feedback = await cdp.eval(
                "(() => { const layer = document.querySelector('.v0-6-mindmap-layer');"
                " const text = layer ? layer.innerText : document.querySelector('#ai-summary')?.innerText || '';"
                " const error = text.split('\\n').find((line) => line.includes('失败') || line.includes('请改用 SVG'));"
                " return error || ''; })()"
            )
            step("export", label=label, files=[str(path.name) for path in found], feedback=feedback)
            result["files"].extend(str(path) for path in found)
            if not found:
                result["failures"].append(f"{label} 导出未生成文件：{feedback}")
            if suffix == ".png" and found:
                size = _png_size(found[0])
                step("png-size", label=label, width=size[0] if size else None, height=size[1] if size else None)
                if not size or size[0] < 800:
                    raise RuntimeError(f"导出的 PNG 尺寸异常：{size}")

        # 关闭全屏
        await cdp.eval(
            "document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true"
        )
        await cdp.wait_for(
            "Boolean(document.querySelector('.v0-6-mindmap-layer'))",
            lambda value: not value,
            timeout=10,
            interval=0.5,
            label="全屏 ESC 关闭",
        )
        body_overflow = await cdp.eval("document.body.style.overflow")
        step("mindmap-fullscreen-closed", body_overflow=body_overflow)

        # 8. 字幕下载
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim().startsWith('文稿'));"
            " if (!button) return false; button.click(); return true; })()"
        )
        await cdp.wait_for(
            "(() => { const panel = document.querySelector('#ai-summary');"
            " return panel ? panel.innerText.includes('下载字幕') : false; })()",
            bool,
            timeout=20,
            interval=0.5,
            label="文稿页字幕下载",
        )
        before_srt = set(download_dir.glob("*.srt"))
        clicked = await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim().includes('下载字幕'));"
            " if (!button) return false; button.click(); return true; })()"
        )
        step("subtitle-download-click", ok=clicked)
        deadline = time.time() + 30
        srt_files: list[Path] = []
        while time.time() < deadline:
            srt_files = _new_files(before_srt, ".srt", download_dir)
            if srt_files:
                break
            await asyncio.sleep(0.5)
        if not srt_files:
            raise RuntimeError("字幕文件未下载")
        srt_text = srt_files[0].read_text(encoding="utf-8", errors="replace")
        step(
            "subtitle-file",
            file=srt_files[0].name,
            bytes=len(srt_text),
            has_arrow="-->" in srt_text,
            has_cn=any("\u4e00" <= char <= "\u9fff" for char in srt_text),
        )
        result["files"].extend(str(path) for path in srt_files)
        await cdp.screenshot("v0.6-subtitle-transcript.png")

        # 8.1 切换 Markdown 格式再下载一次，验证前端格式选择器
        changed = await cdp.eval(
            "(() => { const select = document.querySelector('#ai-summary select');"
            " if (!select) return false; select.value = 'md';"
            " select.dispatchEvent(new Event('change', { bubbles: true })); return true; })()"
        )
        step("subtitle-format-change", ok=changed, value="md")
        if changed:
            before_md = set(download_dir.glob("*.md"))
            clicked_md = await cdp.eval(
                "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
                " const button = buttons.find((item) => item.textContent.trim().includes('下载字幕'));"
                " if (!button) return false; button.click(); return true; })()"
            )
            step("subtitle-md-click", ok=clicked_md)
            deadline = time.time() + 30
            md_files: list[Path] = []
            while time.time() < deadline:
                md_files = _new_files(before_md, ".md", download_dir)
                if md_files:
                    break
                await asyncio.sleep(0.5)
            if md_files:
                md_text = md_files[0].read_text(encoding="utf-8", errors="replace")
                step(
                    "subtitle-md",
                    file=md_files[0].name,
                    bytes=len(md_text),
                    heading="· 字幕" in md_text or md_text.lstrip().startswith("#"),
                    timestamp_links="[0" in md_text,
                )
                result["files"].extend(str(path) for path in md_files)
            else:
                result["failures"].append("Markdown 字幕未下载")

        # 9. 移动端截图
        await cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True},
        )
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '总结');"
            " if (button) button.click(); return true; })()"
        )
        await asyncio.sleep(0.8)
        await cdp.eval("document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true")
        await asyncio.sleep(0.5)
        await cdp.screenshot("v0.6-summary-mobile.png")

        # 9.1 移动端思维导图全屏
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '思维导图');"
            " if (button) button.click(); return true; })()"
        )
        await cdp.wait_for(
            "document.querySelectorAll('#ai-summary .markmap-node').length",
            lambda value: int(value or 0) >= 3,
            timeout=20,
            interval=0.8,
            label="移动端思维导图渲染",
        )
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim().includes('全屏'));"
            " if (button) button.click(); return true; })()"
        )
        await cdp.wait_for(
            "(() => { const layer = document.querySelector('.v0-6-mindmap-layer');"
            " if (!layer) return null; const rect = layer.getBoundingClientRect();"
            " return { width: rect.width, height: rect.height, nodes: layer.querySelectorAll('.markmap-node').length }; })()",
            lambda info: bool(info and info.get("width", 0) > 300 and info.get("nodes", 0) >= 3),
            timeout=15,
            interval=0.5,
            label="移动端导图全屏",
        )
        await asyncio.sleep(1.2)
        await cdp.screenshot("v0.6-mindmap-mobile.png")
        await cdp.eval(
            "document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true"
        )
        await cdp.wait_for(
            "Boolean(document.querySelector('.v0-6-mindmap-layer'))",
            lambda value: not value,
            timeout=10,
            interval=0.5,
            label="移动端导图 ESC 关闭",
        )
        step("mindmap-mobile-fullscreen", ok=True)

        result["exceptions"] = cdp.exceptions[:10]
        result["elapsed_seconds"] = round(time.time() - started, 1)
        result["ok"] = not cdp.exceptions and not result["failures"]
        RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("exceptions:", cdp.exceptions[:5])
        print("result:", RESULT_PATH)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except Exception as exc:  # pragma: no cover - 验收脚本需要清晰失败信息
        print(f"E2E failed: {exc}", file=sys.stderr)
        raise
