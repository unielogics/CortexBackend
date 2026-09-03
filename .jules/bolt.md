
## 2026-03-31 - Optimize Referral Fee Classification & CSV Override Normalization
**Learning:** Compiling regexes dynamically inside helper functions (like `re.search(r"\bwatches\b", ...)` inside `classification_texts_to_bucket`) introduces repeated regex compilation overhead. Additionally, linear iteration over lookup tuples in alias lists can be accelerated by checking an O(1) dictionary map (`CSV_OVER_EXACT_MAP`) for exact matches before doing substring searches.
**Action:** Always hoist static regexes to module scope and build fast O(1) dictionary maps alongside alias lists for string normalization routines on hot paths.
