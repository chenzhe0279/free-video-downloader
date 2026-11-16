"""Loopback-only SMTP and Checkout fixtures, with harmless signed Stripe-shaped events."""

import hashlib
import hmac
import html
import json
import re
import socketserver
import threading
import time
from contextlib import asynccontextmanager
from email import policy
from email.parser import BytesParser
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.membership.config import settings
from app.membership.gateway import MOCK_URL


APP_URL = "http://127.0.0.1:8000"
LOCK = threading.RLock()
SESSIONS = {}
KEYS = {}
INTENTS = {}
INBOX = []
EVENT_LOG = {}
FAIL_NEXT_CREATE = False


class MailHandler(socketserver.StreamRequestHandler):
    def reply(self, text: str) -> None:
        self.wfile.write(f"{text}\r\n".encode("ascii"))

    def handle(self) -> None:
        self.reply("220 ClipNest local SMTP fixture")
        while line := self.rfile.readline(65536):
            command = line.split(maxsplit=1)[0].upper()
            if command in {b"EHLO", b"HELO", b"MAIL", b"RCPT", b"RSET"}:
                self.reply("250 OK")
            elif command == b"DATA":
                self.reply("354 End message with a dot")
                data = bytearray()
                while part := self.rfile.readline(65536):
                    if part == b".\r\n":
                        break
                    data.extend(part[1:] if part.startswith(b"..") else part)
                message = BytesParser(policy=policy.default).parsebytes(data)
                text = message.get_body(preferencelist=("plain",)).get_content()
                match = re.search(r"https?://[^\s]+", text)
                if match:
                    with LOCK:
                        INBOX.append({"to": str(message["To"]), "subject": str(message["Subject"]), "url": match[0]})
                self.reply("250 Accepted")
            elif command == b"QUIT":
                self.reply("221 Bye")
                break
            else:
                self.reply("502 Unsupported command")


class MailServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@asynccontextmanager
async def lifespan(_app):
    config = settings()
    if config.stripe_mode != "mock" or config.smtp_host != "127.0.0.1":
        raise RuntimeError("本地测试服务需要 mock 模式和回环地址")
    with MailServer(("127.0.0.1", config.smtp_port), MailHandler) as smtp:
        worker = threading.Thread(target=smtp.serve_forever, daemon=True)
        worker.start()
        try:
            yield
        finally:
            smtp.shutdown()
            worker.join()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/fixture/inbox")
def inbox():
    with LOCK:
        return list(INBOX)


@app.get("/inbox", response_class=HTMLResponse)
def inbox_page():
    links = "".join(f'<li>{html.escape(mail["to"])} · <a href="{html.escape(mail["url"])}">'
                    f'{html.escape(mail["subject"])}</a></li>' for mail in reversed(inbox()))
    return f'<meta charset="utf-8"><title>ClipNest 测试邮箱</title><h1>ClipNest 测试邮箱</h1><ul>{links}</ul>'


@app.post("/fixture/fail-next-create")
def fail_next_create():
    global FAIL_NEXT_CREATE
    with LOCK:
        FAIL_NEXT_CREATE = True
    return {"ok": True}


@app.post("/internal/sessions")
def create_session(payload: dict):
    global FAIL_NEXT_CREATE
    with LOCK:
        key = payload["key"]
        params = payload["params"]
        for field in ("success_url", "cancel_url"):
            if not params[field].startswith(settings().membership_origin + "/?"):
                raise HTTPException(400, "测试回跳地址无效")
        if key not in KEYS:
            session_id = "cs_test_" + uuid4().hex
            price = params["line_items"][0]["price"]
            amount = {"price_mock_month": 1900, "price_mock_year": 14900}[price]
            SESSIONS[session_id] = {
                "id": session_id, "livemode": False, "mode": "payment", "currency": "cny",
                "client_reference_id": params["client_reference_id"], "metadata": params["metadata"],
                "amount_total": amount, "payment_intent": None, "status": "open", "payment_status": "unpaid",
                "url": f"{MOCK_URL}/checkout/{session_id}",
                "line_items": {"has_more": False, "data": [{"quantity": 1, "price": {"id": price, "unit_amount": amount}}]},
                "success_url": params["success_url"], "cancel_url": params["cancel_url"],
                "created": int(time.time()),
            }
            KEYS[key] = session_id
        if FAIL_NEXT_CREATE:
            FAIL_NEXT_CREATE = False
            raise HTTPException(503, "模拟 Stripe 已创建 Session 但响应丢失")
        return SESSIONS[KEYS[key]]


@app.get("/internal/find/{order_id}")
def find_sessions(order_id: str):
    with LOCK:
        return [session for session in SESSIONS.values() if session["client_reference_id"] == order_id]


