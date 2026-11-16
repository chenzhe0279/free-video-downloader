"""Create MySQL tables for accounts, billing and member usage."""
from alembic import op
from sqlalchemy.dialects import mysql
import sqlalchemy as sa

revision = "0001_membership"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "membership_rate_buckets",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("digest"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )
    op.create_index(
        op.f("ix_membership_rate_buckets_minute"),
        "membership_rate_buckets",
        ["minute"], unique=False,
    )
    op.create_table(
        "membership_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )
    op.create_table(
        "membership_webhook_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("next_attempt", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("processed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )
    op.create_index(
        "ix_membership_events_queue",
        "membership_webhook_events",
        ["mode", "processed_at", "next_attempt"], unique=False,
    )
    op.create_table(
        "membership_mail_tokens",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=12), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["membership_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("digest"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )
    op.create_index(
        op.f("ix_membership_mail_tokens_expires_at"),
        "membership_mail_tokens",
        ["expires_at"], unique=False,
    )
    op.create_index(
        op.f("ix_membership_mail_tokens_user_id"),
        "membership_mail_tokens",
        ["user_id"], unique=False,
    )
    op.create_table(
        "membership_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan", sa.String(length=12), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("price_id", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("checkout_origin", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("intent_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("checked_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("paid_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["membership_users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_id"),
        sa.UniqueConstraint("session_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )
    op.create_index(
        "ix_membership_orders_reconcile",
        "membership_orders",
        ["status", "checked_at"], unique=False,
    )
    op.create_index(
        "ix_membership_orders_user_status",
        "membership_orders",
        ["user_id", "status"], unique=False,
    )
    op.create_table(
        "membership_sessions",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["membership_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("digest"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )
    op.create_index(
        op.f("ix_membership_sessions_expires_at"),
        "membership_sessions",
        ["expires_at"], unique=False,
    )
    op.create_index(
        op.f("ix_membership_sessions_user_id"),
        "membership_sessions",
        ["user_id"], unique=False,
    )
    op.create_table(
        "membership_summary_usage",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["membership_users.id"], ),
        sa.PrimaryKeyConstraint("user_id", "day"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
        mysql_engine="InnoDB"
    )


def downgrade() -> None:
    op.drop_table("membership_summary_usage")
    op.drop_table("membership_sessions")
    op.drop_table("membership_orders")
    op.drop_table("membership_mail_tokens")
    op.drop_table("membership_webhook_events")
    op.drop_table("membership_users")
    op.drop_table("membership_rate_buckets")
