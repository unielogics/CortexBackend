from collections.abc import AsyncGenerator

from fastapi import Request

from unie_cortex.config import settings
from unie_cortex.db.database import SessionLocal
from unie_cortex.db.store import CortexStore, MongoCortexStore, SqlCortexStore


async def get_store(request: Request) -> AsyncGenerator[CortexStore, None]:
    if settings.use_mongodb:
        yield MongoCortexStore(request.app.state.mongo_db)
        return
    assert SessionLocal is not None
    async with SessionLocal() as session:
        try:
            yield SqlCortexStore(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
