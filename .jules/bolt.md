## 2025-10-27 - Missing optimizations in core services
**Learning:** Found that optimizations previously mentioned in project history (consolidated loops in `analyze_order_financial_facts` and ISO fast-path in `_parse_order_datetime`) were not present in the current codebase state, leading to a baseline performance regression.
**Action:** Re-implemented these core optimizations and verified a ~50% reduction in execution time for 10k row financial datasets. Always verify codebase state against expected performance patterns before assuming past optimizations are intact.
