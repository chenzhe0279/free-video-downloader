from alembic import context
from sqlalchemy import create_engine

from app.membership.config import settings
from app.membership.store import Base


def run() -> None:
    config = settings()
    if not config.enabled:
        raise RuntimeError("请配置 VDS_MEMBERSHIP_DB_URL")
    url = config.membership_db_url.get_secret_value()
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, connect_args={"charset": "utf8mb4"})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
