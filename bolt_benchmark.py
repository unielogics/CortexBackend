import time
import re
from datetime import datetime, timezone, date

# --- Order Financial Velocity ---
def _parse_order_datetime_optimized(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            # Only replace if Z is actually there to save a string allocation/scan
            if s.endswith('Z'):
                dt = datetime.fromisoformat(s[:-1] + "+00:00")
            else:
                dt = datetime.fromisoformat(s)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

# --- Amazon Fee Model 2026 ---
def parse_order_year_from_iso_optimized(order_date_iso: str | None) -> int | None:
    if not order_date_iso:
        return None
    s = str(order_date_iso).strip()
    if not s:
        return None

    # Performance optimization: fast path for ISO 8601 year extraction.
    # String slicing + isdigit is significantly faster than regex or strptime.
    if len(s) >= 4:
        y_str = s[:4]
        if y_str.isdigit() and (len(s) == 4 or s[4] == "-"):
            return int(y_str)

    for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).year
        except ValueError:
            continue
    return None

# --- Original Implementations (for comparison) ---
def _parse_order_datetime_original(raw: str | None) -> datetime | None:
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

def parse_order_year_from_iso_original(order_date_iso: str | None) -> int | None:
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

def run_benchmark(name, original_func, optimized_func, data):
    start = time.time()
    for d in data:
        original_func(d)
    orig_time = time.time() - start

    start = time.time()
    for d in data:
        optimized_func(d)
    opt_time = time.time() - start

    speedup = orig_time / opt_time if opt_time > 0 else float('inf')
    print(f"--- {name} ---")
    print(f"Original:  {orig_time:.4f}s")
    print(f"Optimized: {opt_time:.4f}s")
    print(f"Speedup:   {speedup:.2f}x\n")

if __name__ == "__main__":
    iso_dates = [
        "2024-01-01T12:00:00.000Z",
        "2024-01-01T12:00:00Z",
        "2024-01-01T12:00:00",
        "2024-01-01 12:00:00",
        "2024-01-01",
    ] * 10000 # Increased iterations for better stability

    run_benchmark("Order Financial Velocity (datetime)", _parse_order_datetime_original, _parse_order_datetime_optimized, iso_dates)
    run_benchmark("Amazon Fee Model (year only)", parse_order_year_from_iso_original, parse_order_year_from_iso_optimized, iso_dates)
