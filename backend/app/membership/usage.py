from datetime import timedelta

from app.membership.store import SummaryUsage, current_membership, db, lock_user, utcnow


DAILY_ALLOWANCE = 20


def beijing_day(now) -> str:
    return (now + timedelta(hours=8)).date().isoformat()


def quota_snapshot(session, user_id: str) -> dict:
    usage = session.get(SummaryUsage, (user_id, beijing_day(utcnow())))
    return {"limit": DAILY_ALLOWANCE, "remaining": DAILY_ALLOWANCE - (usage.count if usage else 0)}


def reserve_summary(user_id: str) -> bool | None:
    """Return None for a free account, True for a charged slot, False for an exhausted member."""
    with db().begin() as session:
        lock_user(session, user_id)
        now = utcnow()
        if not current_membership(session, user_id, now):
            return None
        day = beijing_day(now)
        usage = session.get(SummaryUsage, (user_id, day))
        if not usage:
            session.add(SummaryUsage(user_id=user_id, day=day, count=1))
        elif usage.count >= DAILY_ALLOWANCE:
            return False
        else:
            usage.count += 1
        return True
