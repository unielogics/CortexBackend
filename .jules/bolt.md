## 2026-08-25 - Fast-Path ZIP Normalization in Rate Bucketing

**Learning:** `normalize_postal_5` in `rate_bucket.py` was executing `re.sub(r"\D", "", z)` for every single rate bucket lookup. Adding fast-path string checks (`len` and `.isdigit()`) for standard 5-digit, ZIP+4 (`#####-####`), and unhyphenated 9-digit formats bypasses regex compilation and execution entirely for standard postal inputs.
**Action:** When normalizing string identifiers or postal codes in hot rate/routing loops, use direct string length and `.isdigit()` checks prior to invoking regular expressions.
