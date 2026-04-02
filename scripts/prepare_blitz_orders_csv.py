#!/usr/bin/env python3
"""
Add line-level seller_sku identifiers and (optionally) randomize ASIN among a fixed ASIN list.

**Demo / fixture only:** default ASIN randomization destroys real category linkage. For production
order-financial pipelines that need accurate referral buckets, keep source ASINs (``--no-random-asin``)
or use a dedicated export — do not use randomized ASINs when SP-API/Keepa resolution matters.

Example:
  python scripts/prepare_blitz_orders_csv.py \\
    --source "c:/dev/PrepCenterNearMe_system/orders_audit_financials_blitzzecommerce_export.csv" \\
    --output "c:/dev/PrepCenterNearMe_system/orders_audit_financials_blitzzecommerce_prepared.csv"
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

DEFAULT_ASINS = [
    "B0CKBYBF5C",
    "B0CR1N73L8",
    "B0D67X3KCB",
    "B0D572MW98",
    "B0D3WKT4GP",
    "B0D67THFS5",
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--no-random-asin",
        action="store_true",
        help="Keep original ASIN column; only add seller_sku",
    )
    args = p.parse_args()

    text = args.source.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise SystemExit("No rows in source CSV")

    rng = random.Random(args.seed)
    base_fields = list(rows[0].keys())
    fieldnames = list(base_fields)
    if "seller_sku" not in fieldnames:
        if "asin" in fieldnames:
            i = fieldnames.index("asin") + 1
            fieldnames = fieldnames[:i] + ["seller_sku"] + fieldnames[i:]
        else:
            fieldnames = ["seller_sku"] + fieldnames

    out_rows: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        new = dict(row)
        oid = (new.get("orderId") or new.get("order_id") or "row").strip()
        new["seller_sku"] = f"BLZ-{oid.replace('-', '')}-{idx:05d}"[:128]
        if not args.no_random_asin:
            new["asin"] = rng.choice(DEFAULT_ASINS)
        out_rows.append(new)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    print(f"Wrote {len(out_rows)} rows to {args.output.resolve()}")


if __name__ == "__main__":
    main()
