"""
Tri-modal API contract: original client input, deterministic Unie baseline, optional NVIDIA layer.

See roadmap section 8 — baseline must remain reproducible; NVIDIA must not silently overwrite baseline numbers.
"""

from __future__ import annotations

from typing import Any

TRI_MODAL_VERSION = "tri_modal_v1"


def build_tri_modal_block(
    *,
    original_input: dict[str, Any],
    baseline_unie: dict[str, Any],
    nvidia_enhanced: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": TRI_MODAL_VERSION,
        "original_input": original_input,
        "baseline_unie": baseline_unie,
        "nvidia_enhanced": nvidia_enhanced,
    }
