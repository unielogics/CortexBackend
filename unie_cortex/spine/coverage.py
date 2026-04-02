"""Per-module required canonical fields (values come from column mapping)."""

LABEL_MODULE_FIELDS = frozenset(
    {
        "label_amount_usd",
        "weight_lb",
        "dest_postal",
    }
)
LABEL_MODULE_OPTIONAL = frozenset(
    {"tracking_number", "carrier", "service_code", "origin_postal", "ship_date"}
)

THROUGHPUT_MODULE_FIELDS = frozenset({"completed_at", "zone"})
THROUGHPUT_OPTIONAL = frozenset({"operator_id", "task_type", "duration_sec"})

DISCREPANCY_LABEL_FIELDS = frozenset({"tracking_number", "label_amount_usd"})

# Optional: SKU-level velocity / item intelligence (does not block core spine)
ITEM_INTELLIGENCE_LABEL_OPTIONAL = frozenset({"sku", "qty", "line_amount_usd"})
ITEM_INTELLIGENCE_TASK_OPTIONAL = frozenset({"sku"})


def mapped_canonical_keys(mappings: dict[str, str]) -> set[str]:
    """Destination canonical field names present in mapping."""
    return set(mappings.values())


def coverage_label(mappings: dict[str, str]) -> tuple[str, list[str]]:
    keys = mapped_canonical_keys(mappings)
    missing = [f for f in LABEL_MODULE_FIELDS if f not in keys]
    if not missing:
        return "complete", []
    if keys & LABEL_MODULE_FIELDS:
        return "partial", missing
    return "skipped", list(LABEL_MODULE_FIELDS)


def coverage_throughput(mappings: dict[str, str]) -> tuple[str, list[str]]:
    keys = mapped_canonical_keys(mappings)
    missing = [f for f in THROUGHPUT_MODULE_FIELDS if f not in keys]
    if not missing:
        return "complete", []
    if keys & THROUGHPUT_MODULE_FIELDS:
        return "partial", missing
    return "skipped", list(THROUGHPUT_MODULE_FIELDS)


def coverage_discrepancy(mappings: dict[str, str]) -> tuple[str, list[str]]:
    keys = mapped_canonical_keys(mappings)
    if "tracking_number" in keys and "label_amount_usd" in keys:
        return "complete", []
    missing = [f for f in DISCREPANCY_LABEL_FIELDS if f not in keys]
    return "skipped", missing


def coverage_item_intelligence(mappings_labels: dict[str, str], mappings_tasks: dict[str, str]):
    """Optional module: needs sku on labels or tasks for velocity rollup."""
    lk = mapped_canonical_keys(mappings_labels)
    tk = mapped_canonical_keys(mappings_tasks)
    if "sku" in lk:
        return "complete", []
    if "sku" in tk:
        return "partial", ["sku on label lines recommended for shipment-SKU join"]
    return "skipped", ["sku"]
