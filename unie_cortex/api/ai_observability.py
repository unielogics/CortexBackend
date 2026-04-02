"""AI observability: list persisted NIM invocations."""

from fastapi import APIRouter, Depends, Query

from unie_cortex.db.deps import get_store
from unie_cortex.db.store import CortexStore

router = APIRouter()


@router.get("/invocations")
async def list_ai_invocations(
    tenant_id: str = Query(..., description="Tenant / org scope for filtering invocations"),
    capability: str | None = Query(None, description="Optional capability filter"),
    limit: int = Query(50, ge=1, le=500),
    store: CortexStore = Depends(get_store),
):
    return await store.ai_invocations_list(tenant_id=tenant_id, capability=capability, limit=limit)
