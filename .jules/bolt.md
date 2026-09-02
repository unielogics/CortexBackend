## 2026-03-31 - Fast-Path ZIP Normalization in Order Financial Planning

**Learning:** `_norm_postal_5` in `unie_cortex/services/order_financial_planning.py` was relying on `re.sub(r"\D", "", ...)` for every input postal code. Adding standard string fast-paths (`len(sz) == 5 and sz.isdigit()`, `len(sz) == 10 and sz[5] == '-'...`, `len(sz) == 9 and sz.isdigit()`) alongside a pre-compiled `_RE_NON_DIGIT` regex bypasses expensive regex engine overhead for standard US postal codes.

**Action:** Always check postal code parsing helpers across financial and routing modules for regex overhead and introduce fast paths for standard 5-digit, ZIP+4, and 9-digit formats.
