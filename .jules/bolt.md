## 2026-03-31 - Fast-Path Postal Code Normalization in Order Financial Planning

**Learning:** `_norm_postal_5` in `order_financial_planning.py` was executing `re.sub(r"\D", "", ...)` on every string, including standard 5-digit ZIPs and ZIP+4 strings (`#####-####`). Fast-path string length and `isdigit()` checks bypass regular expression engine overhead completely for standard formats.
**Action:** Always inspect helper functions that clean/normalize strings (like ZIPs, dates, or SKUs) on hot paths, pre-compile regex patterns at module level, and implement fast-path string checks.
