## 2026-03-31 - Hoisting loop-invariant ZIP3 parsing & string fast-paths in inbound routing
**Learning:** Re-evaluating `_zip3` regexes inside candidate matching loops (like `closest_node_by_postal`) creates significant CPU overhead when searching over node networks. Hoisting origin postal parsing outside candidate iteration and adding string length/digit fast-paths to `_zip3` avoids repeated regex compilation and string manipulation.
**Action:** Always pre-compute origin parameters outside destination candidate loops and use `len()` + `.isdigit()` fast-paths for standard postal code formats.
