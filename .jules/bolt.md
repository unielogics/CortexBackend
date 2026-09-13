# Bolt's Performance Journal

## 2026-03-30 - Referral Fee Classification Regex & Override Lookup Optimization
**Learning:** Recompiling regexes inside hot text classification functions (`re.search(r"\bwatches\b", blob)`) and iterating over list tuples for string normalization incur high cumulative latency overhead. Pre-compiling regexes at module level and constructing an O(1) exact match dictionary map before resorting to substring loops significantly reduces execution time.
**Action:** Always hoist inline regex patterns to pre-compiled module-level constants (`_RE_*`) and use pre-built dictionary mappings (`_EXACT_MAP`) for exact string normalization paths before falling back to iterative loop searches.
