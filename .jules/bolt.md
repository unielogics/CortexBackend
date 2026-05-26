## 2025-05-14 - Optimized Date Parsing with fromisoformat
**Learning:** Using a loop of `datetime.strptime` calls is a significant bottleneck for high-volume data processing. Additionally, manual string truncation (e.g., `s[:26]`) to fit strptime formats often causes sub-second precision loss and parsing failures for valid ISO 8601 strings (like those ending in 'Z').
**Action:** Always prefer `datetime.fromisoformat` with `.replace("Z", "+00:00")` as a fast-path for date parsing. It is ~15-20x faster and more robust than strptime for ISO-compliant strings.
