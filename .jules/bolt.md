## 2025-05-15 - [API Contract Preservation during Refactoring]
**Learning:** When refactoring for performance (e.g., moving from multiple passes to a single pass), it's easy to accidentally drop data that doesn't meet certain criteria early on. In this case, skipping unparseable rows in a single pass would have omitted empty groups from the output, which is a breaking change for the API contract.
**Action:** Always track input keys/counts explicitly if the output structure depends on the full set of input groups, even if some groups contain no valid data for the primary computation.
