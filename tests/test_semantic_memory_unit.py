"""Unit tests for semantic memory policy and settings (no live DB/API)."""

from unie_cortex.config import Settings
from unie_cortex.services.semantic_memory.embedding_policy import redact_basic_pii, sha256_hex, truncate


def test_semantic_brain_configured_requires_flag_and_url() -> None:
    s = Settings(semantic_memory_enabled=False, semantic_database_url="postgresql+asyncpg://x/y")
    assert s.semantic_brain_configured is False
    s2 = Settings(semantic_memory_enabled=True, semantic_database_url="postgresql+asyncpg://x/y")
    assert s2.semantic_brain_configured is True


def test_redact_basic_pii_masks_zip_and_email() -> None:
    t = "Ship to 90210-1234 contact a@b.com"
    o = redact_basic_pii(t)
    assert "90210" not in o
    assert "a@b.com" not in o


def test_truncate_and_hash() -> None:
    assert len(truncate("abcdef", 4)) <= 4
    assert len(sha256_hex("x")) == 64


def test_s3_artifacts_configured() -> None:
    s = Settings(s3_artifacts_bucket="  my-bucket  ")
    assert s.s3_artifacts_configured is True
