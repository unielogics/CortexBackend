
import timeit
import re
from datetime import datetime, timezone

# Mocking enough to run the functions
def old_parse_order_datetime(raw: str | None) -> datetime | None:
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

def new_parse_order_datetime(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()

    # Fast path for ISO 8601
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            # fromisoformat handles many ISO 8601 variants.
            # If it ends in Z, we replace with +00:00 for compatibility
            iso_s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

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

def old_parse_order_year_from_iso(order_date_iso: str | None) -> int | None:
    if not order_date_iso or not str(order_date_iso).strip():
        return None
    s = str(order_date_iso).strip()
    m = re.match(r"^(\d{4})", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt).year
        except ValueError:
            continue
    return None

def new_parse_order_year_from_iso(order_date_iso: str | None) -> int | None:
    if not order_date_iso or not str(order_date_iso).strip():
        return None
    s = str(order_date_iso).strip()
    # Fast path for ISO-like strings (YYYY-MM-DD...)
    if len(s) >= 4 and s[:4].isdigit():
        if len(s) == 4 or s[4] == "-":
            return int(s[:4])

    m = re.match(r"^(\d{4})", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt).year
        except ValueError:
            continue
    return None

test_dates = [
    "2024-01-01T12:00:00Z",
    "2024-01-01 12:00:00",
    "2024-01-01",
    "01/01/2024",
    "2024-02-15T15:30:45.123Z",
]

def run_bench():
    print(f"{'Test Case':<30} | {'Old (ms)':<10} | {'New (ms)':<10} | {'Speedup':<10}")
    print("-" * 70)
    for td in test_dates:
        t_old = timeit.timeit(lambda: old_parse_order_datetime(td), number=10000) * 100
        t_new = timeit.timeit(lambda: new_parse_order_datetime(td), number=10000) * 100
        speedup = t_old / t_new if t_new > 0 else 0
        print(f"{td:<30} | {t_old:10.4f} | {t_new:10.4f} | {speedup:10.2f}x")

    print("\nYear Parsing Benchmark:")
    for td in test_dates:
        t_old = timeit.timeit(lambda: old_parse_order_year_from_iso(td), number=10000) * 100
        t_new = timeit.timeit(lambda: new_parse_order_year_from_iso(td), number=10000) * 100
        speedup = t_old / t_new if t_new > 0 else 0
        print(f"{td:<30} | {t_old:10.4f} | {t_new:10.4f} | {speedup:10.2f}x")

if __name__ == "__main__":
    run_bench()
