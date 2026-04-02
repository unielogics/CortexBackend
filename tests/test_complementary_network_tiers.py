"""Tiered node counts for complementary network audit."""

from __future__ import annotations

from unie_cortex.services.complementary_network_tiers import complement_slot_count, tiered_total_warehouse_nodes


def test_tiered_total_warehouse_nodes_boundaries():
    assert tiered_total_warehouse_nodes(0) == 2
    assert tiered_total_warehouse_nodes(50_000) == 2
    assert tiered_total_warehouse_nodes(50_001) == 3
    assert tiered_total_warehouse_nodes(75_000) == 3
    assert tiered_total_warehouse_nodes(75_001) == 4
    assert tiered_total_warehouse_nodes(100_000) == 4
    assert tiered_total_warehouse_nodes(100_001) == 5
    assert tiered_total_warehouse_nodes(150_000) == 6
    assert tiered_total_warehouse_nodes(500_000) == 6


def test_complement_slot_count_is_total_minus_primary():
    assert complement_slot_count(50_000) == 1
    assert complement_slot_count(50_001) == 2
    assert complement_slot_count(150_000) == 5
