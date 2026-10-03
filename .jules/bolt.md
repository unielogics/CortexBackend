## 2026-03-30 - Fast-path ISO-8601 Date Parsing and Single-Pass Aggregation in Order Financial Facts

**Learning:** Calling `datetime.strptime` inside exception-heavy try-except loops across large datasets creates significant overhead due to CPython's string parsing and exception generation. Using `datetime.fromisoformat(s.replace("Z", "+00:00"))` as a fast path parses standard ISO date strings directly in C without exceptions. Furthermore, replacing 15+ individual generator expressions and list passes over dataset rows with a single O(N) consolidated pass dramatically reduces field lookup (`.get()`) overhead and dictionary allocations.

**Action:** Always prefer `datetime.fromisoformat` fast-paths for ISO-8601 date parsing before falling back to `strptime` formats. When aggregating row data into facts/totals, consolidate multiple list comprehensions into a single loop pass.
