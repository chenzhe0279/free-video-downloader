"""v0.8 无进度条总结流 + 等高工作台的浏览器验收脚本（Mock/真实链路均可）。

前置条件：
- 后端已启动：http://127.0.0.1:8000（挂载最新 frontend/dist）
- Chrome 以调试端口启动：--remote-debugging-port=9222
- 推荐使用 Mock DeepSeek，避免消耗真实额度：
  - tests.mock_deepseek:app 运行在 127.0.0.1:8100
  - 后端环境变量：VDS_DEEPSEEK_BASE_URL=http://127.0.0.1:8100、
    VDS_DEEPSEEK_API_KEY=mock、VDS_SUMMARY_DAILY_LIMIT_PER_IP=20
  - 为了稳定采集打字机增长，建议放慢节奏：
    VDS_SUMMARY_STREAM_INTERVAL_MS=80、VDS_SUMMARY_STREAM_CHUNK_CHARS=24

运行：
    cd backend
    .venv\\Scripts\\python.exe -m tests.workspace_e2e

产物写入 runtime/proof/v0.8-*；报告 runtime/proof/v0.8-e2e.json。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

import httpx
import websockets

from tests.browser_e2e import CDP, PROOF_DIR

# Windows 控制台默认 GBK，打印含 emoji（如 ✨）的面板文案会 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_URL = "http://127.0.0.1:8000"
CDP_URL = "http://127.0.0.1:9222"
VIDEO_URL = "https://www.bilibili.com/video/BV1s18cziEtw"
RESULT_PATH = PROOF_DIR / "v0.8-e2e.json"

PHASE_SCRIPT = "document.querySelector('#ai-summary')?.dataset.summaryPhase || ''"
TEXT_LENGTH_SCRIPT = (
    "(() => { const body = document.querySelector('#ai-summary .md-body');"
    " return body ? body.innerText.length : 0; })()"
)

RECT_SCRIPT = """(() => {
  const left = document.querySelector('#result');
  const right = document.querySelector('#ai-summary');
  if (!left || !right) return null;
  const l = left.getBoundingClientRect();
  const r = right.getBoundingClientRect();
  const grid = right.parentElement;
  const g = grid ? grid.getBoundingClientRect() : null;
  return {
    left: { top: Math.round(l.top), left: Math.round(l.left), right: Math.round(l.right), bottom: Math.round(l.bottom), width: Math.round(l.width), height: Math.round(l.height) },
    right: { top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right), bottom: Math.round(r.bottom), width: Math.round(r.width), height: Math.round(r.height) },
    gridHeight: g ? Math.round(g.height) : null,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    scrollX: Math.round(window.scrollX), scrollY: Math.round(window.scrollY),
    docWidth: document.documentElement.scrollWidth
  };
})()"""


async def set_url_and_submit(cdp: CDP, url: str) -> None:
    await cdp.eval(
        "(() => { const input = document.querySelector('input[inputmode=\"url\"]');"
        " if (!input) throw new Error('找不到链接输入框');"
        " const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;"
        f" setter.call(input, {json.dumps(url)});"
        " input.dispatchEvent(new Event('input', { bubbles: true }));"
        " document.querySelector('form#download button[type=submit]').click();"
        " return true; })()"
    )


def _rect_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return abs(left["top"] - right["top"]) <= 1 and abs(left["height"] - right["height"]) <= 1


async def run() -> int:
    result: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "exceptions": [],
        "failures": [],
        "screenshots": [],
        "ok": False,
    }
    started = time.time()

    def step(name: str, **payload: Any) -> None:
        entry = {"step": name, "at": round(time.time() - started, 2), **payload}
        result["steps"].append(entry)
        print(json.dumps(entry, ensure_ascii=False))

    def fail(name: str, message: str) -> None:
        result["failures"].append({"step": name, "message": message})
        print(f"FAIL {name}: {message}")

    async def shot(cdp: CDP, name: str) -> None:
        path = await cdp.screenshot(name)
        result["screenshots"].append(str(path.relative_to(PROOF_DIR.parent.parent)))

    async with httpx.AsyncClient(timeout=20) as http:
        target = (await http.put(f"{CDP_URL}/json/new?{APP_URL}")).json()
    ws_url = target["webSocketDebuggerUrl"]

    cdp: CDP | None = None
    try:
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
                {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
            )
            await asyncio.sleep(1.5)
            await cdp.eval("window.localStorage.clear(); true")
            await cdp.eval("window.scrollTo(0, 0); true")
            step("page-ready", url=await cdp.eval("location.href"))

            # 1. 解析，自动总结应开始
            await set_url_and_submit(cdp, VIDEO_URL)
            await cdp.wait_for(
                "Boolean(document.querySelector('#workspace') && document.querySelector('#result'))",
                bool,
                timeout=90,
                interval=1.0,
                label="解析结果",
            )
            title = (await cdp.eval("document.querySelector('#result h2')?.innerText || ''"))[:100]
            step("probe", title=title)

            # 2. 思考态：没有进度条/百分比，只有思考动画与阶段文案。
            # 命中缓存时会直接进入 streaming/done，此时主动「重新生成」一次，
            # 强制走真实生成路径，保证能观察到思考态与打字机。
            initial_phase = await cdp.wait_for(
                PHASE_SCRIPT,
                lambda value: value in {"thinking", "starting", "streaming", "done", "error"},
                timeout=120,
                interval=0.2,
                label="总结启动",
            )
            step("initial-phase", phase=initial_phase)
            if initial_phase in {"streaming", "done"}:
                if initial_phase == "streaming":
                    await cdp.wait_for(
                        PHASE_SCRIPT,
                        lambda value: value == "done",
                        timeout=90,
                        interval=0.2,
                        label="缓存结果输出完成",
                    )
                regenerated = await cdp.eval(
                    "(() => { const button = [...document.querySelectorAll('#ai-summary button')]"
                    "   .find((b) => b.textContent.trim() === '重新生成');"
                    " if (!button) return false; button.click(); return true; })()"
                )
                step("force-regenerate", clicked=regenerated)
                if not regenerated:
                    fail("force-regenerate", "缓存命中后找不到「重新生成」按钮")
                else:
                    await cdp.wait_for(
                        PHASE_SCRIPT,
                        lambda value: value in {"starting", "thinking"},
                        timeout=120,
                        interval=0.2,
                        label="强制重新生成思考态",
                    )
            elif initial_phase == "error":
                fail("summary-start", "总结进入错误状态")

            await cdp.wait_for(
                PHASE_SCRIPT,
                lambda value: value == "thinking",
                timeout=180,
                interval=0.2,
                label="总结思考态",
            )
            thinking_state = await cdp.eval(
                "(() => { const panel = document.querySelector('#ai-summary');"
                " if (!panel) return null; const text = panel.innerText || '';"
                " return { phase: panel.dataset.summaryPhase,"
                "   hasProgressbar: Boolean(panel.querySelector('progress, [role=progressbar], .progress')),"
                "   hasPercent: /\\d+\\s*%/.test(text),"
                "   hasDots: Boolean(panel.querySelector('.thinking-dots')),"
                "   hasThinkingTitle: text.includes('正在总结中'),"
                "   head: text.slice(0, 220) }; })()"
            )
            step("thinking-state", state=thinking_state)
            if not thinking_state:
                fail("thinking", "找不到总结面板")
            else:
                if thinking_state["hasProgressbar"] or thinking_state["hasPercent"]:
                    fail("thinking", "生成期间仍出现进度条或百分比")
                if not thinking_state["hasDots"] or not thinking_state["hasThinkingTitle"]:
                    fail("thinking", "思考动画或「正在总结中」缺失")
            await shot(cdp, "v0.8-thinking.png")

            # 3. 进入结果界面并打字机输出
            await cdp.wait_for(
                PHASE_SCRIPT,
                lambda value: value == "streaming",
                timeout=240,
                interval=0.2,
                label="总结流式输出",
            )
            stream_state = await cdp.eval(
                "(() => { const panel = document.querySelector('#ai-summary');"
                " const body = panel?.querySelector('.md-body');"
                " const text = panel?.innerText || '';"
                " return { phase: panel?.dataset.summaryPhase || '',"
                "   length: body ? body.innerText.length : 0,"
                "   hasTabs: ['章节', '文稿', '思维导图'].every((name) =>"
                "     [...panel.querySelectorAll('button')].some((b) => b.textContent.includes(name))),"
                "   outputBadge: text.includes('正在输出') }; })()"
            )
            step("streaming-state", state=stream_state)
            if not stream_state or not stream_state["hasTabs"] or not stream_state["outputBadge"]:
                fail("streaming", "结果界面标签页或「正在输出」标记缺失")

            samples: list[int] = []
            for _ in range(8):
                samples.append(int(await cdp.eval(TEXT_LENGTH_SCRIPT) or 0))
                if len(samples) >= 3 and samples[-1] > samples[0]:
                    break
                await asyncio.sleep(0.25)
            step("typewriter", samples=samples)
            if not any(after > before for before, after in zip(samples, samples[1:])):
                fail("typewriter", f"打字机文本长度未增长：{samples}")
            await shot(cdp, "v0.8-streaming.png")

            # 4. 输出完成
            await cdp.wait_for(
                PHASE_SCRIPT,
                lambda value: value == "done",
                timeout=180,
                interval=0.25,
                label="总结输出完成",
            )
            done_state = await cdp.eval(
                "(() => { const panel = document.querySelector('#ai-summary');"
                " const body = panel?.querySelector('.md-body');"
                " const text = panel?.innerText || '';"
                " return { phase: panel?.dataset.summaryPhase || '',"
                "   length: body ? body.innerText.length : 0,"
                "   hasCopy: text.includes('复制 Markdown'),"
                "   hasToggle: ['笔记', '卡片'].every((name) =>"
                "     [...panel.querySelectorAll('button')].some((b) => b.textContent.trim() === name)) }; })()"
            )
            step("done-state", state=done_state)
            if not done_state or done_state["length"] < 200:
                fail("done", "总结正文为空或过短")
            if not done_state or not done_state["hasCopy"] or not done_state["hasToggle"]:
                fail("done", "输出完成后复制/视图切换按钮未恢复")

            # 5. 1440×900：两栏等高、固定、内部滚动
            await asyncio.sleep(0.6)
            rect = await cdp.eval(RECT_SCRIPT)
            step("layout-1440", rect=rect)
            if not rect:
                fail("layout-1440", "找不到 #result 或 #ai-summary")
            else:
                if not _rect_equal(rect["left"], rect["right"]):
                    fail("layout-1440", f"两栏未等高：left={rect['left']['height']} right={rect['right']['height']}")
                if rect["left"]["right"] >= rect["right"]["left"]:
                    fail("layout-1440", "两栏未并排")
                if rect["gridHeight"] and abs(rect["gridHeight"] - (rect["viewport"]["height"] - 88)) > 2:
                    fail("layout-1440", f"工作台高度未固定为视口高度：{rect['gridHeight']}")
                if rect["docWidth"] > rect["viewport"]["width"]:
                    fail("layout-1440", "出现横向溢出")
            await shot(cdp, "v0.8-workspace-1440.png")

            scroll_state = await cdp.eval(
                "(() => { const panel = document.querySelector('#ai-summary');"
                " const scroll = panel?.querySelector('[data-summary-scroll]');"
                " if (!scroll) return null;"
                " const leftTop = Math.round(document.querySelector('#result').getBoundingClientRect().top);"
                " scroll.scrollTop = 160;"
                " const afterLeftTop = Math.round(document.querySelector('#result').getBoundingClientRect().top);"
                " return { scrollable: scroll.scrollHeight > scroll.clientHeight + 8,"
                "   scrollTop: Math.round(scroll.scrollTop),"
                "   leftTop, afterLeftTop }; })()"
            )
            step("inner-scroll", state=scroll_state)
            if not scroll_state or not (scroll_state["scrollable"] or scroll_state["scrollTop"] > 0):
                fail("inner-scroll", "右栏无法内部滚动")
            elif scroll_state["afterLeftTop"] != scroll_state["leftTop"]:
                fail("inner-scroll", "右栏滚动时左栏位置被带动")
            await cdp.eval(
                "(() => { const scroll = document.querySelector('#ai-summary [data-summary-scroll]');"
                " if (scroll) scroll.scrollTop = 0; return true; })()"
            )

            # 6. 页面滚动时两栏一起移动（旧吸顶已取消）
            await cdp.eval("window.scrollBy(0, 300); true")
            await asyncio.sleep(0.4)
            scrolled = await cdp.eval(RECT_SCRIPT)
            step("page-scroll", rect=scrolled)
            if not scrolled:
                fail("page-scroll", "滚动后取不到 rect")
            else:
                if abs(scrolled["left"]["top"] - scrolled["right"]["top"]) > 1:
                    fail("page-scroll", "页面滚动后两栏未保持对齐")
                if rect and scrolled["left"]["top"] >= rect["left"]["top"] - 100:
                    fail("page-scroll", "工作台仍被吸顶，未随页面滚动")
            await cdp.eval(
                "document.querySelector('#workspace')?.scrollIntoView({ block: 'start' }); true"
            )
            await asyncio.sleep(0.5)

            # 7. 1280×800 仍为等高双栏
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False},
            )
            await asyncio.sleep(1.0)
            await cdp.eval(
                "document.querySelector('#workspace')?.scrollIntoView({ block: 'start' }); true"
            )
            await asyncio.sleep(0.5)
            rect_1280 = await cdp.eval(RECT_SCRIPT)
            step("layout-1280", rect=rect_1280)
            if not rect_1280:
                fail("layout-1280", "取不到 rect")
            else:
                if not _rect_equal(rect_1280["left"], rect_1280["right"]):
                    fail("layout-1280", "1280 宽度下两栏未等高")
                if rect_1280["gridHeight"] and abs(rect_1280["gridHeight"] - (rect_1280["viewport"]["height"] - 88)) > 2:
                    fail("layout-1280", f"1280 下工作台高度异常：{rect_1280['gridHeight']}")
                if rect_1280["docWidth"] > rect_1280["viewport"]["width"]:
                    fail("layout-1280", "出现横向溢出")
            await shot(cdp, "v0.8-workspace-1280.png")

            # 8. 顶栏「升级 Pro」样式
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
            )
            await asyncio.sleep(0.6)
            cta = await cdp.eval(
                "(() => { const link = [...document.querySelectorAll('header a')]"
                "   .find((a) => a.textContent.trim() === '升级 Pro');"
                " if (!link) return null; const style = getComputedStyle(link);"
                " return { text: link.textContent.trim(), href: link.getAttribute('href'),"
                "   bg: style.backgroundColor, color: style.color,"
                "   radius: style.borderRadius, height: Math.round(link.getBoundingClientRect().height) }; })()"
            )
            step("pro-cta", style=cta)
            if not cta:
                fail("pro-cta", "找不到「升级 Pro」按钮")
            else:
                if cta["href"] != "#pricing":
                    fail("pro-cta", f"href 不是 #pricing：{cta['href']}")
                if cta["bg"] not in {"rgb(59, 107, 250)", "rgb(37, 99, 235)"}:
                    fail("pro-cta", f"按钮不是品牌蓝：{cta['bg']}")
                if cta["radius"] not in {"9999px", "9999px 9999px 9999px 9999px"}:
                    fail("pro-cta", f"按钮不是胶囊圆角：{cta['radius']}")

            # 9. 自动总结开关偏好仍可持久化
            await cdp.eval(
                "(() => { const box = document.querySelector('#ai-summary input[type=checkbox]');"
                " if (box && box.checked) box.click(); return true; })()"
            )
            await asyncio.sleep(0.3)
            stored_off = await cdp.eval("window.localStorage.getItem('vds-auto-summary')")
            await cdp.eval(
                "(() => { const box = document.querySelector('#ai-summary input[type=checkbox]');"
                " if (box && !box.checked) box.click(); return true; })()"
            )
            await asyncio.sleep(0.3)
            stored_on = await cdp.eval("window.localStorage.getItem('vds-auto-summary')")
            step("auto-toggle", stored_off=stored_off, stored_on=stored_on)
            if stored_off != "off" or stored_on != "on":
                fail("auto-toggle", "自动总结开关偏好未持久化")

            # 10. 移动端单列、无固定高度
            await cdp.send(
                "Emulation.setDeviceMetricsOverride",
                {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True},
            )
            await asyncio.sleep(1.2)
            await cdp.eval(
                "document.querySelector('#workspace')?.scrollIntoView({ block: 'start' }); true"
            )
            await asyncio.sleep(0.6)
            mobile = await cdp.eval(RECT_SCRIPT)
            step("layout-375", rect=mobile)
            if not mobile:
                fail("layout-375", "取不到 rect")
            else:
                if mobile["right"]["top"] <= mobile["left"]["bottom"]:
                    fail("layout-375", "移动端未按单列堆叠")
                if mobile["docWidth"] > mobile["viewport"]["width"] + 1:
                    fail("layout-375", "移动端出现横向溢出")
                if mobile["gridHeight"] and mobile["gridHeight"] == mobile["viewport"]["height"] - 88:
                    fail("layout-375", "移动端不应套用固定工作台高度")
            await shot(cdp, "v0.8-workspace-375.png")

            await cdp.send("Emulation.clearDeviceMetricsOverride")
            await asyncio.sleep(0.5)
    except Exception as exc:  # noqa: BLE001 - 需要把异常写进验收报告
        fail("unexpected", f"{type(exc).__name__}: {exc}")

    if cdp is not None:
        result["exceptions"] = cdp.exceptions[:10]
        step("exceptions", count=len(cdp.exceptions))
        if cdp.exceptions:
            fail("exceptions", "; ".join(cdp.exceptions[:3]))

    result["ok"] = not result["failures"]
    result["elapsed_seconds"] = round(time.time() - started, 1)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresult: {'PASS' if result['ok'] else 'FAIL'} ({result['elapsed_seconds']}s)")
    for item in result["failures"]:
        print(f" - {item['step']}: {item['message']}")
    print(f"report: {RESULT_PATH}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
