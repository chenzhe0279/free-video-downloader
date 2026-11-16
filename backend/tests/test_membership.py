import hashlib
import hmac
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.main import app
from app.membership import billing
from app.membership.config import settings
from app.membership.gateway import MockGateway, StripeGateway, gateway
from app.membership.store import Order, SummaryUsage, User, WebhookEvent, db, utcnow
from app.membership.usage import beijing_day
from app.services.summary.settings import get_summary_settings
from app.services.summary.tasks import SummaryTaskManager
from tests import membership_fixture as fixture


ORIGIN = "http://127.0.0.1:8000"
SECRET = "whsec_clipnest_integration_only"
PASSWORD = "local-only-password"


class MembershipUnitTests(unittest.TestCase):
    def test_beijing_midnight(self):
        self.assertEqual(beijing_day(datetime(2026, 11, 16, 15, 59, 59)), "2026-11-16")
        self.assertEqual(beijing_day(datetime(2026, 11, 16, 16)), "2026-11-17")

    @patch("app.membership.gateway.stripe.StripeClient")
    def test_stripe_checkout_price_and_idempotency(self, sdk):
        stripe_api = sdk.return_value.v1
        provider = StripeGateway("sk_test_fixture")
        order = Order(id="order-unit", price_id="price_month", mode="sandbox", amount=1900,
                      checkout_origin=ORIGIN)
        price = SimpleNamespace(active=True, currency="cny", type="one_time", unit_amount=2000, livemode=False)
        stripe_api.prices.retrieve.return_value = price
        with self.assertRaises(ValueError):
            provider.create(order)
        stripe_api.checkout.sessions.create.assert_not_called()
        price.unit_amount = 1900
        stripe_api.checkout.sessions.create.return_value.to_dict.return_value = {"id": "cs_test_fixture"}
        self.assertEqual(provider.create(order), {"id": "cs_test_fixture"})
        args, kwargs = stripe_api.checkout.sessions.create.call_args
        self.assertEqual(kwargs["options"]["idempotency_key"], "clipnest-checkout-order-unit")
        self.assertEqual(args[0]["line_items"], [{"price": "price_month", "quantity": 1}])
        self.assertEqual(args[0]["payment_method_types"], ["card"])
        self.assertEqual(args[0]["adaptive_pricing"], {"enabled": False})

    @patch("app.membership.gateway.stripe.StripeClient")
    def test_stripe_only_succeeded_refunds_count_towards_revocation(self, sdk):
        stripe_api = sdk.return_value.v1
        provider = StripeGateway("sk_test_fixture")
        stripe_api.payment_intents.retrieve.return_value = SimpleNamespace(
            status="succeeded", amount_received=1900, currency="cny", latest_charge=SimpleNamespace(id="ch_fixture"),
        )
        refunds = stripe_api.refunds.list.return_value
        refunds.auto_paging_iter.return_value = [
            SimpleNamespace(amount=900, status="succeeded"), SimpleNamespace(amount=1000, status="pending"),
        ]
        disputes = Mock()
        disputes.auto_paging_iter.return_value = [SimpleNamespace(status="under_review")]
        stripe_api.disputes.list.return_value = disputes
        self.assertEqual(provider.financial_state("pi_fixture", 1900), "disputed")
        disputes.auto_paging_iter.return_value = [SimpleNamespace(status="won")]
        self.assertEqual(provider.financial_state("pi_fixture", 1900), "paid")
        refunds.auto_paging_iter.return_value[1].status = "succeeded"
        self.assertEqual(provider.financial_state("pi_fixture", 1900), "refunded")


