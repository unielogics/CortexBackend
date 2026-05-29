import timeit
from datetime import datetime, timezone
import re
from unie_cortex.services.order_financial_velocity import _parse_order_datetime
from unie_cortex.network.amazon_fee_model_2026 import parse_order_year_from_iso

# Original implementation from unie_cortex/services/order_financial_velocity.py (re-created for comparison)
def _parse_order_datetime_orig(raw: str | None) -> datetime | None:
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

test_dates = [
    "2025-03-01T12:34:56.789Z",
    "2025-03-01T12:34:56Z",
    "2025-03-01T12:34:56",
    "2025-03-01",
    "03/01/2025",
]

def run_benchmark():
    n = 10000
    print("Benchmarking _parse_order_datetime:")
    for d in test_dates:
        t_orig = timeit.timeit(lambda: _parse_order_datetime_orig(d), number=n)
        t_opt = timeit.timeit(lambda: _parse_order_datetime(d), number=n)
        print(f"Date: {d}")
        print(f"  Orig: {t_orig:.4f}s")
        print(f"  Opt:  {t_opt:.4f}s")
        print(f"  Improvement: {(t_orig - t_opt) / t_orig * 100:.2f}%")

    print("\nBenchmarking parse_order_year_from_iso:")
    for d in test_dates:
        t_opt = timeit.timeit(lambda: parse_order_year_from_iso(d), number=n)
        print(f"Date: {d}")
        print(f"  Opt:  {t_opt:.4f}s")

if __name__ == "__main__":
    run_benchmark()
