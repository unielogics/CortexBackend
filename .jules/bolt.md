## 2025-05-22 - Order Financial Velocity Optimization
**Learning:** Redundant date parsing across batch operations was a major bottleneck. Pre-parsing and grouping lines in a single pass, combined with a fast-path for ISO 8601 strings, can provide an order of magnitude performance gain. Additionally, backward iteration with early exit for sliding windows on sorted chronological data significantly reduces loop overhead.
**Action:** Always look for "parsing loops" in batch processing functions and refactor to parse once, reuse many.
