"""
NVIDIA cuOpt **cloud** API (`optimize.api.nvidia.com`): invoke + ``202`` status polling.

This is separate from ``CUOPT_NIM_URL`` + ``/tms/vrp`` (custom NIM contract in
``cuopt_tms_routing``). Here the request body matches NVIDIA's
``cuOpt_OptimizedRouting`` action.

Auth: set ``CUOPT_API_KEY`` or ``NVIDIA_API_KEY`` in the environment (see
``resolve_cuopt_cloud_bearer_token``).
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

import httpx

from unie_cortex.config import settings

ACTION_OPTIMIZED_ROUTING = "cuOpt_OptimizedRouting"

DEFAULT_INVOKE_URL = "https://optimize.api.nvidia.com/v1/nvidia/cuopt"
DEFAULT_STATUS_URL_PREFIX = "https://optimize.api.nvidia.com/v1/status/"


class CuOptCloudError(RuntimeError):
    """Non-success HTTP status or missing poll headers."""


def resolve_cuopt_cloud_bearer_token() -> str | None:
    """Prefer dedicated cuOpt key, then general NVIDIA Integrate key."""
    return settings.cuopt_api_key or settings.nvidia_api_key


def build_optimized_routing_payload(
    data: Mapping[str, Any],
    *,
    client_version: str = "",
) -> dict[str, Any]:
    """Wrap ``data`` in the top-level envelope NVIDIA expects."""
    return {
        "action": ACTION_OPTIMIZED_ROUTING,
        "data": dict(data),
        "client_version": client_version,
    }


def cuopt_cloud_run(
    payload: Mapping[str, Any],
    *,
    api_key: str | None = None,
    invoke_url: str | None = None,
    status_url_prefix: str | None = None,
    poll_interval_seconds: float | None = None,
    poll_timeout_seconds: float | None = None,
    post_timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """
    POST ``payload`` to the invoke endpoint. On ``202``, poll
    ``GET {status_url_prefix}{NVCF-REQID}`` until a non-202 response.

    ``payload`` is the full JSON body (``action``, ``data``, ``client_version``).
    Use :func:`build_optimized_routing_payload` for the common case.

    Returns the final JSON object on success (``200`` with parseable body).
    """
    key = api_key or resolve_cuopt_cloud_bearer_token()
    if not key:
        raise CuOptCloudError(
            "Missing API key: set CUOPT_API_KEY or NVIDIA_API_KEY for Bearer auth."
        )

    invoke = invoke_url or settings.nvidia_cuopt_cloud_invoke_url
    prefix = status_url_prefix or settings.nvidia_cuopt_cloud_status_url_prefix
    if not prefix.endswith("/"):
        prefix = prefix + "/"

    interval = (
        poll_interval_seconds
        if poll_interval_seconds is not None
        else settings.nvidia_cuopt_cloud_poll_interval_seconds
    )
    deadline_poll = (
        poll_timeout_seconds
        if poll_timeout_seconds is not None
        else settings.nvidia_cuopt_cloud_poll_timeout_seconds
    )

    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Single long budget: cuOpt jobs can exceed a short read timeout on poll.
    read_budget = max(float(post_timeout_seconds), float(deadline_poll) + 60.0)
    timeout = httpx.Timeout(connect=30.0, read=read_budget, write=120.0, pool=120.0)
    started = time.monotonic()

    with httpx.Client(timeout=timeout) as client:
        response = client.post(invoke, headers=headers, content=json.dumps(payload))

        while response.status_code == 202:
            elapsed = time.monotonic() - started
            if elapsed > deadline_poll:
                raise CuOptCloudError(
                    f"cuOpt cloud poll exceeded {deadline_poll}s (still 202 Accepted)."
                )
            req_id = response.headers.get("NVCF-REQID") or response.headers.get("nvcf-reqid")
            if not req_id:
                raise CuOptCloudError(
                    "202 response missing NVCF-REQID header; cannot poll status."
                )
            time.sleep(max(0.05, interval))
            response = client.get(f"{prefix}{req_id}", headers=headers)

        if response.status_code != 200:
            body = response.text[:8000]
            raise CuOptCloudError(
                f"cuOpt cloud failed HTTP {response.status_code}: {body}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise CuOptCloudError(f"Success HTTP 200 but body is not JSON: {e}") from e
