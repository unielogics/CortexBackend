
import time
from datetime import datetime, timezone
import re

# Current implementation
def _parse_order_datetime_old(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            dt = datetime.strptime(s[:26], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

# Optimized implementation
def _parse_order_datetime_new(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # Fast path for ISO 8601
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            # Replace Z with +00:00 for fromisoformat compatibility in some Python versions
            iso_s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    # Fallback for other formats
    for fmt in (
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None

test_dates = [
    "2025-03-01T12:00:00.123Z",
    "2025-03-01T12:00:00Z",
    "2025-03-01T12:00:00",
    "2025-03-01 12:00:00",
    "2025-03-01",
    "03/01/2025",
    "01/03/2025",
] * 10000

print(f"Benchmarking with {len(test_dates)} date strings...")

start = time.time()
for d in test_dates:
    _parse_order_datetime_old(d)
end = time.time()
print(f"Old implementation: {end - start:.4f}s")

start = time.time()
for d in test_dates:
    _parse_order_datetime_new(d)
end = time.time()
print(f"New implementation: {end - start:.4f}s")
