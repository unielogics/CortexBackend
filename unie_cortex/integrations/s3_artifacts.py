"""Optional S3 blob storage for uploads (when S3_ARTIFACTS_BUCKET is set)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _put_sync(*, bucket: str, key: str, body: bytes, content_type: str, region: str | None) -> str:
    import boto3

    kwargs = {}
    if region:
        kwargs["region_name"] = region
    client = boto3.client("s3", **kwargs)
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
    return f"s3://{bucket}/{key}"


async def put_bytes_async(*, key: str, body: bytes, content_type: str = "application/octet-stream") -> str:
    from unie_cortex.config import settings

    b = (settings.s3_artifacts_bucket or "").strip()
    if not b:
        raise RuntimeError("S3_ARTIFACTS_BUCKET is not configured")
    region = (settings.aws_region or "").strip() or None
    return await asyncio.to_thread(
        _put_sync, bucket=b, key=key, body=body, content_type=content_type, region=region
    )


def generate_presigned_put_url(*, key: str, content_type: str, expires_seconds: int = 3600) -> str | None:
    """Return a presigned PUT URL for direct browser upload, or None if S3 disabled."""
    from unie_cortex.config import settings

    b = (settings.s3_artifacts_bucket or "").strip()
    if not b:
        return None
    import boto3

    region = (settings.aws_region or "").strip() or None
    kwargs = {}
    if region:
        kwargs["region_name"] = region
    client = boto3.client("s3", **kwargs)
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": b, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_seconds,
    )
