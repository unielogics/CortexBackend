from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from unie_cortex.db.models import MappingTemplate


async def seed_mapping_templates(session: AsyncSession) -> None:
    r = await session.execute(select(MappingTemplate).limit(1))
    if r.scalar_one_or_none():
        return
    templates = [
        MappingTemplate(
            vendor_key="generic_labels_v1",
            label="Generic shipping labels CSV",
            mappings={
                "labels": {
                    "tracking_number": "tracking_number",
                    "Tracking": "tracking_number",
                    "carrier": "carrier",
                    "Carrier": "carrier",
                    "service": "service_code",
                    "amount": "label_amount_usd",
                    "Amount": "label_amount_usd",
                    "cost": "label_amount_usd",
                    "weight": "weight_lb",
                    "Weight": "weight_lb",
                    "origin_zip": "origin_postal",
                    "dest_zip": "dest_postal",
                    "ship_date": "ship_date",
                },
                "tasks": {
                    "completed_at": "completed_at",
                    "timestamp": "completed_at",
                    "zone": "zone",
                    "Zone": "zone",
                    "operator": "operator_id",
                    "task_type": "task_type",
                    "duration_sec": "duration_sec",
                },
            },
        ),
    ]
    for t in templates:
        session.add(t)
    await session.flush()