@unittest.skipUnless(os.getenv("CLIPNEST_MEMBERSHIP_TEST_DB_URL"), "需要独立 MySQL 测试库")
class MembershipIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "VDS_MEMBERSHIP_DB_URL": os.environ["CLIPNEST_MEMBERSHIP_TEST_DB_URL"],
            "VDS_MEMBERSHIP_ORIGIN": ORIGIN,
            "VDS_STRIPE_MODE": "mock",
            "VDS_STRIPE_WEBHOOK_SECRET": SECRET,
            "VDS_MEMBERSHIP_CHECKOUT_ENABLED": "true",
            "VDS_SMTP_HOST": "127.0.0.1",
            "VDS_SMTP_FROM": "clipnest@example.com",
            "VDS_DEEPSEEK_API_KEY": "fixture",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.reset_caches()
        self.addCleanup(self.reset_caches)
        # The config guard rejects every database name except clipnest_test for this mode.
        self.assertEqual(settings().stripe_mode, "mock")
        self.app = self.new_client()
        self.provider = TestClient(fixture.app)
        self.mail = {}
        self.emails = []
        self.events = []
        self.addCleanup(self.delete_test_rows)
        for patcher in (
            patch("app.membership.auth.send_link", side_effect=self.capture_mail),
            patch("app.membership.gateway.MockGateway.call", side_effect=self.provider_request),
            patch("tests.membership_fixture.replay", side_effect=self.deliver),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def new_client():
        return TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}, client=("127.0.0.1", 1234))

    @staticmethod
    def reset_caches():
        if db.cache_info().currsize:
            db().kw["bind"].dispose()
        db.cache_clear()
        settings.cache_clear()
        gateway.cache_clear()
        get_summary_settings.cache_clear()

    def delete_test_rows(self):
        with db().begin() as session:
            users = select(User.id).where(User.email.in_(self.emails))
            session.execute(delete(SummaryUsage).where(SummaryUsage.user_id.in_(users)))
            session.execute(delete(Order).where(Order.user_id.in_(users)))
            session.execute(delete(User).where(User.email.in_(self.emails)))
            session.execute(delete(WebhookEvent).where(WebhookEvent.id.in_(self.events)))

    def capture_mail(self, email, purpose, token):
        self.mail[(email, purpose)] = token

    def provider_request(self, method, path, **kwargs):
        result = self.provider.request(method, path, **kwargs)
        result.raise_for_status()
        return result.json()

    def deliver(self, event_id):
        self.events.append(event_id)
        raw = json.dumps(fixture.EVENT_LOG[event_id]).encode()
        stamp = str(int(time.time()))
        mac = hmac.new(SECRET.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        response = self.app.post("/api/billing/stripe/webhook", content=raw,
                                 headers={"Stripe-Signature": f"t={stamp},v1={mac}"})
        self.assertEqual(response.status_code, 200, response.text)
        return {"event_id": event_id}

    def identity(self, *, verified=True, client=None):
        client = client or self.app
        email = f"clipnest-{uuid4().hex}@example.com"
        self.emails.append(email)
        credentials = {"email": email, "password": PASSWORD}
        result = client.post("/api/account/register", json=credentials)
        self.assertEqual(result.status_code, 200, result.text)
        if verified:
            result = client.post("/api/account/verify", json={
                "token": self.mail[email, "verify"], "password": PASSWORD,
            })
            self.assertEqual(result.status_code, 200, result.text)
        result = client.post("/api/account/login", json=credentials)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("HttpOnly", result.headers["set-cookie"])
        return email

    def checkout(self, plan="month"):
        response = self.app.post("/api/billing/checkout", json={"plan": plan})
        self.assertEqual(response.status_code, 200, response.text)
        order = response.json()
        return order["id"], order["checkout_url"].rsplit("/", 1)[-1]

    def order(self, order_id):
        return self.app.get(f"/api/billing/orders/{order_id}").json()

    def status(self):
        return self.app.get("/api/billing/account").json()

    def advance_worker(self):
        for _ in range(50):
            if not billing.process_event():
                return
        self.fail("Webhook 队列未处理完")

    def outcome(self, session_id, result, *, delivery=True):
        response = self.provider.post(f"/fixture/outcome/{session_id}/{result}", params={"delivery": delivery})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["event_id"]

    def test_account_validation_password_reset_and_session_revocation(self):
        email = self.identity(verified=False)
        checkout = self.app.post("/api/billing/checkout", json={"plan": "month"})
        self.assertEqual(checkout.status_code, 403)
        token = self.mail[email, "verify"]
        bad_origin = self.app.post("/api/account/verify", headers={"Origin": "https://example.com"},
                                   json={"token": token, "password": PASSWORD})
        self.assertEqual(bad_origin.status_code, 403)
        self.assertEqual(self.app.post("/api/account/verify", json={"token": token, "password": PASSWORD + "no"}).status_code, 401)
        self.assertEqual(self.app.post("/api/account/verify", json={"token": token, "password": PASSWORD}).status_code, 200)
        self.assertEqual(self.app.post("/api/account/verify", json={"token": token, "password": PASSWORD}).status_code, 400)
        other = self.new_client()
        self.assertEqual(other.post("/api/account/login", json={"email": email, "password": PASSWORD}).status_code, 200)
        self.app.post("/api/account/password-reset-email", json={"email": email}).raise_for_status()
        payload = {"token": self.mail[email, "reset"], "password": PASSWORD + "new"}
        self.app.post("/api/account/password-reset", json=payload).raise_for_status()
        self.assertIsNone(self.status()["user"])
        self.assertIsNone(other.get("/api/billing/account").json()["user"])
        self.assertEqual(self.app.post("/api/account/password-reset", json=payload).status_code, 400)
        self.assertEqual(other.post("/api/account/login", json={"email": email, "password": PASSWORD}).status_code, 401)
        other.post("/api/account/login", json={"email": email, "password": payload["password"]}).raise_for_status()
        self.assertTrue(other.get("/api/billing/account").json()["user"]["verified"])

    def test_concurrency_retry_and_order_access(self):
        self.identity()
        self.provider.post("/fixture/fail-next-create").raise_for_status()
        response = self.app.post("/api/billing/checkout", json={"plan": "month"})
        self.assertEqual(response.status_code, 503)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.checkout(), range(4)))
        self.assertEqual(len(set(results)), 1)
        order_id, session_id = results[0]
        self.assertEqual(len(MockGateway().call("GET", f"/internal/find/{order_id}")), 1)
        self.assertEqual(self.app.post("/api/billing/checkout", json={"plan": "year"}).status_code, 409)
        stranger = self.new_client()
        self.identity(client=stranger)
        self.assertEqual(stranger.get(f"/api/billing/orders/{order_id}").status_code, 404)
        self.assertEqual(stranger.post(f"/api/billing/orders/{order_id}/cancel", json={}).status_code, 404)
        self.app.post(f"/api/billing/orders/{order_id}/cancel", json={}).raise_for_status()
        self.assertEqual(self.order(order_id)["status"], "expired")
        self.assertEqual(self.provider.post(f"/fixture/outcome/{session_id}/pay").status_code, 409)
        new_id, _ = self.checkout("year")
        self.assertNotEqual(new_id, order_id)

    def test_verified_durable_fulfillment_refunds_disputes_and_cancellation_race(self):
        self.identity()
        order_id, session_id = self.checkout("year")
        forged = self.app.post("/api/payment/webhook", content=b'{"object":"event"}',
                               headers={"Stripe-Signature": "t=0,v1=bad"})
        self.assertEqual(forged.status_code, 400)
        self.assertIsNone(self.status()["membership"])

        paid_event = self.outcome(session_id, "pay")
        self.deliver(paid_event)
        with db()() as session:
            self.assertIsNone(session.get(WebhookEvent, paid_event).processed_at)
        self.reset_caches()  # Reconnect to MySQL as a new worker would after a restart.
        self.advance_worker()
        order = self.order(order_id)
        self.assertEqual(order["status"], "paid")
        self.assertEqual(datetime.fromisoformat(order["expires_at"]) - datetime.fromisoformat(order["paid_at"]),
                         timedelta(days=365))
        self.assertEqual(self.app.post("/api/billing/checkout", json={"plan": "month"}).status_code, 409)
        self.app.post(f"/api/billing/orders/{order_id}/cancel", json={}).raise_for_status()
        self.assertEqual(self.order(order_id)["status"], "paid")

        self.outcome(session_id, "partial")
        self.advance_worker()
        self.assertEqual(self.order(order_id)["status"], "paid")
        disputed_event = self.outcome(session_id, "disputed")
        self.advance_worker()
        self.assertEqual(self.order(order_id)["status"], "disputed")
        self.assertIsNone(self.status()["membership"])
        older_undelivered_event = self.outcome(session_id, "disputed", delivery=False)
        won_event = self.outcome(session_id, "won")
        self.advance_worker()
        self.deliver(disputed_event)
        self.deliver(older_undelivered_event)
        self.deliver(won_event)
        self.advance_worker()
        self.assertEqual(self.order(order_id)["expires_at"], order["expires_at"])
        self.assertEqual(self.order(order_id)["status"], "paid")

        self.outcome(session_id, "refunded")
        self.advance_worker()
        self.assertEqual(self.order(order_id)["status"], "refunded")
        self.assertIsNone(self.status()["membership"])
        second_order, second_session = self.checkout()
        late_event = self.outcome(second_session, "pay", delivery=False)
        result = self.app.post(f"/api/billing/orders/{second_order}/cancel", json={})
        result.raise_for_status()
        self.assertEqual(result.json()["status"], "paid")
        self.deliver(late_event)
        self.advance_worker()
        paid = self.order(second_order)
        self.assertEqual(datetime.fromisoformat(paid["expires_at"]) - datetime.fromisoformat(paid["paid_at"]),
                         timedelta(days=30))
        self.outcome(second_session, "dispute_lost")
        self.advance_worker()
        self.assertEqual(self.order(second_order)["status"], "dispute_lost")

    def test_summary_quota_cache_and_expiry(self):
        self.identity()
        order_id, session_id = self.checkout()
        self.outcome(session_id, "pay")
        self.advance_worker()
        manager = SummaryTaskManager()
        counter = 0

        async def finish(task, _normalized):
            manager._release_slot(task)

        def run_summary(ip):
            nonlocal counter
            counter += 1
            response = self.app.post("/api/summary", headers={"X-Forwarded-For": ip},
                                     json={"url": f"https://example.com/{counter}", "force": False})
            return response.status_code

        normalized = {"duration": 300, "id": "offline", "title": "Offline fixture", "platform": "offline"}
        with (
            patch("app.api.summary.summary_manager", manager),
            patch("app.api.summary.validate_public_url", side_effect=lambda url: url),
            patch("app.services.summary.tasks.media.probe", new=AsyncMock(return_value=normalized)),
            patch.object(manager, "_run", side_effect=finish),
        ):
            self.assertEqual([run_summary(f"192.0.2.{i}") for i in range(1, 21)], [202] * 20)
            self.assertEqual(run_summary("192.0.2.21"), 429)
            self.assertEqual(self.status()["quota"], {"limit": 20, "remaining": 0})
            with patch.object(manager, "_get_cached", return_value=object()), patch.object(
                manager, "_task_from_cache", return_value=manager.get(next(iter(manager._tasks))),
            ):
                self.assertEqual(run_summary("192.0.2.22"), 202)
            self.assertEqual(self.status()["quota"]["remaining"], 0)
            with db().begin() as session:
                session.get(Order, order_id).expires_at = utcnow() - timedelta(seconds=1)
            self.assertIsNone(self.status()["membership"])
            self.assertEqual([run_summary("192.0.2.100") for _ in range(4)], [202, 202, 202, 429])

    def test_amount_mismatch_stays_unfulfilled_and_retries(self):
        self.identity()
        order_id, session_id = self.checkout()
        event_id = self.outcome(session_id, "pay")
        fixture.SESSIONS[session_id]["amount_total"] = 1
        self.advance_worker()
        self.assertEqual(self.order(order_id)["status"], "open")
        self.assertIsNone(self.status()["membership"])
        with db().begin() as session:
            event = session.get(WebhookEvent, event_id)
            self.assertEqual(event.attempts, 1)
            self.assertIsNone(event.processed_at)
            event.next_attempt = utcnow()
        fixture.SESSIONS[session_id]["amount_total"] = 1900
        self.advance_worker()
        self.assertEqual(self.order(order_id)["status"], "paid")
