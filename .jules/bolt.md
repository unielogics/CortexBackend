# Bolt's Journal

## 2026-03-31 - O(1) Fast-Path and Pre-compiled Regex in Category Classification
**Learning:** In `referral_fee_classification.py`, string alias lookup via repeated O(N) list iteration (`CSV_OVERRIDE_ALIASES`) on hot paths like `normalize_csv_override` can be significantly sped up by constructing a module-level exact-match mapping dictionary (`CSV_OVER_EXACT_MAP`). Additionally, pre-compiling word boundary regex patterns (`\bwatches\b`, `\bpc\b`) avoids compiling regex objects inside repeated calls.
**Action:** Always pre-build exact lookup maps for known category aliases and pre-compile word-boundary regex patterns at the module level when performing classification in hot loops.
