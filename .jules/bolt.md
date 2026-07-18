# Bolt's Journal

## 2026-03-02 - Session Initialization
**Learning:** Initialized session for performance optimization of the Unie Cortex codebase.
**Action:** Identify a high-impact, low-risk performance win in the hot path of the core services and optimize it.

## 2026-03-02 - DateTime and Year Parsing Edge Cases
**Learning:** When implementing fast paths for datetime and year parsing, prefix-based checks (e.g., `s[:4].isdigit()`) can cause silent regressions for slash-separated formats (e.g., `YYYY/MM/DD` vs `MM/DD/YYYY`). Explicitly checking for standard separators (`-`, `T`, ` `, `/`) at specific indices avoids false positives and fallback bugs.
**Action:** Guard fast paths with robust separator checks and fallback correctly to slow/standard regex and `strptime` loops if fast paths are bypassed.
