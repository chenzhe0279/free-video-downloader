from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import ForeignKey, Index, String, create_engine, select
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.membership.config import settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc_iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat() if value else None


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "membership_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    verified: Mapped[bool] = mapped_column(default=False)


class LoginSession(Base):
    __tablename__ = "membership_sessions"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), index=True)


class MailToken(Base):
    __tablename__ = "membership_mail_tokens"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(12))
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), index=True)


class RateBucket(Base):
    __tablename__ = "membership_rate_buckets"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    minute: Mapped[int] = mapped_column(index=True)
    count: Mapped[int] = mapped_column()


class Order(Base):
    __tablename__ = "membership_orders"
    __table_args__ = (
        Index("ix_membership_orders_user_status", "user_id", "status"),
        Index("ix_membership_orders_reconcile", "status", "checked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id))
    plan: Mapped[str] = mapped_column(String(12))
    days: Mapped[int] = mapped_column()
    amount: Mapped[int] = mapped_column()
    price_id: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(24))
    checkout_origin: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    intent_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    checked_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    paid_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    expires_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class WebhookEvent(Base):
    __tablename__ = "membership_webhook_events"
    __table_args__ = (Index("ix_membership_events_queue", "mode", "processed_at", "next_attempt"),)

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    next_attempt: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    processed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    attempts: Mapped[int] = mapped_column(default=0)


class SummaryUsage(Base):
    __tablename__ = "membership_summary_usage"

    user_id: Mapped[str] = mapped_column(ForeignKey(User.id), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)


@lru_cache
def db():
    if not settings().enabled:
        raise RuntimeError("会员数据库未启用")
    engine = create_engine(
        settings().membership_db_url.get_secret_value(),
        pool_pre_ping=True,
        pool_timeout=5,
        isolation_level="READ COMMITTED",
        connect_args={"connect_timeout": 5, "read_timeout": 10, "write_timeout": 10, "charset": "utf8mb4"},
    )
    return sessionmaker(engine, expire_on_commit=False)


def lock_user(session, user_id: str) -> User | None:
    return session.scalar(select(User).where(User.id == user_id).with_for_update())


def current_membership(session, user_id: str, now: datetime) -> Order | None:
    return session.scalar(select(Order).where(
        Order.user_id == user_id, Order.mode == settings().stripe_mode,
        Order.status == "paid", Order.expires_at > now,
    ).order_by(Order.expires_at.desc()).limit(1))
