## 2026-03-30 - Fast-path date string year extraction in amazon_fee_model_2026

**Learning:** `datetime.strptime` exception loops and `re.match` introduce heavy latency when parsing ISO or slash-formatted order dates across large datasets. Fast-path checking string length (`len(s) >= 4`) and digit slices (`s[:4].isdigit()`, `s[6:10].isdigit()`) returns integer years directly without regex overhead or exception handling. Fast rejection checks (`not any(c.isdigit() for c in s)`) bypass `strptime` entirely for non-digit inputs.

**Action:** Prefer direct string length and digit slice checks over `re.match` or multi-format `datetime.strptime` try/except loops when only date components (e.g. year) are required.
