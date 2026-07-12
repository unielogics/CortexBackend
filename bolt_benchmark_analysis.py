
import time
import uuid
import random
from unie_cortex.services.order_financial_analysis import analyze_order_financial_facts
from unie_cortex.services.order_financial_velocity import build_batch_velocity_enrichment
from unie_cortex.network.demand_rollup import rollup_order_financial_demand

def generate_mock_rows(count):
    rows = []
    states = ["CA", "NY", "TX", "FL", "WA", "IL", "GA", "OH"]
    asins = [f"ASIN{i:04d}" for i in range(100)]
    sources = ["source_a", "source_b", "source_c"]

    for i in range(count):
        asin = random.choice(asins)
        rows.append({
            "revenue_usd": random.uniform(10, 100),
            "marketplace_fees_usd": random.uniform(1, 15),
            "other_expenses_usd": random.uniform(0, 5),
            "total_fees_usd": random.uniform(2, 20),
            "profit_usd": random.uniform(-5, 30),
            "product_cogs_usd": random.uniform(5, 40),
            "prep_cost_usd": random.uniform(0, 2),
            "inbound_cost_usd": random.uniform(0, 2),
            "quantity": random.randint(1, 5),
            "referral_fees_modeled_usd": random.uniform(1, 10),
            "asin": asin,
            "sku": f"SKU-{asin}-{i%10}",
            "ship_to_state": random.choice(states),
            "ship_to_postal": f"{random.randint(100, 999)}01",
            "inflation_source": random.choice(sources),
            "referral_fee_source": random.choice(sources),
            "order_date_iso": "2023-01-01T12:00:00Z",
            "fba_fulfillment_fee_audit_line_total_usd": random.uniform(1, 5),
            "amazon_seller_fees_usd": random.uniform(0.5, 2),
            "amazon_fba_fulfillment_fees_usd": random.uniform(1, 4),
        })
    return rows

def benchmark():
    count = 10000
    rows = generate_mock_rows(count)

    # Warm up
    analyze_order_financial_facts(rows[:100])

    start = time.perf_counter()
    analyze_order_financial_facts(rows)
    end = time.perf_counter()
    print(f"analyze_order_financial_facts total: {(end - start) * 1000:.2f}ms")

    # Component breakdown
    start = time.perf_counter()
    vel_rows = [
        {
            "order_date_iso": r.get("order_date_iso"),
            "sku": r.get("sku"),
            "asin": r.get("asin"),
            "quantity": r.get("quantity"),
        }
        for r in rows
    ]
    build_batch_velocity_enrichment(vel_rows)
    end = time.perf_counter()
    print(f"build_batch_velocity_enrichment: {(end - start) * 1000:.2f}ms")

    start = time.perf_counter()
    rollup_order_financial_demand(rows, hot_pct=0.33, cold_pct=0.33, weight_mode="quantity")
    end = time.perf_counter()
    print(f"rollup_order_financial_demand (quantity): {(end - start) * 1000:.2f}ms")

if __name__ == "__main__":
    benchmark()
