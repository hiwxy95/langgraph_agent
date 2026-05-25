from __future__ import annotations

from app.core.config import get_settings
from app.db.models import Base
from app.db.session import get_engine


async def init_business_tables() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_checkpoint_tables() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    settings = get_settings()
    with PostgresSaver.from_conn_string(settings.checkpoint_url) as checkpointer:
        checkpointer.setup()


async def init_all() -> None:
    await init_business_tables()
    init_checkpoint_tables()
