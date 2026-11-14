from __future__ import annotations

import asyncio
import json
import time

import httpx
import websockets

from tests.browser_e2e import APP_URL, CDP_URL, PROOF_DIR, VIDEO_URL, CDP


async def set_question(cdp: CDP, question: str) -> bool:
    return bool(
        await cdp.eval(
            "(() => { const el = document.querySelector('#ai-summary textarea');"
            " if (!el) return false;"
            " const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;"
            f" setter.call(el, {json.dumps(question)});"
            " el.dispatchEvent(new Event('input', { bubbles: true }));"
            " return true; })()"
        )
    )


async def click_button(cdp: CDP, label: str) -> bool:
    return bool(
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            f" const button = buttons.find((item) => item.textContent.trim() === {json.dumps(label)});"
            " if (!button) return false; button.click(); return true; })()"
        )
    )


async def panel_state(cdp: CDP) -> dict:
    return await cdp.eval(
        "(() => { const panel = document.querySelector('#ai-summary');"
        " if (!panel) return { text: '', send: false, stop: false };"
        " const buttons = [...panel.querySelectorAll('button')];"
        " return {"
        " text: panel.innerText,"
        " send: buttons.some((b) => b.textContent.trim() === '发送'),"
        " stop: buttons.some((b) => b.textContent.trim() === '停止')"
        " }; })()"
    )


async def ask(cdp: CDP, question: str, timeout: float = 60) -> dict:
    await cdp.eval(
        "document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true"
    )
    if not await set_question(cdp, question):
        raise RuntimeError("找不到问答输入框")
    if not await click_button(cdp, "发送"):
        raise RuntimeError("找不到发送按钮")
    started = time.time()
    await cdp.wait_for(
        "(() => { const panel = document.querySelector('#ai-summary');"
        " if (!panel) return false; const buttons = [...panel.querySelectorAll('button')];"
        " return buttons.some((b) => b.textContent.trim() === '停止')"
        " || panel.innerText.includes('正在判断问题'); })()",
        bool,
        timeout=10,
        interval=0.2,
        label="开始生成",
    )
    samples: list[tuple[float, int]] = []
    stop_seen = False
    final = None
    while time.time() - started < timeout:
        state = await panel_state(cdp)
        samples.append((round(time.time() - started, 2), len(state["text"])))
        if state["stop"]:
            stop_seen = True
        if stop_seen and state["send"] and not state["stop"]:
            final = state
            break
        await asyncio.sleep(0.3)
    if final is None:
        final = await panel_state(cdp)
    return {
        "question": question,
        "elapsed": round(time.time() - started, 2),
        "samples": samples,
        "text": final["text"],
    }


async def run() -> int:
    async with httpx.AsyncClient(timeout=10) as http:
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
            {"width": 1440, "height": 1200, "deviceScaleFactor": 1, "mobile": False},
        )
        await asyncio.sleep(1.5)

        # 解析 + 生成总结（命中缓存）
        await cdp.eval(
            "(() => { const input = document.querySelector('input[inputmode=\"url\"]');"
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
            interval=1,
            label="解析结果",
        )
        await cdp.eval(
            "(() => { const buttons = [...document.querySelectorAll('#ai-summary button')];"
            " const button = buttons.find((item) => item.textContent.trim() === '生成总结');"
            " if (!button) return 'cached'; button.click(); return 'clicked'; })()"
        )
        await cdp.wait_for(
            "document.querySelector('#ai-summary')?.innerText.includes('TL;DR') || false",
            bool,
            timeout=90,
            interval=1,
            label="总结完成",
        )

        # 问答 tab
        if not await click_button(cdp, "问答"):
            raise RuntimeError("找不到问答标签页")
        await asyncio.sleep(0.5)
        await cdp.eval(
            "document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true"
        )
        await cdp.screenshot("ai-qa-empty.png")

        relevant = await ask(cdp, "这个视频的核心内容是什么？")
        print("relevant elapsed", relevant["elapsed"])
        print("relevant samples", relevant["samples"][:12])
        print("relevant has answer", "巡演" in relevant["text"] or "独白" in relevant["text"])
        await cdp.screenshot("ai-qa-relevant.png")

        follow = await ask(cdp, "再展开说说第一点")
        print("follow elapsed", follow["elapsed"], "has more", "第一点" in follow["text"])
        await cdp.screenshot("ai-qa-followup.png")

        unrelated = await ask(cdp, "今天天气怎么样？")
        print("unrelated elapsed", unrelated["elapsed"])
        print("unrelated refused", "只能回答与当前视频内容相关" in unrelated["text"])
        await cdp.screenshot("ai-qa-refusal.png")

        strict = await ask(cdp, "视频里用的什么拍摄设备？")
        print("strict elapsed", strict["elapsed"])
        print("strict not mentioned", "材料中没有提到" in strict["text"])
        await cdp.screenshot("ai-qa-strict.png")

        # 标签切换后会话仍在
        await click_button(cdp, "总结")
        await asyncio.sleep(0.3)
        await click_button(cdp, "问答")
        await asyncio.sleep(0.3)
        persisted = await cdp.eval(
            "document.querySelector('#ai-summary')?.innerText.includes('拍摄设备') || false"
        )
        print("history persists across tabs", persisted)

        # 停止按钮
        await set_question(cdp, "详细分析视频里所有情感变化和象征意义，尽量展开。")
        await click_button(cdp, "发送")
        await asyncio.sleep(0.4)
        stopped = await click_button(cdp, "停止")
        await asyncio.sleep(0.8)
        stop_text = await cdp.eval(
            "document.querySelector('#ai-summary')?.innerText || ''"
        )
        print("stop clicked", stopped, "stop shown", "已停止生成" in stop_text)
        await cdp.screenshot("ai-qa-stopped.png")

        # 移动端
        await cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True},
        )
        await asyncio.sleep(1)
        await cdp.eval(
            "document.querySelector('#ai-summary')?.scrollIntoView({ block: 'start' }); true"
        )
        await cdp.screenshot("ai-qa-mobile.png")
        print("exceptions:", cdp.exceptions[:5])

        result = {
            "relevant": relevant,
            "follow": follow,
            "unrelated": unrelated,
            "strict": strict,
            "history_persisted": persisted,
            "stop_clicked": stopped,
            "stop_shown": "已停止生成" in stop_text,
            "exceptions": cdp.exceptions,
        }
        PROOF_DIR.mkdir(parents=True, exist_ok=True)
        (PROOF_DIR / "ai-qa-browser-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
