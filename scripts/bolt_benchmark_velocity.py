import time
import random
from datetime import datetime, timedelta, timezone
from unie_cortex.services.order_financial_velocity import build_batch_velocity_enrichment

def generate_mock_data(n_rows=10000):
    skus = [f"SKU-{i}" for i in range(100)]
    rows = []
    base_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
    for _ in range(n_rows):
        dt = base_date + timedelta(days=random.randint(0, 365), seconds=random.randint(0, 86400))
        rows.append({
            "sku": random.choice(skus),
            "order_date_iso": dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "quantity": random.randint(1, 5),
            "order_id": f"ORDER-{random.randint(100000, 999999)}"
        })
    return rows

def main():
    print("Generating mock data...")
    rows = generate_mock_data(20000)

    print(f"Benchmarking build_batch_velocity_enrichment with {len(rows)} rows...")
    start = time.perf_counter()
    result = build_batch_velocity_enrichment(rows)
    end = time.perf_counter()

    print(f"Time taken: {end - start:.4f} seconds")
    print(f"Groups processed: {len(result['by_sku_or_asin'])}")

if __name__ == "__main__":
    main()
