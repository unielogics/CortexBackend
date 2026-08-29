import time
import random
from datetime import datetime, timezone, timedelta
from unie_cortex.services.order_financial_velocity import _parse_order_datetime, _lines_for_group, build_batch_velocity_enrichment

def generate_mock_rows(count=10000):
    rows = []
    start_date = datetime(2023, 1, 1)
    for i in range(count):
        dt = start_date + timedelta(seconds=random.randint(0, 365*24*3600))
        # Mix of formats supported by _parse_order_datetime
        fmts = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y",
        ]
        fmt = random.choice(fmts)
        raw_dt = dt.strftime(fmt)
        if "%fZ" in fmt:
             raw_dt = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        rows.append({
            "sku": f"SKU-{random.randint(1, 100)}",
            "order_date_iso": raw_dt,
            "quantity": random.randint(1, 5),
            "order_id": f"ORD-{i}"
        })
    return rows

def benchmark_parsing():
    rows = generate_mock_rows(20000)
    raw_dates = [row["order_date_iso"] for row in rows]

    start = time.perf_counter()
    for rd in raw_dates:
        _parse_order_datetime(rd)
    end = time.perf_counter()
    print(f"Parsing 20,000 dates: {end - start:.4f}s")

def benchmark_batch_enrichment():
    rows = generate_mock_rows(10000)
    start = time.perf_counter()
    build_batch_velocity_enrichment(rows)
    end = time.perf_counter()
    print(f"Batch enrichment (10,000 rows): {end - start:.4f}s")

if __name__ == "__main__":
    benchmark_parsing()
    benchmark_batch_enrichment()
