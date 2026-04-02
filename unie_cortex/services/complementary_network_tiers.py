"""Tiered total warehouse node count (including primary) for complementary network audit."""

from __future__ import annotations


def tiered_total_warehouse_nodes(order_count: int) -> int:
    """
    Total nodes in the mock plan = **audited primary + complements**.

    Rules (per product spec):
    - Up to 50,000 orders: **2** nodes (primary + 1 complement).
    - Above 50,000: start at **3** nodes; add **1** per additional **25,000** orders.
    - **Maximum 6** nodes.

    ``order_count`` should be distinct shipped orders or order lines — caller chooses.
    """
    n = max(0, int(order_count))
    if n <= 50_000:
        return 2
    extra_tiers = (n - 50_001) // 25_000
    total = 3 + extra_tiers
    return min(6, total)


def complement_slot_count(order_count: int) -> int:
    """Number of **additional** mock DCs (not counting primary)."""
    return max(0, tiered_total_warehouse_nodes(order_count) - 1)
