## 2026-03-06 - Fast Paths for 5-Digit Postal Normalization in Rate Bucket

**Learning:** Inline module imports inside hot function calls combined with uncompiled `re.sub` regex calls introduce substantial overhead when calculating rate cache key fingerprints across thousands of parcel operations. Fast-pathing standard string patterns (`len` & `.isdigit()` checks for 5-digit, ZIP+4, 9-digit, and short 3-4 digit ZIPs) bypasses regex completely for common inputs.
**Action:** When normalizing postal codes in hot rate calculation loops, use fast string length and digit validation before falling back to pre-compiled module-level regex.
