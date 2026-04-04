"""Request-scoped context (correlation id for AI observability chain)."""

from __future__ import annotations

from contextvars import ContextVar

correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()