@app.get("/internal/sessions/{session_id}")
def get_session(session_id: str):
    with LOCK:
        if session_id not in SESSIONS:
            raise HTTPException(404)
        return dict(SESSIONS[session_id])


@app.get("/internal/intents/{intent_id}")
def get_intent(intent_id: str):
    with LOCK:
        if intent_id not in INTENTS:
            raise HTTPException(404)
        return dict(INTENTS[intent_id])


def emit(kind: str, resource: dict, *, delivery: bool = True) -> str:
    event_id = "evt_test_" + uuid4().hex
    with LOCK:
        EVENT_LOG[event_id] = {
            "id": event_id, "object": "event", "type": kind,
            "livemode": False, "data": {"object": dict(resource)},
        }
    if delivery:
        replay(event_id)
    return event_id


@app.post("/fixture/replay/{event_id}")
def replay(event_id: str):
    with LOCK:
        raw = json.dumps(EVENT_LOG[event_id], separators=(",", ":")).encode()
    at = int(time.time())
    secret = settings().stripe_webhook_secret.get_secret_value().encode()
    mac = hmac.new(secret, str(at).encode() + b"." + raw, hashlib.sha256).hexdigest()
    with httpx.Client(timeout=10, trust_env=False) as client:
        result = client.post(f"{APP_URL}/api/billing/stripe/webhook", content=raw,
                             headers={"Stripe-Signature": f"t={at},v1={mac}"})
        result.raise_for_status()
        return {"event_id": event_id}


@app.post("/internal/sessions/{session_id}/expire")
def expire_session(session_id: str):
    with LOCK:
        session = SESSIONS[session_id]
        expired = session["status"] == "open"
        if expired:
            session["status"] = "expired"
        # Checkout cancellation may hold the order lock. Let the next API read see expiry immediately.
    if expired:
        emit("checkout.session.expired", session)
    return {"ok": True}


@app.post("/fixture/outcome/{session_id}/{outcome}")
def outcome_session(session_id: str, outcome: str, delivery: bool = True):
    with LOCK:
        session = SESSIONS[session_id]
        if outcome == "pay":
            if session["status"] != "open":
                raise HTTPException(409, "该模拟 Session 已关闭")
            intent_id = "pi_test_" + uuid4().hex
            INTENTS[intent_id] = {"order_id": session["client_reference_id"], "financial_state": "paid"}
            session.update(status="complete", payment_status="paid", payment_intent=intent_id)
            kind, resource = "checkout.session.completed", session
        elif outcome in {"partial", "refunded", "disputed", "won", "dispute_lost"} and session["payment_intent"]:
            intent_id = session["payment_intent"]
            INTENTS[intent_id]["financial_state"] = {"partial": "paid", "won": "paid"}.get(outcome, outcome)
            kind = {
                "partial": "refund.created", "refunded": "charge.refunded", "disputed": "charge.dispute.created",
                "won": "charge.dispute.closed", "dispute_lost": "charge.dispute.closed",
            }[outcome]
            resource = {"id": "fixture_" + uuid4().hex, "payment_intent": intent_id}
        else:
            raise HTTPException(409, "当前状态无法执行模拟操作")
    return {"event_id": emit(kind, resource, delivery=delivery)}


@app.get("/checkout/{session_id}", response_class=HTMLResponse)
def checkout_page(session_id: str, declined: bool = False):
    session = get_session(session_id)
    status = session["status"]
    message = "<p role='alert'>模拟发卡行拒绝付款，订单仍可重试。</p>" if declined else ""
    actions = (
        f'<form method="post" action="/checkout/{session_id}/pay"><button>模拟付款成功</button></form>'
        f'<form method="post" action="/checkout/{session_id}/decline"><button>模拟银行卡拒付</button></form>'
        if status == "open" else f"<p>模拟收银台状态 {status}</p>"
    )
    return (f'<meta charset="utf-8"><title>本地模拟收银台</title><h1>本地模拟收银台</h1>'
            f'<p>¥{session["amount_total"] / 100:g}，测试模式，无需填写卡号。</p>'
            f'{message}{actions}<a href="{html.escape(session["cancel_url"])}">返回网站</a>')


@app.post("/checkout/{session_id}/{action}")
def checkout_submit(session_id: str, action: str):
    if action == "decline":
        return RedirectResponse(f"/checkout/{session_id}?declined=1", 303)
    if action != "pay":
        raise HTTPException(404)
    outcome_session(session_id, "pay")
    url = get_session(session_id)["success_url"]
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(400)
    return RedirectResponse(url, 303)
