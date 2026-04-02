"""Starlette middleware that enforces API key auth on /v1/* when configured."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from unie_cortex.middleware.auth import auth_enabled, verify_api_key


class APIAuthMiddleware(BaseHTTPMiddleware):
    """
    When auth is enabled, require valid API key on all /v1/* and /portal paths.
    Excludes /health, /, /docs, /openapi.json, /redoc.
    """

    SKIP_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
    SKIP_PREFIXES = ("/v1/integrations/capabilities",)

    async def dispatch(self, request: Request, call_next):
        path = request.scope.get("path", "")
        if path in self.SKIP_PATHS:
            return await call_next(request)
        for prefix in self.SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        if not path.startswith("/v1") and not path.startswith("/portal"):
            return await call_next(request)
        if not auth_enabled():
            return await call_next(request)
        key = await verify_api_key(request)
        if key is None:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "API key required. Provide X-API-Key header, ?api_key= query, or Authorization: Bearer <key>.",
                },
            )
        return await call_next(request)
