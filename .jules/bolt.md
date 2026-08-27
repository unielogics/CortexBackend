# Bolt's Performance Journal

## 2026-08-27 - Fast-path string checks for postal code normalization

**Learning:** Postal code normalization functions (`normalize_postal_5`) called repeatedly during parcel rate shopping and cache key generation incur significant CPU overhead when using unconditional regex string replacements (`re.sub(r"\D", "", ...)`). Pre-compiling regexes at module level and introducing length and `.isdigit()` fast-paths for standard US formats (5-digit, ZIP+4, 9-digit unhyphenated, 3-4 digit ZIPs) bypasses regex parsing entirely for common inputs.

**Action:** When handling string normalization on hot execution paths (such as postal/ZIP or carrier code normalization), always check if standard length and character properties (`.isdigit()`, `.isalnum()`) can resolve common formats before falling back to regex operations.
