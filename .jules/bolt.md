## 2026-03-31 - Fast-path ISO-8601 parsing in velocity calculations
**Learning:** Sequential `datetime.strptime` format loops throw and catch `ValueError` exceptions on every non-matching format string. For standard ISO-8601 strings (the vast majority in order financial exports), `datetime.fromisoformat(s.replace('Z', '+00:00'))` executes in C without exception overhead.
**Action:** Always prefer `datetime.fromisoformat` fast-paths before fallback `strptime` format loops when parsing ISO-like timestamp fields.
