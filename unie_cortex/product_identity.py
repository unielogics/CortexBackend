"""
Product naming: **Seller Optimization Engine** (SOE).

Use this module anywhere a human-visible or JSON-stable system name is required.
The Python package remains ``unie_cortex``; this is the customer-facing product identity.
"""

from __future__ import annotations

from typing import Any

# Primary name — use in UI, OpenAPI title, and analytics payloads
SELLER_OPTIMIZATION_ENGINE_NAME: str = "Seller Optimization Engine"

# Short label (log lines, compact headers)
SELLER_OPTIMIZATION_ENGINE_SHORT: str = "SOE"

# Stable machine id for integrations and feature flags
SELLER_OPTIMIZATION_ENGINE_SYSTEM_ID: str = "seller_optimization_engine"

# Repository / import name (technical)
IMPLEMENTATION_PACKAGE: str = "unie_cortex"


def seller_optimization_engine_identity() -> dict[str, Any]:
    """Embed in API responses, planning matrices, and analysis artifacts."""
    return {
        "display_name": SELLER_OPTIMIZATION_ENGINE_NAME,
        "short_name": SELLER_OPTIMIZATION_ENGINE_SHORT,
        "system_id": SELLER_OPTIMIZATION_ENGINE_SYSTEM_ID,
        "implementation_package": IMPLEMENTATION_PACKAGE,
    }
