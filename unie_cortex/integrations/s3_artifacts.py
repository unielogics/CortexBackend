"""Optional S3 blob storage for uploads (when S3_ARTIFACTS_BUCKET is set)."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse
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


def _parse_s3_uri(uri: str) -> tuple[str, str] | None:
    u = (uri or "").strip()
    if not u.startswith("s3://"):
        return None
    parsed = urlparse(u)
    bucket = parsed.netloc.strip()
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        return None
    return bucket, key


def _head_sync(*, bucket: str, key: str, region: str | None) -> dict | None:
    import boto3
    from botocore.exceptions import ClientError

    kwargs = {}
    if region:
        kwargs["region_name"] = region
    client = boto3.client("s3", **kwargs)
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        code = str((e.response or {}).get("Error", {}).get("Code") or "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


async def head_uri_async(uri: str) -> dict | None:
    from unie_cortex.config import settings

    parsed = _parse_s3_uri(uri)
    if parsed is None:
        return None
    bucket, key = parsed
    region = (settings.aws_region or "").strip() or None
    return await asyncio.to_thread(_head_sync, bucket=bucket, key=key, region=region)


def _transition_sync(*, bucket: str, key: str, storage_class: str, region: str | None) -> None:
    import boto3

    kwargs = {}
    if region:
        kwargs["region_name"] = region
    client = boto3.client("s3", **kwargs)
    client.copy_object(
        Bucket=bucket,
        Key=key,
        CopySource={"Bucket": bucket, "Key": key},
        MetadataDirective="COPY",
        StorageClass=storage_class,
    )


async def transition_uri_storage_class_async(uri: str, storage_class: str) -> bool:
    from unie_cortex.config import settings

    parsed = _parse_s3_uri(uri)
    if parsed is None:
        return False
    bucket, key = parsed
    sc = (storage_class or "").strip().upper()
    if not sc:
        return False
    region = (settings.aws_region or "").strip() or None
    await asyncio.to_thread(
        _transition_sync,
        bucket=bucket,
        key=key,
        storage_class=sc,
        region=region,
    )
    return True


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
