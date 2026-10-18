## 2025-05-18 - Fast-path ISO 8601 parsing with datetime.fromisoformat
**Learning:** Python's `datetime.strptime` is implemented in Python and involves expensive regex/format matching and locale lookup overhead on every format attempt. In contrast, `datetime.fromisoformat` is implemented in C and parses ISO 8601 strings (including 'Z' converted to '+00:00') ~20x faster.
**Action:** Always attempt `datetime.fromisoformat` fast-path for datetime parsing on ISO 8601 string inputs before falling back to `strptime` format loops.
