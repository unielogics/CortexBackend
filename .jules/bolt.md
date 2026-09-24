## 2026-03-30 - Fast-path string checks for ZIP5 normalization

**Learning:** `re.sub(r"\D", "", ...)` is used across many normalization routines in order financial planning. Fast-path string checks (`len`, `.isdigit()`) bypass regex execution for clean standard formats (5-digit, ZIP+4, 9-digit unhyphenated), providing a ~2.8x speedup on postal normalization.

**Action:** Look for `re.sub(r"\D", ...)` calls on postal code normalization functions across other modules and introduce string fast-paths.
