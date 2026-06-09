
import time
from datetime import datetime
from unie_cortex.services.order_financial_velocity import _parse_order_datetime, build_batch_velocity_enrichment
from unie_cortex.network.amazon_fee_model_2026 import parse_order_year_from_iso

def benchmark_parse_order_datetime():
    dates = [
        "2025-03-01T12:34:56.789Z",
        "2025-03-01T12:34:56Z",
        "2025-03-01T12:34:56",
        "2025-03-01",
        "03/01/2025",
        "01/03/2025",
    ] * 1000
    start = time.perf_counter()
    for d in dates:
        _parse_order_datetime(d)
    end = time.perf_counter()
    print(f"_parse_order_datetime took: {end - start:.4f}s for {len(dates)} iterations")

def benchmark_parse_order_year_from_iso():
    dates = [
        "2025-03-01T12:34:56.789Z",
        "2025-03-01",
        "03/01/2025",
    ] * 1000
    start = time.perf_counter()
    for d in dates:
        parse_order_year_from_iso(d)
    end = time.perf_counter()
    print(f"parse_order_year_from_iso took: {end - start:.4f}s for {len(dates)} iterations")

def benchmark_build_batch_velocity_enrichment():
    rows = [
        {"order_date_iso": "2025-03-01T12:34:56.789Z", "sku": f"SKU-{i%10}", "quantity": 1}
        for i in range(1000)
    ]
    start = time.perf_counter()
    build_batch_velocity_enrichment(rows)
    end = time.perf_counter()
    print(f"build_batch_velocity_enrichment took: {end - start:.4f}s for {len(rows)} rows")

if __name__ == "__main__":
    benchmark_parse_order_datetime()
    benchmark_parse_order_year_from_iso()
    benchmark_build_batch_velocity_enrichment()
