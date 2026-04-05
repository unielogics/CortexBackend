"""Self-hosted NVIDIA cuOpt REST (Docker): POST /cuopt/request + GET /cuopt/solution/{reqId}."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Mapping

import httpx

from unie_cortex.integrations.nvidia_cuopt_cloud import build_optimized_routing_payload


class CuOptSelfHostedError(RuntimeError):
    """Non-success body from self-hosted cuOpt or poll timeout."""


def _poll_interval_sec() -> float:
    return 0.5


def _cuopt_http_headers(client_version: str) -> dict[str, str]:
    """cuOpt server validates version from the ``client-version`` request header (see cuopt_server webserver)."""
    return {
        "Content-Type": "application/json",
        "client-version": client_version,
    }


async def cuopt_self_hosted_run(
    data: Mapping[str, Any],
    *,
    base_url: str,
    poll_timeout_seconds: float = 120.0,
    # cuOpt server rejects non-semver strings (see cuopt_server check_client_version); "custom" is allowed.
    client_version: str = "custom",
) -> dict[str, Any]:
    """POST optimized-routing job; poll until solution or error."""
    payload = build_optimized_routing_payload(dict(data), client_version=client_version)
    root = base_url.rstrip("/")
    post_url = f"{root}/cuopt/request"
    read_budget = max(120.0, float(poll_timeout_seconds) + 60.0)
    timeout = httpx.Timeout(connect=30.0, read=read_budget, write=120.0, pool=120.0)
    deadline = time.monotonic() + float(poll_timeout_seconds)
    hdrs = _cuopt_http_headers(client_version)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(post_url, json=payload, headers=hdrs)
        if r.status_code != 200:
            raise CuOptSelfHostedError(f"POST {post_url} HTTP {r.status_code}: {(r.text or '')[:2000]}")
        try:
            meta = r.json()
        except json.JSONDecodeError as e:
            raise CuOptSelfHostedError(f"Invalid JSON from cuOpt request: {e}") from e
        req_id = meta.get("reqId") or meta.get("requestId")
        if not req_id:
            raise CuOptSelfHostedError(f"Missing reqId in response: {meta!r:.800}")
        sol_url = f"{root}/cuopt/solution/{req_id}"
        while True:
            pr = await client.get(sol_url, headers=hdrs)
            if pr.status_code != 200:
                raise CuOptSelfHostedError(
                    f"GET {sol_url} HTTP {pr.status_code}: {(pr.text or '')[:2000]}"
                )
            try:
                body = pr.json()
            except json.JSONDecodeError as e:
                raise CuOptSelfHostedError(f"Invalid JSON from cuOpt solution: {e}") from e
            if body.get("error_result"):
                raise CuOptSelfHostedError(str(body.get("error") or body)[:4000])
            if body.get("response") is not None or body.get("solver_response") is not None:
                return body
            keys = set(body.keys())
            if keys <= {"reqId", "status"} and time.monotonic() < deadline:
                await asyncio.sleep(_poll_interval_sec())
                continue
            if time.monotonic() >= deadline:
                raise CuOptSelfHostedError(
                    f"cuOpt self-hosted poll exceeded {poll_timeout_seconds}s (last keys: {sorted(keys)})"
                )
            return body


def cuopt_self_hosted_run_sync(
    data: Mapping[str, Any],
    *,
    base_url: str,
    poll_timeout_seconds: float = 120.0,
    client_version: str = "custom",
) -> dict[str, Any]:
    """Sync variant for TMS path (sync route engine)."""
    payload = build_optimized_routing_payload(dict(data), client_version=client_version)
    root = base_url.rstrip("/")
    post_url = f"{root}/cuopt/request"
    read_budget = max(120.0, float(poll_timeout_seconds) + 60.0)
    timeout = httpx.Timeout(connect=30.0, read=read_budget, write=120.0, pool=120.0)
    deadline = time.monotonic() + float(poll_timeout_seconds)
    hdrs = _cuopt_http_headers(client_version)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(post_url, json=payload, headers=hdrs)
        if r.status_code != 200:
            raise CuOptSelfHostedError(f"POST {post_url} HTTP {r.status_code}: {(r.text or '')[:2000]}")
        meta = r.json()
        req_id = meta.get("reqId") or meta.get("requestId")
        if not req_id:
            raise CuOptSelfHostedError(f"Missing reqId in response: {meta!r:.800}")
        sol_url = f"{root}/cuopt/solution/{req_id}"
        while True:
            pr = client.get(sol_url, headers=hdrs)
            if pr.status_code != 200:
                raise CuOptSelfHostedError(
                    f"GET {sol_url} HTTP {pr.status_code}: {(pr.text or '')[:2000]}"
                )
            body = pr.json()
            if body.get("error_result"):
                raise CuOptSelfHostedError(str(body.get("error") or body)[:4000])
            if body.get("response") is not None or body.get("solver_response") is not None:
                return body
            keys = set(body.keys())
            if keys <= {"reqId", "status"} and time.monotonic() < deadline:
                time.sleep(_poll_interval_sec())
                continue
            if time.monotonic() >= deadline:
                raise CuOptSelfHostedError(
                    f"cuOpt self-hosted poll exceeded {poll_timeout_seconds}s (last keys: {sorted(keys)})"
                )
            return body


async def cuopt_self_hosted_health(base_url: str, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    root = base_url.rstrip("/")
    url = f"{root}/cuopt/health"
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return {"ok": False, "http_status": r.status_code, "detail": (r.text or "")[:500]}
        try:
            return {"ok": True, "body": r.json()}
        except json.JSONDecodeError:
            return {"ok": True, "body_raw": (r.text or "")[:500]}
