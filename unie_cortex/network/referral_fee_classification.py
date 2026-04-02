"""
Map free-text classification strings (SP-API, Keepa category chain, CSV override) to
referral fee buckets consumed by amazon_referral_fees_2026.
"""

from __future__ import annotations

import re
from typing import Any

# Valid bucket ids for CSV override (normalize to these)
KNOWN_BUCKETS = frozenset(
    {
        "default",
        "amazon_device_accessories",
        "jewelry",
        "clothing_accessories",
        "watches",
        "automotive_tires",
        "automotive_powersports",
        "electronics_consumer",
        "personal_computers",
        "grocery_gourmet",
        "beauty_health",
        "electronics_accessories",
        "furniture",
        "media",
    }
)

# Aliases: substring or exact key -> bucket
CSV_OVERRIDE_ALIASES: list[tuple[str, str]] = [
    ("amazon_device_accessories", "amazon_device_accessories"),
    ("device_accessories", "amazon_device_accessories"),
    ("kindle", "amazon_device_accessories"),
    ("jewelry", "jewelry"),
    ("clothing", "clothing_accessories"),
    ("apparel", "clothing_accessories"),
    ("watch", "watches"),
    ("watches", "watches"),
    ("tire", "automotive_tires"),
    ("tires", "automotive_tires"),
    ("automotive", "automotive_powersports"),
    ("powersports", "automotive_powersports"),
    ("consumer_electronics", "electronics_consumer"),
    ("electronics_consumer", "electronics_consumer"),
    ("cell_phone", "electronics_consumer"),
    ("camera", "electronics_consumer"),
    ("personal_computer", "personal_computers"),
    ("pc", "personal_computers"),
    ("computers", "personal_computers"),
    ("grocery", "grocery_gourmet"),
    ("gourmet", "grocery_gourmet"),
    ("beauty", "beauty_health"),
    ("health", "beauty_health"),
    ("electronics_accessories", "electronics_accessories"),
    ("furniture", "furniture"),
    ("book", "media"),
    ("dvd", "media"),
    ("music", "media"),
    ("software", "media"),
    ("video_game", "media"),
    ("video games", "media"),
    ("default", "default"),
    ("most_categories", "default"),
    ("home", "default"),
    ("kitchen", "default"),
]


def normalize_csv_override(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if s in KNOWN_BUCKETS:
        return s
    for needle, bucket in CSV_OVERRIDE_ALIASES:
        if needle in s or s == needle:
            return bucket
    return None


def classification_texts_to_bucket(texts: list[str] | None) -> str:
    """
    Heuristic mapping from SP-API / Keepa labels. Order: most specific first.
    """
    if not texts:
        return "default"
    blob = " ".join(t.lower() for t in texts if t).strip()
    if not blob:
        return "default"

    def has(*words: str) -> bool:
        return all(w in blob for w in words)

    # Media (before generic book)
    if any(
        x in blob
        for x in (
            "video games",
            "video game",
            "computer & video games",
            "dvd",
            "blu-ray",
            "books",
            "book ",
            "audible",
            "digital music",
            "software",
        )
    ):
        if "kindle" in blob and "accessories" in blob:
            return "amazon_device_accessories"
        if any(x in blob for x in ("books", "book ", "dvd", "video game", "software", "music")):
            return "media"

    if "amazon device" in blob or "device accessories" in blob or "kindle accessories" in blob:
        return "amazon_device_accessories"

    if "tire" in blob or "tyre" in blob:
        return "automotive_tires"
    if "automotive" in blob or "powersports" in blob or "motorcycle" in blob or "auto part" in blob:
        return "automotive_powersports"

    if "wristwatch" in blob or "wrist watch" in blob or re.search(r"\bwatches\b", blob):
        return "watches"

    if "jewelry" in blob or "jewellery" in blob:
        return "jewelry"

    if "furniture" in blob:
        return "furniture"

    if "personal computer" in blob or re.search(r"\bpc\b", blob) or "laptop" in blob or "desktop computer" in blob:
        if "accessories" in blob and "computer" not in blob.replace("accessories", ""):
            pass
        else:
            return "personal_computers"

    if "electronics accessories" in blob or "cell phone accessories" in blob or "camera accessories" in blob:
        return "electronics_accessories"

    if any(
        x in blob
        for x in (
            "cell phones",
            "cell phone",
            "camera & photo",
            "camera",
            "television",
            "video",
            "consumer electronics",
            "electronics",
            "headphone",
        )
    ):
        if "accessories" in blob and ("phone" in blob or "camera" in blob):
            return "electronics_accessories"
        return "electronics_consumer"

    if "grocery" in blob or "gourmet" in blob or "food" in blob:
        return "grocery_gourmet"

    if "beauty" in blob or "health" in blob or "personal care" in blob:
        return "beauty_health"

    if "clothing" in blob or "shoe" in blob or "apparel" in blob or "fashion" in blob:
        return "clothing_accessories"

    return "default"


def extract_classification_strings_from_keepa_product(product: dict[str, Any]) -> list[str]:
    """Collect searchable strings from a Keepa ``products[0]`` object."""
    out: list[str] = []
    if not isinstance(product, dict):
        return out
    for k in ("title", "trackingName", "productGroup", "binding", "brand", "manufacturer"):
        v = product.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v)
    rc = product.get("rootCategory")
    try:
        if rc is not None and int(rc) > 0:
            out.append(f"category_id:{int(rc)}")
    except (TypeError, ValueError):
        pass
    ct = product.get("categoryTree")
    if isinstance(ct, list):
        for node in ct:
            if isinstance(node, dict):
                for kk in ("name", "contextFreeName"):
                    s = node.get(kk)
                    if isinstance(s, str) and s.strip():
                        out.append(s)
    return out


def extract_classification_strings_from_spapi_item(payload: dict) -> list[str]:
    """Flatten Catalog API 2022-04-01 item JSON into searchable strings."""
    out: list[str] = []
    if not isinstance(payload, dict):
        return out
    if "_uc_referral" in payload:
        payload = {k: v for k, v in payload.items() if k != "_uc_referral"}

    summaries = payload.get("summaries")
    if isinstance(summaries, list):
        for s in summaries:
            if isinstance(s, dict):
                for k in ("itemName", "browseClassification", "websiteDisplayGroup"):
                    v = s.get(k)
                    if isinstance(v, str):
                        out.append(v)
                    elif isinstance(v, dict):
                        out.extend(str(x) for x in v.values() if isinstance(x, str))

    pts = payload.get("productTypes")
    if isinstance(pts, list):
        for pt in pts:
            if isinstance(pt, dict):
                t = pt.get("productType")
                if isinstance(t, str):
                    out.append(t)

    attrs = payload.get("attributes")
    if isinstance(attrs, dict):
        for key, val in attrs.items():
            out.append(key.replace("_", " "))
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        for kk in ("value", "language_tag", "marketplace_id"):
                            if kk in item and isinstance(item[kk], str):
                                out.append(item[kk])
                    elif isinstance(item, str):
                        out.append(item)
            elif isinstance(val, str):
                out.append(val)

    return [x for x in out if isinstance(x, str) and x.strip()]
