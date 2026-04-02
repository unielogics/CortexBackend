"""Print sample demand_extract-style payloads (no live Keepa API). Run from repo root:

  .venv\\Scripts\\python scripts\\demo_keepa_demand_output.py
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unie_cortex.integrations.keepa_demand import extract_demand_from_keepa_payload


def _show(title: str, raw: dict, **kwargs) -> None:
    d = extract_demand_from_keepa_payload(deepcopy(raw), **kwargs)
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    # Trim huge keys for readability
    slim = {k: v for k, v in d.items() if k not in ("placement_hints",)}
    if "inventory_placement_summary" in slim and isinstance(slim["inventory_placement_summary"], dict):
        ips = dict(slim["inventory_placement_summary"])
        for heavy in list(ips.keys()):
            if heavy.startswith("warehouse_") or heavy in ("nodes_detail",):
                ips[heavy] = "<omitted>"
        slim["inventory_placement_summary"] = ips
    print(json.dumps(slim, indent=2, default=str))


def main() -> None:
    t_end = 5_000_000
    t0 = t_end - 30 * 24 * 60
    hist = [str(t0), "S_WIN", "4990000", "S_OT", "4999000", "S_WIN"]
    offers_bb = [{"sellerId": "S_WIN", "isAmazon": 0} for _ in range(10)]

    _show(
        "1) Small ASIN, no offers/history — tier slice (unknown seller)",
        {"products": [{"asin": "B0TEST1234", "monthlySold": 80}]},
    )

    _show(
        "2) 20k/mo, no history — capped tier slice",
        {"products": [{"asin": "B0HUGE", "monthlySold": 20000}]},
    )

    _show(
        "3) Buy box history + 1500/mo, unknown seller — follower avg × velocity (then cap 400 if over)",
        {
            "products": [
                {
                    "asin": "B0FOL",
                    "monthlySold": 1500,
                    "lastUpdate": t_end,
                    "buyBoxSellerIdHistory": hist,
                    "offers": [],
                }
            ]
        },
    )

    _show(
        "4) Same + marketplace_seller_id=S_WIN — dominant share × velocity",
        {
            "products": [
                {
                    "asin": "B0WIN",
                    "monthlySold": 20000,
                    "lastUpdate": t_end,
                    "buyBoxSellerIdHistory": hist,
                    "offers": offers_bb,
                    "buyBoxSellerId": "S_WIN",
                }
            ]
        },
        marketplace_seller_id="S_WIN",
    )

    _show(
        "5) Same as (4) + optional listing signals for cohort nudge",
        {
            "products": [
                {
                    "asin": "B0WIN",
                    "monthlySold": 20000,
                    "lastUpdate": t_end,
                    "buyBoxSellerIdHistory": hist,
                    "offers": offers_bb
                    + [
                        {
                            "sellerId": "S_OT",
                            "isAmazon": 0,
                            "isFBA": 1,
                            "recentStarRating": 49,
                            "recentReviewCount": 100,
                        }
                    ],
                    "buyBoxSellerId": "S_WIN",
                }
            ]
        },
        marketplace_seller_id=None,
        seller_listing_rating_12m_pct=96.0,
        seller_listing_review_count=80.0,
        seller_listing_is_fba=True,
    )


if __name__ == "__main__":
    main()
