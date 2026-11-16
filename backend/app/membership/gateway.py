from datetime import UTC
from functools import lru_cache

import httpx
import stripe

from app.membership.config import settings
from app.membership.store import Order


EVENTS = {
    "checkout.session.completed", "checkout.session.expired",
    "refund.created", "refund.updated", "refund.failed", "charge.refunded",
    "charge.dispute.created", "charge.dispute.updated", "charge.dispute.closed",
}
MOCK_URL = "http://127.0.0.1:8102"


def checkout_params(order: Order) -> dict:
    return {
        "mode": "payment",
        "ui_mode": "hosted",
        "payment_method_types": ["card"],
        "adaptive_pricing": {"enabled": False},
        "line_items": [{"price": order.price_id, "quantity": 1}],
        "client_reference_id": order.id,
        "metadata": {"order_id": order.id},
        "payment_intent_data": {"metadata": {"order_id": order.id}},
        "success_url": f"{order.checkout_origin}/?membership_order={order.id}#pricing",
        "cancel_url": f"{order.checkout_origin}/?membership_order={order.id}&checkout_cancelled=1#pricing",
    }


class StripeGateway:
    def __init__(self, key: str):
        self.api = stripe.StripeClient(
            key, http_client=stripe.RequestsClient(timeout=5), max_network_retries=1
        ).v1

    def create(self, order: Order):
        price = self.api.prices.retrieve(order.price_id)
        if (
            not price.active or price.type != "one_time" or price.currency != "cny"
            or price.unit_amount != order.amount or price.livemode is not (order.mode == "live")
        ):
            raise ValueError("Stripe Price 须与站点的套餐金额和环境一致")
        return self.api.checkout.sessions.create(
            checkout_params(order), options={"idempotency_key": f"clipnest-checkout-{order.id}"}
        ).to_dict()

    def fetch(self, session_id: str):
        return self.api.checkout.sessions.retrieve(session_id, {"expand": ["line_items"]}).to_dict()

    def find_sessions(self, order: Order) -> list[str]:
        start = int(order.created_at.replace(tzinfo=UTC).timestamp())
        sessions = self.api.checkout.sessions.list({"created": {"gte": start - 60, "lte": start + 86400}})
        return [
            session.id for session in sessions.auto_paging_iter()
            if session.client_reference_id == order.id and session.to_dict()["metadata"].get("order_id") == order.id
        ]

    def expire(self, session_id: str, order_id: str):
        try:
            self.api.checkout.sessions.expire(session_id, options={"idempotency_key": f"clipnest-expire-{order_id}"})
        except stripe.InvalidRequestError:
            # A payment or Stripe's own expiry may have won the race.
            pass

    def order_for_intent(self, intent_id: str) -> str | None:
        if intent_id.startswith("ch_"):
            charge = self.api.charges.retrieve(intent_id)
            if not charge.payment_intent:
                return None
            intent_id = charge.payment_intent
        intent = self.api.payment_intents.retrieve(intent_id)
        return intent.to_dict()["metadata"].get("order_id")

    def financial_state(self, intent_id: str, amount: int) -> str:
        intent = self.api.payment_intents.retrieve(intent_id, {"expand": ["latest_charge"]})
        charge = intent.latest_charge
        if intent.status != "succeeded" or intent.amount_received != amount or intent.currency != "cny" or not charge:
            raise ValueError("Stripe PaymentIntent 未匹配到账金额")
        refunds = self.api.refunds.list({"charge": charge.id})
        if sum(refund.amount for refund in refunds.auto_paging_iter() if refund.status == "succeeded") >= amount:
            return "refunded"
        disputes = self.api.disputes.list({"charge": charge.id})
        statuses = {dispute.status for dispute in disputes.auto_paging_iter()}
        if "lost" in statuses:
            return "dispute_lost"
        if statuses.intersection({"needs_response", "under_review"}):
            return "disputed"
        return "paid"


class MockGateway:
    def call(self, method: str, path: str, **kwargs):
        with httpx.Client(timeout=5, trust_env=False) as client:
            result = client.request(method, f"{MOCK_URL}{path}", **kwargs)
            result.raise_for_status()
            return result.json()

    def create(self, order: Order):
        return self.call("POST", "/internal/sessions", json={
            "params": checkout_params(order), "key": order.id,
        })

    def fetch(self, session_id: str):
        return self.call("GET", f"/internal/sessions/{session_id}")

    def find_sessions(self, order: Order) -> list[str]:
        return [session["id"] for session in self.call("GET", f"/internal/find/{order.id}")]

    def expire(self, session_id: str, order_id: str):
        self.call("POST", f"/internal/sessions/{session_id}/expire")

    def order_for_intent(self, intent_id: str):
        return self.call("GET", f"/internal/intents/{intent_id}")["order_id"]

    def financial_state(self, intent_id: str, amount: int):
        return self.call("GET", f"/internal/intents/{intent_id}")["financial_state"]


@lru_cache
def gateway():
    config = settings()
    if config.stripe_mode == "mock":
        return MockGateway()
    return StripeGateway(config.stripe_secret_key.get_secret_value())


def decode_event(raw: bytes, signature: str):
    return stripe.Webhook.construct_event(
        raw, signature, settings().stripe_webhook_secret.get_secret_value(), tolerance=300
    ).to_dict()
