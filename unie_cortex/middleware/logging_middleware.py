"""Request logging with request IDs and token redaction."""

import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from unie_cortex.request_context import correlation_id_ctx

# Redact API keys, bearer tokens, and common secret patterns
REDACT_PATTERNS = [
    (re.compile(r'(api[_-]?key|apikey|authorization|bearer)\s*[:=]\s*["\']?([^\s"\']+)', re.I), r'\1=***REDACTED***'),
    (re.compile(r'["\']([a-fA-F0-9]{32,})["\']'), lambda m: f'"{m.group(1)[:8]}...{m.group(1)[-4:]}"' if len(m.group(1)) > 12 else '"***"'),
]

logger = logging.getLogger("unie_cortex.request")


def _redact(msg: str) -> str:
    for pat, repl in REDACT_PATTERNS:
        msg = pat.sub(repl, msg)
    return msg


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request/response with request_id; redact secrets from logs."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:12]
        request.scope["request_id"] = request_id
        token = correlation_id_ctx.set(request_id)
        method = request.method
        path = request.scope.get("path", "")
        logger.info(_redact(f"[{request_id}] {method} {path}"))
        try:
            response = await call_next(request)
            logger.info(_redact(f"[{request_id}] {method} {path} -> {response.status_code}"))
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as e:
            logger.exception(_redact(f"[{request_id}] {method} {path} -> error: {e}"))
            raise
        finally:
            correlation_id_ctx.reset(token)
