import asyncio
import logging
import time
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert
from starlette.concurrency import run_in_threadpool

from app.membership.auth import account_write, require_user, signed_in_user, throttle
from app.membership.config import settings
from app.membership.gateway import EVENTS, MOCK_URL, decode_event, gateway
from app.membership.store import (
    LoginSession, MailToken, Order, RateBucket, WebhookEvent, current_membership, db, lock_user, utc_iso, utcnow,
)
from app.membership.usage import quota_snapshot


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/api/payment", tags=["billing"])
PLANS = {"month": (1900, 30), "year": (14900, 365)}
PENDING = {"creating", "open", "review"}
REVISIT = {"open", "disputed"}
SAFE_RETRY = timedelta(hours=23)


class CheckoutInput(BaseModel):
    plan: str


def pending_order(session, user_id: str):
    return session.scalar(select(Order).where(
        Order.user_id == user_id, Order.mode == settings().stripe_mode, Order.status.in_(PENDING),
    ).limit(1))


def order_json(order: Order, checkout_url: str | None = None):
    return {
        "id": order.id, "plan": order.plan, "amount": order.amount, "status": order.status,
        "created_at": utc_iso(order.created_at), "paid_at": utc_iso(order.paid_at),
        "expires_at": utc_iso(order.expires_at), "checkout_url": checkout_url,
    }


def order_by_id(session, order_id: str, user_id: str | None = None) -> Order:
    order = session.get(Order, order_id, populate_existing=True)
    if not order or order.mode != settings().stripe_mode or (user_id and order.user_id != user_id):
        raise HTTPException(404, "订单不存在")
    return order


@router.get("/account")
def account(request: Request):
    config = settings()
    response = {
        "enabled": config.enabled, "checkout_enabled": config.membership_checkout_enabled,
        "user": None, "membership": None, "quota": None, "orders": [],
    }
    user = signed_in_user(request)
    if user is None:
        return response
    with db()() as session:
        active = current_membership(session, user.id, utcnow())
        orders = session.scalars(select(Order).where(
            Order.user_id == user.id, Order.mode == config.stripe_mode,
        ).order_by(Order.created_at.desc()).limit(20))
        response.update(
            user={"email": user.email, "verified": user.verified},
            membership=order_json(active) if active else None,
            quota=quota_snapshot(session, user.id) if active else None,
            orders=[order_json(order) for order in orders],
        )
    return response


def reserve_order(user_id: str, plan: str) -> Order:
    config = settings()
    with db().begin() as session:
        lock_user(session, user_id)
        now = utcnow()
        active = current_membership(session, user_id, now)
        disputed = session.scalar(select(Order.id).where(
            Order.user_id == user_id, Order.mode == config.stripe_mode,
            Order.status == "disputed", Order.expires_at > now,
        ).limit(1))
        if active or disputed:
            raise HTTPException(409, "当前会员周期结束后可再次购买")
        previous = pending_order(session, user_id)
        if previous:
            if previous.plan != plan:
                raise HTTPException(409, "请先取消目前的待付款订单，再选择其他套餐")
            return previous
        amount, days = PLANS[plan]
        price_id = f"price_mock_{plan}" if config.stripe_mode == "mock" else getattr(config, f"stripe_{plan}_price_id")
        order = Order(
            id=str(uuid4()), user_id=user_id, plan=plan, amount=amount, days=days,
            price_id=price_id, mode=config.stripe_mode, status="creating",
            checkout_origin=config.membership_origin, created_at=now, checked_at=now,
        )
        session.add(order)
        return order


def validate_ref(order: Order, remote) -> None:
    if (
        remote["client_reference_id"] != order.id
        or remote["metadata"].get("order_id") != order.id
        or remote["mode"] != "payment"
        or remote["livemode"] is not (order.mode == "live")
        or (order.session_id and remote["id"] != order.session_id)
    ):
        raise ValueError("Stripe Checkout Session 与本地订单不匹配")


