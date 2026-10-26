## 2026-10-26 - Amazon 2026 Referral Fee Dispatch & Metadata Caching

**Learning:** In Amazon referral fee calculations (`unie_cortex/network/amazon_referral_fees_2026.py`), repeated `if/elif/else` branching on bucket names and dict instantiations for `referral_fee_metadata` add latency in high-volume financial calculations. Replacing the bucket `if/elif` chain with an O(1) dictionary dispatch table (`_BUCKET_RULES`) and caching `referral_fee_metadata` (with a shallow `.copy()` to protect global cache immutability) yielded a ~1.11x speedup (~10% execution time reduction).

**Action:** For category/bucket fee calculations or metadata helpers called in hot loops, use dictionary dispatch tables and key-based metadata caching with `.copy()` to eliminate branching and allocation overhead.
