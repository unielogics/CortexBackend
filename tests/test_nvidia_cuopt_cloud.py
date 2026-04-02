"""Unit tests for NVIDIA cuOpt cloud client (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from unie_cortex.integrations.nvidia_cuopt_cloud import (
    CuOptCloudError,
    build_optimized_routing_payload,
    cuopt_cloud_run,
)


class _CM:
    def __init__(self, inner: MagicMock) -> None:
        self._inner = inner

    def __enter__(self) -> MagicMock:
        return self._inner

    def __exit__(self, *a: object) -> None:
        return None


def test_build_optimized_routing_payload_wraps_data():
    p = build_optimized_routing_payload({"fleet_data": {}}, client_version="1.0")
    assert p["action"] == "cuOpt_OptimizedRouting"
    assert p["client_version"] == "1.0"
    assert p["data"] == {"fleet_data": {}}


def test_cuopt_cloud_run_missing_key():
    with patch(
        "unie_cortex.integrations.nvidia_cuopt_cloud.resolve_cuopt_cloud_bearer_token",
        return_value=None,
    ):
        with pytest.raises(CuOptCloudError, match="Missing API key"):
            cuopt_cloud_run({"action": "cuOpt_OptimizedRouting", "data": {}}, api_key=None)


def test_cuopt_cloud_run_200_immediate():
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"status": "ok", "routes": []}
    inner = MagicMock()
    inner.post.return_value = ok
    with patch("unie_cortex.integrations.nvidia_cuopt_cloud.httpx.Client", return_value=_CM(inner)):
        out = cuopt_cloud_run(
            {"action": "cuOpt_OptimizedRouting", "data": {"x": 1}},
            api_key="test-key",
        )
    assert out == {"status": "ok", "routes": []}
    inner.post.assert_called_once()
    call_kw = inner.post.call_args
    assert "Authorization" in call_kw[1]["headers"]
    assert call_kw[1]["headers"]["Authorization"] == "Bearer test-key"


def test_cuopt_cloud_run_202_then_poll_200():
    r202 = MagicMock()
    r202.status_code = 202
    r202.headers = httpx.Headers({"NVCF-REQID": "job-xyz"})

    r200 = MagicMock()
    r200.status_code = 200
    r200.json.return_value = {"solution": {"vehicles": [1]}}

    inner = MagicMock()
    inner.post.return_value = r202
    inner.get.return_value = r200

    with patch("unie_cortex.integrations.nvidia_cuopt_cloud.httpx.Client", return_value=_CM(inner)):
        with patch("unie_cortex.integrations.nvidia_cuopt_cloud.time.sleep"):
            out = cuopt_cloud_run(
                {"action": "cuOpt_OptimizedRouting", "data": {}},
                api_key="k",
                poll_interval_seconds=0.01,
            )
    assert out == {"solution": {"vehicles": [1]}}
    inner.get.assert_called_once()
    assert str(inner.get.call_args[0][0]).endswith("job-xyz")


def test_cuopt_cloud_run_202_missing_reqid():
    r202 = MagicMock()
    r202.status_code = 202
    r202.headers = httpx.Headers({})
    inner = MagicMock()
    inner.post.return_value = r202
    with patch("unie_cortex.integrations.nvidia_cuopt_cloud.httpx.Client", return_value=_CM(inner)):
        with pytest.raises(CuOptCloudError, match="NVCF-REQID"):
            cuopt_cloud_run(
                {"action": "cuOpt_OptimizedRouting", "data": {}},
                api_key="k",
            )