def apply_session(order: Order, remote) -> None:
    validate_ref(order, remote)
    order.session_id = remote["id"]
    order.checked_at = utcnow()
    if remote["status"] == "expired" and remote["payment_status"] == "unpaid" and not order.paid_at:
        order.status = "expired"
        return
    if remote["payment_status"] != "paid":
        if remote["status"] == "open" and order.status == "creating":
            order.status = "open"
        return

    lines = remote["line_items"]["data"]
    if (
        remote["status"] != "complete" or remote["currency"] != "cny"
        or remote["amount_total"] != order.amount or remote["line_items"]["has_more"]
        or len(lines) != 1 or lines[0]["quantity"] != 1
        or lines[0]["price"]["id"] != order.price_id
        or lines[0]["price"]["unit_amount"] != order.amount
        or not remote["payment_intent"]
        or (order.intent_id and remote["payment_intent"] != order.intent_id)
    ):
        raise ValueError("Stripe 付款金额、套餐或支付标识不匹配")
    intent_id = remote["payment_intent"]
    order.status = gateway().financial_state(intent_id, order.amount)
    order.intent_id = intent_id
    if not order.paid_at:
        order.paid_at = order.checked_at
        order.expires_at = order.paid_at + timedelta(days=order.days)


def checkout_url(remote) -> str | None:
    if remote["status"] != "open":
        return None
    url = remote["url"]
    parsed = urlsplit(url or "")
    allowed = (
        url.startswith(f"{MOCK_URL}/checkout/") if settings().stripe_mode == "mock" and url
        else parsed.netloc == "checkout.stripe.com" and parsed.scheme == "https"
    )
    if not allowed:
        raise ValueError("Stripe 返回的收银台地址无效")
    return url


def get_remote(order: Order):
    if order.session_id:
        return gateway().fetch(order.session_id)
    if order.created_at + SAFE_RETRY <= utcnow() or order.status == "review":
        order.status = "review"
        return None
    return gateway().create(order)


def checkout_action(user_id: str, order_id: str, *, cancel: bool = False):
    with db().begin() as session:
        lock_user(session, user_id)
        order = order_by_id(session, order_id, user_id)
        if order.status not in PENDING:
            return order_json(order)
        remote = get_remote(order)
        if remote is None:
            return order_json(order)
        validate_ref(order, remote)
        if cancel and remote["status"] == "open":
            gateway().expire(remote["id"], order.id)
            remote = gateway().fetch(remote["id"])
        if remote["payment_status"] == "paid" and not remote.get("line_items"):
            remote = gateway().fetch(remote["id"])
        apply_session(order, remote)
        return order_json(order, None if cancel else checkout_url(remote))


def checkout_response(user_id: str, order_id: str, *, cancel: bool = False):
    try:
        return checkout_action(user_id, order_id, cancel=cancel)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("结账请求待重试，订单=%s，错误类型=%s", order_id, type(exc).__name__)
        raise HTTPException(503, "暂时无法确认收银台状态，请重试同一订单") from None


@router.post("/checkout")
def checkout(payload: CheckoutInput, request: Request):
    account_write(request)
    if not settings().membership_checkout_enabled:
        raise HTTPException(503, "暂未开放会员购买")
    user = require_user(request, verified=True)
    throttle(request, "checkout", user.id, 20)
    if payload.plan not in PLANS:
        raise HTTPException(422, "无效套餐")
    order = reserve_order(user.id, payload.plan)
    return checkout_response(user.id, order.id)


@router.get("/orders/{order_id}")
def get_order(order_id: str, request: Request):
    user = require_user(request)
    with db()() as session:
        return order_json(order_by_id(session, order_id, user.id))


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, request: Request):
    account_write(request)
    user = require_user(request, verified=True)
    throttle(request, "cancel", user.id, 20)
    return checkout_response(user.id, order_id, cancel=True)


def save_event(event) -> None:
    mode = settings().stripe_mode
    if event["livemode"] is not (mode == "live"):
        raise HTTPException(400, "Webhook 环境不匹配")
    kind = event["type"]
    if kind not in EVENTS:
        return
    item = event["data"]["object"]
    resource_id = item["id"]
    if not kind.startswith("checkout.session."):
        resource_id = item.get("payment_intent") or item.get("charge") or (
            item["id"] if kind == "charge.refunded" else None
        )
    if not isinstance(resource_id, str):
        return
    now = utcnow()
    with db().begin() as session:
        stmt = insert(WebhookEvent).values(
            id=event["id"], mode=mode, kind=kind, resource_id=resource_id,
            created_at=now, next_attempt=now, attempts=0,
        )
        session.execute(stmt.on_duplicate_key_update(id=WebhookEvent.id))


