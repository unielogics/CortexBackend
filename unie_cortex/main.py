import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from unie_cortex.api.assessment import router as assessment_router
from unie_cortex.api.ai_observability import router as ai_observability_router
from unie_cortex.api.eia import router as eia_router
from unie_cortex.api.integrations import router as integrations_router
from unie_cortex.api.network import router as network_router
from unie_cortex.api.maiw import router as maiw_router
from unie_cortex.api.maiw_warehouse import router as maiw_warehouse_router
from unie_cortex.api.item_intelligence import router as item_intelligence_router
from unie_cortex.api.operational import router as operational_router
from unie_cortex.config import settings
from unie_cortex.db.database import SessionLocal, init_sql_db
from unie_cortex.product_identity import SELLER_OPTIMIZATION_ENGINE_NAME, seller_optimization_engine_identity
from unie_cortex.db.store import MongoCortexStore, SqlCortexStore, ensure_mongo_indexes
from unie_cortex.middleware.auth_middleware import APIAuthMiddleware
from unie_cortex.middleware.logging_middleware import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    app.state.mongo_client = None

    if settings.use_mongodb:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.mongodb_uri)
        app.state.mongo_client = client
        app.state.mongo_db = client[settings.mongodb_db]
        await ensure_mongo_indexes(app.state.mongo_db)
        await MongoCortexStore(app.state.mongo_db).templates_seed_default()
    else:
        await init_sql_db()
        assert SessionLocal is not None
        async with SessionLocal() as session:
            await SqlCortexStore(session).templates_seed_default()
            await session.commit()

    yield

    if app.state.mongo_client is not None:
        app.state.mongo_client.close()


app = FastAPI(
    title=SELLER_OPTIMIZATION_ENGINE_NAME,
    description=(
        f"{SELLER_OPTIMIZATION_ENGINE_NAME} — Amazon seller fee, fulfillment, and network planning "
        "(assessment, order-financial ingest, MAIW, warehouse intelligence; MongoDB or SQLite)."
    ),
    version="0.4.0",
    lifespan=lifespan,
)

# CORS: env-driven origins; empty = * for dev
_cors_origins = [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
] if settings.cors_origins.strip() else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Auth: when API_KEY or API_KEYS set, require key on /v1/* and /portal
app.add_middleware(APIAuthMiddleware)
# Request logging with request_id and secret redaction
app.add_middleware(RequestLoggingMiddleware)

app.include_router(assessment_router, prefix="/v1/assessment", tags=["assessment"])
app.include_router(ai_observability_router, prefix="/v1/ai", tags=["ai-observability"])
app.include_router(operational_router, prefix="/v1/operational", tags=["operational"])
app.include_router(
    item_intelligence_router,
    prefix="/v1/operational",
    tags=["Product Research Optimization"],
)
app.include_router(maiw_router, prefix="/v1/maiw", tags=["maiw"])
app.include_router(maiw_warehouse_router, prefix="/v1", tags=["warehouse-intelligence"])
app.include_router(integrations_router, prefix="/v1/integrations", tags=["integrations"])
app.include_router(eia_router, prefix="/v1/integrations/eia", tags=["eia"])
app.include_router(network_router, prefix="/v1/network", tags=["network"])

portal_dir = os.path.join(os.path.dirname(__file__), "..", "portal", "dist")
if os.path.isdir(portal_dir):
    app.mount("/portal", StaticFiles(directory=portal_dir, html=True), name="portal")


@app.get("/health")
async def health():
    """Basic health. Use /health/deps for dependency readiness (mongo ping)."""
    return {
        "status": "ok",
        "service": SELLER_OPTIMIZATION_ENGINE_NAME,
        "seller_optimization_engine": seller_optimization_engine_identity(),
        "database": "mongodb" if settings.use_mongodb else "sql",
    }


@app.get("/health/deps")
async def health_deps(request: Request):
    """Extended health with dependency checks (Mongo ping when using MongoDB)."""
    deps = {"database": "unknown", "mongo": None}
    if settings.use_mongodb:
        try:
            mongo_db = request.app.state.mongo_db
            if mongo_db:
                await mongo_db.command("ping")
                deps["database"] = "mongodb"
                deps["mongo"] = "ok"
            else:
                deps["database"] = "mongodb"
                deps["mongo"] = "not_initialized"
        except Exception as e:
            deps["database"] = "mongodb"
            deps["mongo"] = f"error: {type(e).__name__}"
    else:
        deps["database"] = "sql"
        deps["mongo"] = "n/a"
    ok = deps.get("mongo") in ("ok", "n/a", "not_initialized")
    return {"status": "ok" if ok else "degraded", "dependencies": deps}


@app.get("/")
async def root():
    return {
        "service": SELLER_OPTIMIZATION_ENGINE_NAME,
        "seller_optimization_engine": seller_optimization_engine_identity(),
        "docs": "/docs",
        "maiw": "/v1/maiw/query",
        "warehouse_intelligence": "/v1/pick-pathing/batch-optimize",
        "network": "/v1/network/capabilities",
        "database": "mongodb" if settings.use_mongodb else "sql",
        "portal": "/portal/" if os.path.isdir(portal_dir) else None,
    }
