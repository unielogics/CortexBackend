## 2026-10-06 - Fast-path ZIP3 extraction in demand rollup

**Learning:** `re.sub(r"\D", "", ...)` is frequently used across postal processing helper functions. For standard 5-digit (`08817`), ZIP+4 (`08817-1234`), 9-digit (`088171234`), and 3-digit (`070`) inputs, checking string length and `.isdigit()` bypasses regex engine execution and temporary string allocations entirely.
**Action:** When working on postal code processing functions, apply length and `.isdigit()` fast paths before falling back to regex filtering.
