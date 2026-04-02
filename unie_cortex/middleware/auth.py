"""API key auth middleware — optional; when API_KEY or API_KEYS is set, require valid key on /v1/*."""

from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader, APIKeyQuery

from unie_cortex.config import settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="api_key", auto_error=False)


def _valid_keys() -> set[str]:
    """Resolve allowed API keys from settings."""
    keys: set[str] = set()
    if settings.api_keys:
        keys.update(k.strip() for k in settings.api_keys.split(",") if k.strip())
    if settings.api_key and settings.api_key.strip():
        keys.add(settings.api_key.strip())
    return keys


def auth_enabled() -> bool:
    """True if any API key is configured."""
    return len(_valid_keys()) > 0


def _extract_bearer_token(auth_header: str | None) -> str | None:
    if not auth_header or not auth_header.strip().lower().startswith("bearer "):
        return None
    return auth_header[7:].strip()


async def verify_api_key(request: Request) -> str | None:
    """
    Extract and validate API key from X-API-Key, query param, or Authorization: Bearer.
    Returns the validated key if auth is disabled or key is valid; None if key missing/invalid.
    """
    if not auth_enabled():
        return None

    keys = _valid_keys()
    candidates: list[str] = []

    header_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if header_key:
        candidates.append(header_key.strip())

    query_key = request.query_params.get("api_key")
    if query_key:
        candidates.append(query_key.strip())

    bearer = _extract_bearer_token(request.headers.get("Authorization"))
    if bearer:
        candidates.append(bearer)

    for c in candidates:
        if c and c in keys:
            return c

    return None


async def require_api_key(request: Request) -> None:
    """
    Dependency/middleware helper: raise 401 if auth is enabled and no valid key provided.
    """
    if not auth_enabled():
        return
    key = await verify_api_key(request)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide X-API-Key header, ?api_key= query, or Authorization: Bearer <key>.",
        )
