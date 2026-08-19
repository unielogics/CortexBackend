## 2026-03-30 - Fast-path string checks for postal code normalization and pre-allocated constants

**Learning:** Replacing `re.sub(r"\D", "", p)` in postal code normalization with fast-path length/`isdigit()` checks for standard 5-digit, ZIP+4 (`#####-####`), and 9-digit formats bypasses regex compilation and execution overhead for ~99%+ of postal code inputs. Additionally, pre-allocating model note string constants (`_NOTE_USPS`, `_NOTE_UPS`, `_NOTE_FEDEX`) and inlining simple string slicing for ZIP3 extraction (`int(o[:3])`) eliminates redundant string allocations and function invocation overhead in rating loops, yielding a ~2.04x speedup for `mock_zone_id` (from 4.11s down to 2.01s per 900k calls).

**Action:** Look for high-frequency string normalization helper functions that use regex (`re.sub` or `re.search`) on standard-formatted inputs, and introduce early fast-path checks for common patterns while retaining regex fallback for dirty/edge-case inputs.
