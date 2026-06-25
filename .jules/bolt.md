## 2025-05-15 - [Date Parsing Type Consistency]
**Learning:** Mixing timezone-aware (e.g., from `fromisoformat` with '+00:00') and timezone-naive (e.g., from `strptime`) datetimes in the same list causes a `TypeError` during sorting.
**Action:** Always normalize datetimes to naive UTC (using `.astimezone(timezone.utc).replace(tzinfo=None)`) when using mixed parsing methods to ensure compatibility and consistent comparison/sorting.
