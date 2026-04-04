"""Load JSON secrets from AWS Secrets Manager (sync; call from startup or lazy resolver)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_secret_json(*, secret_arn: str, region_name: str | None) -> dict[str, Any]:
    """Fetch and parse a Secrets Manager secret string as JSON."""
    try:
        import boto3
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("boto3 is required for SEMANTIC_DATABASE_SECRET_ARN") from e

    client = boto3.client(
        "secretsmanager",
        region_name=region_name or None,
    )
    resp = client.get_secret_value(SecretId=secret_arn)
    raw = resp.get("SecretString") or ""
    return json.loads(raw)


def build_postgres_async_url_from_secret(secret: dict[str, Any]) -> str:
    """Build ``postgresql+asyncpg://`` URL from typical RDS-style secret keys."""
    user = secret.get("username") or secret.get("user")
    password = secret.get("password")
    host = secret.get("host")
    port = int(secret.get("port") or 5432)
    dbname = secret.get("dbname") or secret.get("database") or "postgres"
    if not all([user, password is not None, host]):
        raise ValueError("Secret must include username, password, host (and optionally port, dbname)")
    from urllib.parse import quote_plus

    return (
        f"postgresql+asyncpg://{quote_plus(str(user))}:{quote_plus(str(password))}"
        f"@{host}:{port}/{dbname}"
    )
