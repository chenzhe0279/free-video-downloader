from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import websockets

APP_URL = "http://127.0.0.1:8000"
CDP_URL = "http://127.0.0.1:9222"
PROOF_DIR = Path(__file__).resolve().parents[2] / "runtime" / "proof"
VIDEO_URL = "https://www.bilibili.com/video/BV1s18cziEtw"


class CDP:
    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.next_id = 0
        self.exceptions: list[str] = []

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        current = self.next_id
        await self.ws.send(
            json.dumps({"id": current, "method": method, "params": params or {}})
        )
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), 60)
            message = json.loads(raw)
            if message.get("id") == current:
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result", {})
            method_name = message.get("method")
            if method_name == "Runtime.exceptionThrown":
                details = message.get("params", {}).get("exceptionDetails", {})
                text = details.get("exception", {}).get("description") or details.get(
                    "text", ""
                )
                self.exceptions.append(str(text)[:500])

    async def eval(self, expression: str) -> Any:
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        inner = result.get("result", {})
        if inner.get("subtype") == "error":
            raise RuntimeError(inner.get("description", "JS error"))
        return inner.get("value")

    async def wait_for(
        self,
        expression: str,
        predicate: Callable[[Any], bool],
        *,
        timeout: float = 60,
        interval: float = 1.0,
        label: str = "",
    ) -> Any:
        started = time.time()
        last: Any = None
        while time.time() - started < timeout:
            last = await self.eval(expression)
            if predicate(last):
                return last
            await asyncio.sleep(interval)
        raise TimeoutError(f"等待超时：{label}，最后值：{str(last)[:300]}")

    async def screenshot(self, name: str) -> Path:
        PROOF_DIR.mkdir(parents=True, exist_ok=True)
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(result["data"])
        path = PROOF_DIR / name
        path.write_bytes(data)
        return path


async def run() -> int:
    async with httpx.AsyncClient(timeout=10) as http:
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
            {"width": 1440, "height": 1100, "deviceScaleFactor": 1, "mobile": False},
        )
        await asyncio.sleep(1.5)
        print("page:", await cdp.eval("location.href"))
        print("ready:", await cdp.eval("document.readyState"))

        # 1. 输入链接并解析
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
        print("parsed:", (await cdp.eval("document.querySelector('#result').innerText"))[:200])

        # 2. 选择一个较轻量的清晰度，便于预览跳转
        await cdp.eval(
            "(() => { const items = [...document.querySelectorAll('#result li')];"
            " const target = items.find((li) => li.innerText.includes('360P'))"
            " || items.find((li) => li.innerText.includes('480P')) || items[0];"
            " if (!target) return false; const button = target.querySelector('button');"
            " button?.click(); return target.innerText.slice(0, 80); })()"
        )
        await asyncio.sleep(1.5)

        # 3. 生成 AI 总结（若已有缓存会直接出现）
        clicked = await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '生成总结');"
            " if (!button) return 'no-generate-button'; button.click(); return 'clicked'; })()"
        )
        print("generate:", clicked)
        panel_text = await cdp.wait_for(
            "document.querySelector('#ai-summary')?.innerText || ''",
            lambda text: "TL;DR" in text or "总结失败" in text or "AI 总结未启用" in text,
            timeout=120,
            interval=1.2,
            label="AI 总结完成",
        )
        print("panel:\n", panel_text[:1500])

        # 4. 总结标签页截图
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '总结');"
            " if (button) button.click();"
            " document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' });"
            " return true; })()"
        )
        await asyncio.sleep(0.8)
        await cdp.screenshot("ai-summary-summary.png")

        # 5. 章节标签页与时间戳跳转
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim().startsWith('章节'));"
            " if (!button) return false; button.click(); return true; })()"
        )
        await asyncio.sleep(1)
        chapters_text = await cdp.eval(
            "(() => { const panel = document.querySelector('#ai-summary');"
            " return panel ? panel.innerText : ''; })()"
        )
        print("chapters:\n", chapters_text[:1200])
        await cdp.eval(
            "document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true"
        )
        await cdp.screenshot("ai-summary-chapters.png")
        time_clicked = await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => { const text = item.textContent.trim();"
            " return /^\\d+:\\d{2}$/.test(text) && text !== '0:00'; });"
            " if (!button) return 'no-time-button'; if (button.disabled) return 'disabled';"
            " button.click(); return button.textContent.trim(); })()"
        )
        print("time clicked:", time_clicked)
        video_state = await cdp.wait_for(
            "(() => { const video = document.querySelector('#result video');"
            " if (!video) return { found: false };"
            " return { found: true, currentTime: video.currentTime, duration: video.duration,"
            " paused: video.paused, readyState: video.readyState }; })()",
            lambda state: bool(
                state
                and state.get("found")
                and state.get("currentTime", 0) >= 29
            ),
            timeout=120,
            interval=1.5,
            label="预览跳转到 0:30",
        )
        print("video:", video_state)

        # 6. 检查文稿 / 思维导图标签页
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim().startsWith('文稿'));"
            " if (!button) return false; button.click(); return true; })()"
        )
        await asyncio.sleep(1.5)
        transcript_text = await cdp.wait_for(
            "document.querySelector('#ai-summary')?.innerText || ''",
            lambda text: "复制文稿" in text and "段" in text,
            timeout=20,
            interval=1,
            label="文稿标签页",
        )
        print("transcript tab:", len(transcript_text) > 0)
        await cdp.screenshot("ai-summary-transcript.png")
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '思维导图');"
            " if (!button) return false; button.click(); return true; })()"
        )
        mindmap_info = await cdp.wait_for(
            "(() => { const panel = document.querySelector('#ai-summary');"
            " if (!panel) return { nodes: 0, svg: false };"
            " return { nodes: panel.querySelectorAll('.markmap-node').length,"
            " svg: Boolean(panel.querySelector('svg')) }; })()",
            lambda info: bool(info and info.get("nodes", 0) >= 3),
            timeout=20,
            interval=1,
            label="思维导图标签页",
        )
        print("mindmap tab:", mindmap_info.get("nodes"))
        await cdp.screenshot("ai-summary-mindmap.png")

        # 7. 桌面 / 移动端截图
        await cdp.eval(
            "document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true"
        )
        await asyncio.sleep(0.5)
        await cdp.screenshot("ai-summary-mindmap.png")
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '总结');"
            " if (button) button.click(); return true; })()"
        )
        await cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True},
        )
        await asyncio.sleep(1)
        await cdp.eval(
            "document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true"
        )
        await asyncio.sleep(0.5)
        await cdp.screenshot("ai-summary-mobile.png")
        print("exceptions:", cdp.exceptions[:5])
        print(
            "screenshots:",
            (PROOF_DIR / "ai-summary-summary.png").exists(),
            (PROOF_DIR / "ai-summary-mobile.png").exists(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
