## 2025-05-15 - Naive vs Aware Datetime Consistency
**Learning:** Mixing naive and aware datetimes in Python triggers `TypeError` during comparisons or sorting. Fast-path parsers like `datetime.fromisoformat` often return aware datetimes (with `+00:00`) while legacy `strptime` patterns might return naive ones depending on the format string.
**Action:** Always normalize parsed datetimes to a single standard (e.g., naive UTC via `.astimezone(timezone.utc).replace(tzinfo=None)`) before performing comparisons or storing in shared data structures.