@router.post("/stripe/webhook")
@webhook_router.post("/webhook")
async def webhook(request: Request):
    if settings().stripe_mode == "disabled":
        raise HTTPException(404, "Webhook 未启用")
    parts = bytearray()
    async for chunk in request.stream():
        if len(parts) + len(chunk) > 512 * 1024:
            raise HTTPException(413, "Webhook 请求过大")
        parts.extend(chunk)
    try:
        event = decode_event(bytes(parts), request.headers.get("stripe-signature", ""))
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Webhook 签名无效") from None
    await run_in_threadpool(save_event, event)
    return {"received": True}


def synchronize_event(session, event: WebhookEvent) -> None:
    provider = gateway()
    is_checkout = event.kind.startswith("checkout.session.")
    if is_checkout:
        remote = provider.fetch(event.resource_id)
        order_id = remote["metadata"].get("order_id")
    else:
        order_id = provider.order_for_intent(event.resource_id)
    if not order_id:
        return
    order = session.get(Order, order_id)
    if not order or order.mode != event.mode:
        return
    lock_user(session, order.user_id)
    session.refresh(order)
    if is_checkout:
        # Refresh after getting the same lock used by checkout and cancellation.
        remote = provider.fetch(event.resource_id)
    else:
        if not order.session_id:
            raise RuntimeError("等待 Stripe Checkout Session 绑定")
        remote = provider.fetch(order.session_id)
    apply_session(order, remote)


def process_event() -> bool:
    with db().begin() as session:
        event = session.scalar(select(WebhookEvent).where(
            WebhookEvent.mode == settings().stripe_mode, WebhookEvent.processed_at.is_(None),
            WebhookEvent.next_attempt <= utcnow(),
        ).order_by(WebhookEvent.next_attempt).limit(1).with_for_update(skip_locked=True))
        if not event:
            return False
        try:
            with session.begin_nested():
                synchronize_event(session, event)
        except Exception as exc:
            event.attempts += 1
            event.next_attempt = utcnow() + timedelta(seconds=min(3600, 2 ** min(event.attempts, 12)))
            logger.warning("Stripe 事件待重试，事件=%s，次数=%s，错误类型=%s",
                           event.id, event.attempts, type(exc).__name__)
        else:
            event.processed_at = utcnow()
        return True


def reconcile_order() -> bool:
    now = utcnow()
    mode = settings().stripe_mode
    with db()() as session:
        item = session.execute(select(Order.id, Order.user_id).where(
            Order.mode == mode,
            (
                ((Order.status == "creating") & (Order.created_at <= now - SAFE_RETRY))
                | (Order.status.in_(REVISIT) & (Order.checked_at <= now - timedelta(minutes=2)))
            ),
        ).order_by(Order.checked_at).limit(1)).first()
    if not item:
        return False
    with db().begin() as session:
        lock_user(session, item.user_id)
        order = order_by_id(session, item.id, item.user_id)
        if order.checked_at > now - timedelta(minutes=2) or order.status not in REVISIT | {"creating"}:
            return False
        try:
            with session.begin_nested():
                if order.session_id:
                    apply_session(order, gateway().fetch(order.session_id))
                elif order.created_at <= now - SAFE_RETRY:
                    order.status = "review"
                    logger.warning("Stripe 订单超过幂等重试窗口，需人工对账，订单=%s", order.id)
        except Exception as exc:
            logger.warning("Stripe 订单对账失败，订单=%s，错误类型=%s", order.id, type(exc).__name__)
        order.checked_at = utcnow()
        return True


def prune_auth() -> None:
    now = utcnow()
    with db().begin() as session:
        for table in (LoginSession, MailToken):
            session.execute(delete(table).where(table.expires_at <= now))
        session.execute(delete(RateBucket).where(RateBucket.minute < int(time.time()) // 60 - 1440))


async def maintenance():
    cycles = 0
    while True:
        try:
            if cycles % 240 == 0:
                await run_in_threadpool(prune_auth)
            if settings().stripe_mode != "disabled":
                for _ in range(10):
                    if not await run_in_threadpool(process_event):
                        break
                await run_in_threadpool(reconcile_order)
        except Exception as exc:
            logger.error("会员后台任务失败，错误类型=%s", type(exc).__name__)
        cycles += 1
        await asyncio.sleep(15)
