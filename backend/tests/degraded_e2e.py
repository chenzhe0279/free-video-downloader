"""v0.8 降级布局核对：AI 总结未启用时应为单列、自然高度，且不显示自动请求。

前置：后端以 VDS_SUMMARY_ENABLED=false 启动，Chrome 9222 可用。
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import websockets

from tests.browser_e2e import CDP, PROOF_DIR, VIDEO_URL

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_URL = "http://127.0.0.1:8000"
CDP_URL = "http://127.0.0.1:9222"


async def run() -> int:
    async with httpx.AsyncClient(timeout=20) as http:
        target = (await http.put(f"{CDP_URL}/json/new?{APP_URL}")).json()
    async with websockets.connect(
        target["webSocketDebuggerUrl"],
        origin="http://127.0.0.1:9222",
        max_size=30 * 1024 * 1024,
    ) as ws:
        cdp = CDP(ws)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        await asyncio.sleep(1.5)
        await cdp.eval("window.localStorage.clear(); true")

        await cdp.eval(
            "(() => { const input = document.querySelector('input[inputmode=\"url\"]');"
            " const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;"
            f" setter.call(input, {json.dumps(VIDEO_URL)});"
            " input.dispatchEvent(new Event('input', { bubbles: true }));"
            " document.querySelector('form#download button[type=submit]').click();"
            " return true; })()"
        )
        await cdp.wait_for(
            "Boolean(document.querySelector('#result') && document.querySelector('#ai-summary'))",
            bool,
            timeout=90,
            interval=1,
            label="解析结果",
        )
        await asyncio.sleep(4)
        state = await cdp.eval(
            "(() => { const left = document.querySelector('#result').getBoundingClientRect();"
            " const right = document.querySelector('#ai-summary').getBoundingClientRect();"
            " const panel = document.querySelector('#ai-summary');"
            " return { left: { top: Math.round(left.top), bottom: Math.round(left.bottom)," 
            " right: Math.round(left.right) },"
            " right: { top: Math.round(right.top), left: Math.round(right.left) },"
            " singleColumn: right.top > left.bottom,"
            " disabledNotice: panel.innerText.includes('AI 总结未启用'),"
            " autoToggle: Boolean(panel.querySelector('input[type=checkbox]')),"
            " note: Boolean(panel.querySelector('.md-body')),"
            " overflow: document.documentElement.scrollWidth > window.innerWidth }; })()"
        )
        print(json.dumps(state, ensure_ascii=False))
        await cdp.eval("document.querySelector('#workspace')?.scrollIntoView({ block: 'start' }); true")
        await asyncio.sleep(0.8)
        await cdp.screenshot("v0.8-degraded-single-column.png")
        print("exceptions:", cdp.exceptions[:3])
        ok = (
            state["singleColumn"]
            and state["disabledNotice"]
            and not state["autoToggle"]
            and not state["note"]
            and not state["overflow"]
            and not cdp.exceptions
        )
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
