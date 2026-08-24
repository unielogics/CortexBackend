## 2025-05-18 - Single-Pass Date Parsing and `fromisoformat` Fast Path in Order Financial Velocity

**Learning:** `datetime.strptime` incurs severe locale lookup and regex compilation overhead (~35x slower than `datetime.fromisoformat` in Python 3.11+). Furthermore, batch functions like `build_batch_velocity_enrichment` that re-parse date lines for each subgroup AND again for the entire dataset duplicate date parsing operations.

**Action:** Always use `datetime.fromisoformat` fast paths before falling back to `strptime`. Design batch processing helpers to accept pre-parsed domain objects (e.g., `_pre_parsed_lines`) so that data parsing happens exactly once per batch item.
