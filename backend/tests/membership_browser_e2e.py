"""Drive the local membership flow through Chromium via the existing test CDP helper."""

import asyncio
import json
import os
from uuid import uuid4

import httpx
import websockets

from tests.browser_e2e import APP_URL, CDP


CDP_URL = os.getenv("CLIPNEST_TEST_CDP_URL", "http://127.0.0.1:9222")
INBOX_URL = "http://127.0.0.1:8102/fixture/inbox"


def js(value):
    return json.dumps(value, ensure_ascii=False)


async def run():
    async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
        target = (await http.put(f"{CDP_URL}/json/new?about:blank")).raise_for_status().json()
        try:
            async with websockets.connect(target["webSocketDebuggerUrl"], max_size=10 * 1024 * 1024) as ws:
                await exercise(CDP(ws), http)
        finally:
            await http.get(f"{CDP_URL}/json/close/{target['id']}")


async def exercise(browser: CDP, http: httpx.AsyncClient):
    async def wait(expression, label):
        try:
            async with asyncio.timeout(35):
                while True:
                    try:
                        if await browser.eval(expression):
                            return
                    except RuntimeError as exc:
                        if "context" not in str(exc).lower() and "navigat" not in str(exc).lower():
                            raise
                    await asyncio.sleep(0.25)
        except TimeoutError as exc:
            page = await browser.eval("({ origin: location.origin, title: document.title })")
            raise TimeoutError(f"等待浏览器步骤超时：{label}，页面={page}，JS={browser.exceptions}") from exc

    async def click(text, scope="document"):
        expression = (
            f"Array.from({scope}.querySelectorAll('button, a'))"
            f".find(el => el.textContent.trim() === {js(text)} && !el.disabled)"
        )
        await wait(f"!!({expression})", text)
        await browser.eval(f"({expression}).click()")

    async def fill(selector, value):
        await browser.eval(
            f"(() => {{ const input = document.querySelector({js(selector)});"
            f"input.value = {js(value)}; input.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()"
        )

    async def navigate(url):
        await browser.send("Page.navigate", {"url": url})

    async def verify_mail(email, subject):
        async with asyncio.timeout(12):
            while True:
                mails = (await http.get(INBOX_URL)).raise_for_status().json()
                for mail in reversed(mails):
                    if email in mail["to"] and subject in mail["subject"]:
                        return mail["url"]
                await asyncio.sleep(0.2)

    await browser.send("Page.enable")
    await browser.send("Runtime.enable")
    await navigate(APP_URL)
    await click("登录")
    dialog = "document.querySelector('dialog')"
    await click("注册账号", dialog)
    email = f"browser-{uuid4().hex}@example.com"
    password = "browser-test-password"
    await fill("dialog input[type=email]", email)
    await fill("dialog input[type=password]", password)
    await click("注册账号", dialog)
    await wait("document.querySelector('dialog [role=status]')?.textContent.includes('系统会发送邮件')", "注册响应")
    link = await verify_mail(email, "验证邮箱")
    await navigate(link)
    await wait("document.querySelector('#membership-dialog-title')?.textContent === '验证邮箱'", "验证邮箱对话框")
    await fill("dialog input[type=password]", password)
    await click("验证邮箱", dialog)
    await wait("document.querySelector('dialog [role=status]')?.textContent.trim() === '邮箱已验证。'", "邮箱已验证")
    await fill("dialog input[type=email]", email)
    await fill("dialog input[type=password]", password)
    await click("登录", dialog)
    await wait("document.querySelector('#membership-dialog-title')?.textContent === '我的会员'", "已登录")
    await click("关闭", dialog)
    await click("开通月卡")
    await wait("location.port === '8102' && document.title === '本地模拟收银台'", "跳转模拟收银台")
    await click("模拟银行卡拒付")
    await wait("!!document.querySelector('[role=alert]')", "发卡行拒绝提示")
    await click("返回网站")
    await wait("document.querySelector('#membership-dialog-title')?.textContent === '我的会员'", "回跳订单状态")
    await click("继续付款", dialog)
    await wait("location.port === '8102' && document.title === '本地模拟收银台'", "继续同一笔订单")
    session_id = await browser.eval("location.pathname.split('/').pop()")
    await click("模拟付款成功")
    await wait("document.querySelector('dialog')?.textContent.includes('今天剩余 20 / 20 次')", "会员生效")
    (await http.post(f"http://127.0.0.1:8102/fixture/outcome/{session_id}/refunded")).raise_for_status()
    await wait("document.querySelector('dialog')?.textContent.includes('已全额退款')", "退款撤销会员")
    assert not browser.exceptions, browser.exceptions
    print("浏览器验收通过：注册、SMTP 验证、登录、拒绝后继续付款、签名回调开通、全额退款")


if __name__ == "__main__":
    asyncio.run(run())
