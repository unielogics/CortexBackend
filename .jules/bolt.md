## 2026-03-31 - Cache Pydantic model_dump in Batch Facility Resolving

**Learning:** Calling Pydantic v2 `.model_dump(exclude_none=True)` repeatedly inside batch processing loops (e.g. over hundreds of shipments sharing facility freight profiles) creates significant CPU serialization overhead. Caching `.model_dump()` dict results per object instance (`id(facility_freight)`) within the loop scope completely avoids redundant serialization without altering Pydantic validation or side effects.

**Action:** Look for `model_dump` calls inside `for shipment in shipments` or similar batch iteration loops where model instances are re-used, and cache the resulting dict per `id(instance)`.
