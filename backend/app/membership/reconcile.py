"""Reconcile one unresolved order against the configured Stripe account."""

import argparse
from datetime import timedelta

from app.membership.billing import apply_session, order_by_id
from app.membership.config import settings
from app.membership.gateway import gateway
from app.membership.store import db, lock_user, utcnow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id")
    parser.add_argument("--close-if-missing", action="store_true")
    args = parser.parse_args()

    if settings().stripe_mode == "disabled":
        parser.error("请配置订单所属的 Stripe 环境")
    with db().begin() as session:
        order = order_by_id(session, args.order_id)
        lock_user(session, order.user_id)
        session.refresh(order)
        provider = gateway()
        if order.session_id:
            apply_session(order, provider.fetch(order.session_id))
        else:
            matches = provider.find_sessions(order)
            if len(matches) == 1:
                apply_session(order, provider.fetch(matches[0]))
            elif (
                not matches and args.close_if_missing and order.status == "review"
                and order.created_at + timedelta(hours=48) < utcnow()
            ):
                order.status = "expired"
                order.checked_at = utcnow()
            else:
                print(f"匹配到 {len(matches)} 个 Checkout Session。订单保持 {order.status}，请在 Stripe 后台核查。")
                return
        print(f"订单 {order.id} 当前状态 {order.status}")


if __name__ == "__main__":
    main()
