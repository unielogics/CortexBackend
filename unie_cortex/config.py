from __future__ import annotations

try:
    from typing import Self
except ImportError:  # Python < 3.11
    from typing_extensions import Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    unie_cortex_env: str = "development"

    # Auth — optional; when set, all /v1/* routes require X-API-Key or Authorization: Bearer <key>
    api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("API_KEY", "UNIE_CORTEX_API_KEY"),
    )
    api_keys: str | None = Field(
        None,
        validation_alias=AliasChoices("API_KEYS", "UNIE_CORTEX_API_KEYS"),
        description="Comma-separated list of valid API keys (overrides single API_KEY if set)",
    )
    user_auth_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("USER_AUTH_ENABLED", "user_auth_enabled"),
        description="Enable first-party UI user authentication endpoints and middleware checks.",
    )
    auth_token_secret: str | None = Field(
        None,
        validation_alias=AliasChoices("AUTH_TOKEN_SECRET", "auth_token_secret"),
        description="HMAC secret for signed auth session tokens. If unset, API_KEY is reused as fallback.",
    )
    auth_session_ttl_hours: int = Field(
        12,
        ge=1,
        le=24 * 14,
        validation_alias=AliasChoices("AUTH_SESSION_TTL_HOURS", "auth_session_ttl_hours"),
    )
    auth_cookie_name: str = Field(
        "unie_auth_session",
        validation_alias=AliasChoices("AUTH_COOKIE_NAME", "auth_cookie_name"),
    )
    bootstrap_auth_email: str = Field(
        "franco@unielogics.com",
        validation_alias=AliasChoices("BOOTSTRAP_AUTH_EMAIL", "bootstrap_auth_email"),
    )
    bootstrap_auth_password: str = Field(
        "",  # secret moved out of source — supplied via .env (gitignored)
        validation_alias=AliasChoices("BOOTSTRAP_AUTH_PASSWORD", "bootstrap_auth_password"),
    )
    bootstrap_auth_must_rotate_password: bool = Field(
        False,
        validation_alias=AliasChoices(
            "BOOTSTRAP_AUTH_MUST_ROTATE_PASSWORD",
            "bootstrap_auth_must_rotate_password",
        ),
        description="When true, bootstrap user receives must_rotate_password=true.",
    )
    cors_origins: str = Field(
        "",
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"),
        description="Comma-separated allowed origins; empty = * for dev",
    )
    public_rate_shop_tenant: str = Field(
        "__default__",
        validation_alias=AliasChoices("PUBLIC_RATE_SHOP_TENANT", "public_rate_shop_tenant"),
        description="Tenant scope used for the unauthenticated /v1/public/rate-shop endpoint.",
    )

    # Public audit-intake → provisioning + AWS SES email
    email_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("EMAIL_ENABLED", "email_enabled"),
        description="Master switch for outbound email (AWS SES). Off → provision + on-screen link only.",
    )
    email_sender: str | None = Field(
        None,
        validation_alias=AliasChoices("EMAIL_SENDER", "email_sender"),
        description="SES-verified From identity, e.g. no-reply@uniecortex.com.",
    )
    aws_ses_region: str = Field(
        "us-east-1",
        validation_alias=AliasChoices("AWS_SES_REGION", "aws_ses_region"),
    )
    ses_events_topic_arn: str | None = Field(
        None,
        validation_alias=AliasChoices("SES_EVENTS_TOPIC_ARN", "ses_events_topic_arn"),
        description="Optional SNS topic ARN allowlist for the SES bounce/complaint webhook (signature is verified regardless).",
    )
    app_base_url: str = Field(
        "https://ai.uniecortex.com",
        validation_alias=AliasChoices("APP_BASE_URL", "app_base_url"),
        description="Base URL of the authed app — used to build /invite/{token} onboarding links.",
    )
    intake_inviter_email: str | None = Field(
        None,
        validation_alias=AliasChoices("INTAKE_INVITER_EMAIL", "intake_inviter_email"),
        description="Super-admin AuthUser email that owns public-intake invitations (defaults to bootstrap_auth_email).",
    )
    audit_code_ttl_minutes: int = Field(
        30,
        validation_alias=AliasChoices("AUDIT_CODE_TTL_MINUTES", "audit_code_ttl_minutes"),
    )
    audit_code_max_attempts: int = Field(
        5,
        validation_alias=AliasChoices("AUDIT_CODE_MAX_ATTEMPTS", "audit_code_max_attempts"),
    )
    # ── UnieSales mirror (server-to-server, HMAC-signed) ───────────────────
    # After provisioning a public_intake submission, Cortex fires a
    # fire-and-forget POST to UnieSales' uniecortex public-intake endpoint
    # so the lead lands in the sales workspace. Failure is logged, never
    # raised — the audit-onboarding email path is unaffected.
    uniesales_public_intake_url: str | None = Field(
        "https://api.uniesales.com",
        validation_alias=AliasChoices(
            "UNIESALES_PUBLIC_INTAKE_URL",
            "uniesales_public_intake_url",
        ),
        description=(
            "UnieSales public-intake base URL (e.g. https://api.uniesales.com). "
            "Set to empty string to disable the mirror."
        ),
    )
    uniesales_intake_hmac_secret: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "UNIESALES_INTAKE_HMAC_SECRET",
            "uniesales_intake_hmac_secret",
        ),
        description=(
            "Shared HMAC secret for signing the X-UnieSales-Signature header. "
            "Pulled from AWS Secrets Manager (uniesales/prod/app). When unset, "
            "the mirror is skipped (logged warning, never raised)."
        ),
    )
    uniesales_mirror_timeout_seconds: float = Field(
        5.0,
        validation_alias=AliasChoices(
            "UNIESALES_MIRROR_TIMEOUT_SECONDS",
            "uniesales_mirror_timeout_seconds",
        ),
        description="HTTP timeout for the UnieSales mirror call.",
    )
    specialists: str = Field(
        "Maya Chen,Devon Reyes,Priya Anand",
        validation_alias=AliasChoices("SPECIALISTS", "specialists"),
        description="Comma-separated specialist roster for the 'speak with a specialist' booking.",
    )

    # MongoDB (preferred if set) — no Postgres/SQLite needed for Cortex
    mongodb_uri: str | None = Field(
        None,
        validation_alias=AliasChoices("MONGODB_URI", "MONGO_URI", "mongodb_uri"),
    )
    mongodb_db: str = Field(
        "unie_cortex",
        validation_alias=AliasChoices("MONGODB_DB", "mongodb_db"),
    )

    # SQLite/Postgres only when MONGODB_URI is empty
    database_url: str = Field(
        "sqlite+aiosqlite:///./unie_cortex.db",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    wms_intelligence_database_url: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "WMS_INTELLIGENCE_DATABASE_URL",
            "wms_intelligence_database_url",
        ),
        description=(
            "Read-only external WMS intelligence baseline source (Postgres URL). "
            "Used for warehouse nodes/pricing/peer settings/capacity bootstrap in Product Research "
            "and Seller Optimization."
        ),
    )
    tms_db_host: str | None = Field(
        None,
        validation_alias=AliasChoices("TMS_DB_HOST", "DB_HOST", "tms_db_host"),
        description="TMS read-only Postgres host (used to build WMS intelligence DB URL when explicit URL is unset).",
    )
    tms_db_port: int = Field(
        5432,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("TMS_DB_PORT", "DB_PORT", "tms_db_port"),
        description="TMS read-only Postgres port.",
    )
    tms_db_name: str | None = Field(
        None,
        validation_alias=AliasChoices("TMS_DB_NAME", "DB_NAME", "tms_db_name"),
        description="TMS read-only Postgres database name.",
    )
    tms_db_user: str | None = Field(
        None,
        validation_alias=AliasChoices("TMS_DB_USER", "DB_USER", "tms_db_user"),
        description="TMS read-only Postgres username.",
    )
    tms_db_password: str | None = Field(
        None,
        validation_alias=AliasChoices("TMS_DB_PASSWORD", "DB_PASSWORD", "tms_db_password"),
        description="TMS read-only Postgres password.",
    )
    tms_db_ssl: str = Field(
        "require",
        validation_alias=AliasChoices("TMS_DB_SSL", "DB_SSL", "tms_db_ssl"),
        description="TMS read-only Postgres sslmode (e.g. require, verify-ca, verify-full, disable).",
    )
    tms_db_schema: str = Field(
        "cortex_export",
        validation_alias=AliasChoices("TMS_DB_SCHEMA", "DB_SCHEMA", "tms_db_schema"),
        description=(
            "Postgres schema for the WMS/TMS intelligence feed (e.g. baseline_entities). "
            "This is not necessarily where LTL serving objects live: use TMS_LTL_SERVING_SCHEMA for sv_*."
        ),
    )
    tms_ltl_serving_schema: str = Field(
        "cortex",
        validation_alias=AliasChoices(
            "TMS_LTL_SERVING_SCHEMA",
            "tms_ltl_serving_schema",
        ),
        description=(
            "Schema the LTL engine queries for sv_lanes, sv_zones, sv_rate_lines, and related sv_* objects. "
            "Default cortex (serving views); tms_db_schema often remains cortex_export for baseline_entities. "
            "Override if your sv_* objects live elsewhere. The DB user needs SELECT on these objects."
        ),
    )
    tms_db_preferred_for_intelligence: bool = Field(
        True,
        validation_alias=AliasChoices(
            "TMS_DB_PREFERRED_FOR_INTELLIGENCE",
            "tms_db_preferred_for_intelligence",
        ),
        description=(
            "When true, wms_intelligence_db_url() prefers TMS_DB_* over WMS_INTELLIGENCE_DATABASE_URL. "
            "When false, the explicit WMS URL is preferred for baseline intelligence. "
            "LTL sv_* reads always use TMS_DB_* via tms_serving_db_url(), independent of this flag."
        ),
    )
    wms_only_strict: bool = Field(
        True,
        validation_alias=AliasChoices("WMS_ONLY_STRICT", "wms_only_strict"),
        description=(
            "When true, warehouse/pricing intelligence must come from WMS baseline entities only. "
            "Non-WMS fallback sources are disabled."
        ),
    )
    wms_only_require_complete_baseline: bool = Field(
        True,
        validation_alias=AliasChoices(
            "WMS_ONLY_REQUIRE_COMPLETE_BASELINE",
            "wms_only_require_complete_baseline",
        ),
        description=(
            "When true under WMS_ONLY_STRICT, block optimization runs unless all required WMS baseline "
            "entity types are present and non-empty."
        ),
    )
    aurora_dsql_cluster_host: str | None = Field(
        None,
        validation_alias=AliasChoices("AURORA_DSQL_CLUSTER_HOST", "aurora_dsql_cluster_host"),
        description="When set, SQLAlchemy uses Aurora DSQL async creator instead of DATABASE_URL.",
    )
    aurora_dsql_user: str | None = Field(
        None,
        validation_alias=AliasChoices("AURORA_DSQL_USER", "aurora_dsql_user"),
    )
    aurora_dsql_dbname: str = Field(
        "postgres",
        validation_alias=AliasChoices("AURORA_DSQL_DBNAME", "aurora_dsql_dbname"),
    )
    aurora_dsql_region: str | None = Field(
        None,
        validation_alias=AliasChoices("AURORA_DSQL_REGION", "aurora_dsql_region"),
    )
    aurora_dsql_aws_profile: str | None = Field(
        None,
        validation_alias=AliasChoices("AURORA_DSQL_AWS_PROFILE", "aurora_dsql_aws_profile"),
    )
    aurora_dsql_token_duration_secs: int | None = Field(
        None,
        ge=60,
        validation_alias=AliasChoices(
            "AURORA_DSQL_TOKEN_DURATION_SECS", "aurora_dsql_token_duration_secs"
        ),
    )
    aurora_dsql_pool_recycle: int = Field(
        3600,
        ge=60,
        validation_alias=AliasChoices("AURORA_DSQL_POOL_RECYCLE", "aurora_dsql_pool_recycle"),
    )
    semantic_memory_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("SEMANTIC_MEMORY_ENABLED", "semantic_memory_enabled"),
    )
    embedding_provider: str | None = Field(
        None,
        validation_alias=AliasChoices("EMBEDDING_PROVIDER", "embedding_provider"),
        description="e.g. openai — used by audit-run embedding queue guard in semantic_memory pipeline.",
    )
    semantic_database_url: str | None = Field(
        None,
        validation_alias=AliasChoices("SEMANTIC_DATABASE_URL", "semantic_database_url"),
    )
    semantic_database_secret_arn: str | None = Field(
        None,
        validation_alias=AliasChoices("SEMANTIC_DATABASE_SECRET_ARN", "semantic_database_secret_arn"),
    )
    semantic_database_region: str | None = Field(
        None,
        validation_alias=AliasChoices("SEMANTIC_DATABASE_REGION", "semantic_database_region"),
    )
    semantic_pool_recycle: int = Field(
        3600,
        ge=60,
        validation_alias=AliasChoices("SEMANTIC_POOL_RECYCLE", "semantic_pool_recycle"),
    )
    semantic_embed_max_concurrency: int = Field(
        4,
        ge=1,
        le=64,
        validation_alias=AliasChoices("SEMANTIC_EMBED_MAX_CONCURRENCY", "semantic_embed_max_concurrency"),
    )
    semantic_embed_max_chars_audit: int = Field(
        8000,
        ge=256,
        validation_alias=AliasChoices("SEMANTIC_EMBED_MAX_CHARS_AUDIT", "semantic_embed_max_chars_audit"),
    )
    semantic_embed_max_chars_proposal: int = Field(
        4000,
        ge=256,
        validation_alias=AliasChoices(
            "SEMANTIC_EMBED_MAX_CHARS_PROPOSAL", "semantic_embed_max_chars_proposal"
        ),
    )
    aws_region: str | None = Field(
        None,
        validation_alias=AliasChoices("AWS_REGION", "aws_region"),
    )
    s3_artifacts_bucket: str | None = Field(
        None,
        validation_alias=AliasChoices("S3_ARTIFACTS_BUCKET", "s3_artifacts_bucket"),
    )
    s3_artifacts_prefix: str | None = Field(
        None,
        validation_alias=AliasChoices("S3_ARTIFACTS_PREFIX", "s3_artifacts_prefix"),
    )
    upload_dir: str = Field(
        "./uploads",
        validation_alias=AliasChoices("UPLOAD_DIR", "upload_dir"),
    )
    # Warehouse-audit uploads above this size (bytes) defer their ingest to the
    # audit-run pipeline's `csv_ingest` stage (Part 0B). Smaller uploads still
    # ingest in-band during the POST and return `ingest_status: "complete"` so
    # typical (<5 MB, <15k-row) CSVs don't pay for the deferred lane.
    upload_defer_ingest_bytes: int = Field(
        5 * 1024 * 1024,
        validation_alias=AliasChoices("UPLOAD_DEFER_INGEST_BYTES", "upload_defer_ingest_bytes"),
    )
    distribution_local_export_dir: str | None = Field(
        None,
        validation_alias=AliasChoices("DISTRIBUTION_LOCAL_EXPORT_DIR", "distribution_local_export_dir"),
        description="When set, write distribution_{job_id}.json here after each PRO run (server filesystem).",
    )

    rate_shopping_url: str | None = Field(
        None,
        validation_alias=AliasChoices("RATE_SHOPPING_URL", "rate_shopping_url"),
    )
    rate_shopping_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("RATE_SHOPPING_API_KEY", "rate_shopping_api_key"),
    )
    geocoding_mapbox_token: str | None = Field(
        None,
        validation_alias=AliasChoices("GEOCODING_MAPBOX_TOKEN", "MAPBOX_TOKEN", "geocoding_mapbox_token"),
    )
    geocoding_nominatim: bool = Field(
        True,
        validation_alias=AliasChoices("GEOCODING_NOMINATIM", "geocoding_nominatim"),
    )
    geoapify_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("GEOAPIFY_API_KEY", "geoapify_api_key"),
    )

    shippo_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("SHIPPO_API_KEY", "shippo_api_key"),
    )
    shippo_mock_mode: bool = Field(
        False,
        validation_alias=AliasChoices("SHIPPO_MOCK_MODE", "shippo_mock_mode"),
    )
    shippo_rate_limit_backoff_sec: float = Field(
        1.5,
        gt=0,
        validation_alias=AliasChoices(
            "SHIPPO_RATE_LIMIT_BACKOFF_SEC",
            "shippo_rate_limit_backoff_sec",
        ),
        description="Seed delay (seconds) for Shippo 429 / 5xx exponential backoff.",
    )
    shippo_max_retries: int = Field(
        3,
        ge=1,
        le=10,
        validation_alias=AliasChoices("SHIPPO_MAX_RETRIES", "shippo_max_retries"),
        description="Max attempts per Shippo quote call before giving up.",
    )
    warehouse_placement_v2_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "WAREHOUSE_PLACEMENT_V2_ENABLED",
            "warehouse_placement_v2_enabled",
        ),
        description=(
            "When true (default), intelligence_run / order_financial_planning attach a "
            "`placement_v2` block to `warehouse_network_intelligence` produced by the reusable "
            "warehouse placement engine (Cortex rate cache + Shippo + cuOpt primary driver). "
            "The legacy fields stay untouched so the existing UI keeps working. The V3 seller "
            "optimization page (state rate-shop grid, inventory spread, inbound schedule, LTL "
            "route arcs on the heatmap) requires this block, so flipping it off will leave "
            "those tiles in their empty state."
        ),
    )
    warehouse_placement_keepa_max_asins: int = Field(
        80,
        ge=0,
        validation_alias=AliasChoices(
            "WAREHOUSE_PLACEMENT_KEEPA_MAX_ASINS",
            "warehouse_placement_keepa_max_asins",
        ),
        description=(
            "Hard cap on Keepa lookups per placement run. ASINs are sorted by monthly_units "
            "descending so the most-impactful SKUs win when above the cap. Set 0 to disable."
        ),
    )
    warehouse_placement_keepa_per_call_timeout_sec: float = Field(
        8.0,
        gt=0,
        validation_alias=AliasChoices(
            "WAREHOUSE_PLACEMENT_KEEPA_PER_CALL_TIMEOUT_SEC",
            "warehouse_placement_keepa_per_call_timeout_sec",
        ),
        description="Per-ASIN timeout (seconds) for Keepa lookups during placement enrichment.",
    )
    warehouse_placement_keepa_concurrency: int = Field(
        4,
        ge=1,
        le=32,
        validation_alias=AliasChoices(
            "WAREHOUSE_PLACEMENT_KEEPA_CONCURRENCY",
            "warehouse_placement_keepa_concurrency",
        ),
        description="Parallel Keepa lookups during placement enrichment.",
    )

    keepa_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("KEEPA_API_KEY", "keepa_api_key"),
    )
    keepa_ttl_days: int = Field(
        30,
        validation_alias=AliasChoices("KEEPA_TTL_DAYS", "keepa_ttl_days"),
        description=(
            "Per-ASIN Keepa cache TTL in days (full product JSON reuses until expiry). "
            "For fresher listings, set e.g. KEEPA_TTL_DAYS=2. Time-series signals come from each "
            "payload's csv/stats, not from offer row counts."
        ),
    )
    product_research_keepa_refresh_hours: int = Field(
        48,
        ge=1,
        le=24 * 30,
        validation_alias=AliasChoices(
            "PRODUCT_RESEARCH_KEEPA_REFRESH_HOURS",
            "product_research_keepa_refresh_hours",
        ),
        description="Keepa freshness target for Product Research runs (hours).",
    )
    product_research_rerun_update_days: int = Field(
        5,
        ge=1,
        le=90,
        validation_alias=AliasChoices(
            "PRODUCT_RESEARCH_RERUN_UPDATE_DAYS",
            "product_research_rerun_update_days",
        ),
        description="When rerun is older than this age (days), persist fresh Product Research run state.",
    )
    product_research_hot_retention_months: int = Field(
        6,
        ge=1,
        le=36,
        validation_alias=AliasChoices(
            "PRODUCT_RESEARCH_HOT_RETENTION_MONTHS",
            "product_research_hot_retention_months",
        ),
        description="Hot-system retention window before archive lifecycle (months).",
    )
    product_research_require_s3_durability_in_prod: bool = Field(
        True,
        validation_alias=AliasChoices(
            "PRODUCT_RESEARCH_REQUIRE_S3_DURABILITY_IN_PROD",
            "product_research_require_s3_durability_in_prod",
        ),
        description="When true in production, fail startup if S3 artifacts are not configured.",
    )
    product_research_archive_storage_class: str = Field(
        "STANDARD_IA",
        validation_alias=AliasChoices(
            "PRODUCT_RESEARCH_ARCHIVE_STORAGE_CLASS",
            "product_research_archive_storage_class",
        ),
        description="Target S3 storage class used by Product Research lifecycle transition job.",
    )
    product_research_lifecycle_batch_size: int = Field(
        200,
        ge=1,
        le=5000,
        validation_alias=AliasChoices(
            "PRODUCT_RESEARCH_LIFECYCLE_BATCH_SIZE",
            "product_research_lifecycle_batch_size",
        ),
        description="Max Product Research runs processed per lifecycle audit execution.",
    )
    keepa_assume_unknown_condition_is_new: bool = Field(
        True,
        validation_alias=AliasChoices(
            "KEEPA_ASSUME_UNKNOWN_CONDITION_IS_NEW",
            "keepa_assume_unknown_condition_is_new",
        ),
        description=(
            "When true, Keepa offer rows with missing/unparseable condition count toward new-path "
            "merchant metrics (legacy). When false, they are 'unknown' and excluded from new-path counts."
        ),
    )
    keepa_offers_digest_max_sellers: int = Field(
        250,
        validation_alias=AliasChoices(
            "KEEPA_OFFERS_DIGEST_MAX_SELLERS",
            "keepa_offers_digest_max_sellers",
        ),
        ge=1,
        le=10_000,
        description="Cap offers_by_seller[] length in keepa_offers_digest for API/Mongo size",
    )
    keepa_trend_bundle_max_points: int = Field(
        160,
        validation_alias=AliasChoices(
            "KEEPA_TREND_BUNDLE_MAX_POINTS",
            "keepa_trend_bundle_max_points",
        ),
        ge=24,
        le=500,
        description="Max downsampled points in keepa_trend_bundle chart series",
    )
    keepa_trend_risk_discount: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "KEEPA_TREND_RISK_DISCOUNT",
            "keepa_trend_risk_discount",
        ),
        ge=0.1,
        le=2.0,
        description="Multiplies suggested_cover_units in keepa_trend_bundle (<1 = more conservative)",
    )
    keepa_trend_forecast_lookback_days: int = Field(
        60,
        validation_alias=AliasChoices(
            "KEEPA_TREND_FORECAST_LOOKBACK_DAYS",
            "keepa_trend_forecast_lookback_days",
        ),
        ge=14,
        le=365,
        description="Lookback window used for next-30d Keepa trend forecast factors",
    )
    keepa_trend_forecast_horizon_days: int = Field(
        30,
        validation_alias=AliasChoices(
            "KEEPA_TREND_FORECAST_HORIZON_DAYS",
            "keepa_trend_forecast_horizon_days",
        ),
        ge=7,
        le=120,
        description="Forward forecast horizon days for keepa_trend_bundle.forecast_next_30d",
    )
    keepa_hybrid_buybox_weight: float = Field(
        0.7,
        validation_alias=AliasChoices(
            "KEEPA_HYBRID_BUYBOX_WEIGHT",
            "keepa_hybrid_buybox_weight",
        ),
        ge=0.0,
        le=1.0,
        description="Weight for buy-box intelligence in unified sell decision scoring",
    )
    keepa_hybrid_trend_weight: float = Field(
        0.3,
        validation_alias=AliasChoices(
            "KEEPA_HYBRID_TREND_WEIGHT",
            "keepa_hybrid_trend_weight",
        ),
        ge=0.0,
        le=1.0,
        description="Weight for trend intelligence in unified sell decision scoring",
    )
    keepa_hybrid_review_weight: float = Field(
        0.2,
        validation_alias=AliasChoices(
            "KEEPA_HYBRID_REVIEW_WEIGHT",
            "keepa_hybrid_review_weight",
        ),
        ge=0.0,
        le=1.0,
        description="Review-signal contribution factor inside trend side of hybrid sell decision",
    )
    keepa_product_offers: int = Field(
        20,
        validation_alias=AliasChoices("KEEPA_PRODUCT_OFFERS", "keepa_product_offers"),
        description="Include N marketplace offer rows on Keepa product calls (0=omit; uses more tokens)",
    )
    keepa_product_stats_days: int = Field(
        90,
        validation_alias=AliasChoices("KEEPA_PRODUCT_STATS_DAYS", "keepa_product_stats_days"),
        description="Keepa stats window in days on product calls (0=omit stats param)",
    )
    keepa_planning_monthly_cap_3p: int = Field(
        400,
        validation_alias=AliasChoices("KEEPA_PLANNING_MONTHLY_CAP_3P", "keepa_planning_monthly_cap_3p"),
        description="Max suggested monthly units for unknown 3P (Keepa ASIN velocity is marketplace-wide)",
    )
    keepa_planning_large_velocity_threshold: int = Field(
        800,
        validation_alias=AliasChoices(
            "KEEPA_PLANNING_LARGE_VELOCITY_THRESHOLD", "keepa_planning_large_velocity_threshold"
        ),
        description="Above this Keepa monthly mid, apply strict slice only (no small-listing floor)",
    )
    keepa_planning_buybox_winner_cap: int = Field(
        1200,
        validation_alias=AliasChoices("KEEPA_PLANNING_BUYBOX_WINNER_CAP", "keepa_planning_buybox_winner_cap"),
        description="Cap when marketplace_seller_id matches Keepa buy box seller (still not POS truth)",
    )
    keepa_buybox_history_window_days: int = Field(
        30,
        validation_alias=AliasChoices(
            "KEEPA_BUYBOX_HISTORY_WINDOW_DAYS", "keepa_buybox_history_window_days"
        ),
        description="Clip buyBoxSellerIdHistory into this many recent days for win-% shares",
    )
    keepa_planning_buybox_history_known_cap: int = Field(
        50_000,
        validation_alias=AliasChoices(
            "KEEPA_PLANNING_BUYBOX_HISTORY_KNOWN_CAP", "keepa_planning_buybox_history_known_cap"
        ),
        description="Cap planning units when seller id matches a seller in buy box history (share × velocity)",
    )
    keepa_planning_buybox_follower_similarity_weight: float = Field(
        0.18,
        validation_alias=AliasChoices(
            "KEEPA_PLANNING_BUYBOX_FOLLOWER_SIMILARITY_WEIGHT",
            "keepa_planning_buybox_follower_similarity_weight",
        ),
        description="How much optional client rating/review/FBA vs cohort nudges follower-based planning (0=off)",
    )
    keepa_planning_peer_review_log_weight: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "KEEPA_PLANNING_PEER_REVIEW_LOG_WEIGHT",
            "keepa_planning_peer_review_log_weight",
        ),
        description="Weight on |log1p(client_reviews)-log1p(peer_reviews)| in peer distance for buy-box planning",
    )
    keepa_planning_peer_rating_weight: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "KEEPA_PLANNING_PEER_RATING_WEIGHT",
            "keepa_planning_peer_rating_weight",
        ),
        description="Weight on |client_rating_pct-peer_rating_pct|/100 in peer distance for buy-box planning",
    )
    keepa_planning_peer_distance_epsilon: float = Field(
        0.35,
        validation_alias=AliasChoices(
            "KEEPA_PLANNING_PEER_DISTANCE_EPSILON",
            "keepa_planning_peer_distance_epsilon",
        ),
        description="Peers within d_min + epsilon are averaged for reference buy-box win %",
    )
    keepa_volume_intelligence_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "KEEPA_VOLUME_INTELLIGENCE_ENABLED",
            "keepa_volume_intelligence_enabled",
        ),
        description="Blend sales-rank + review momentum with optional learned category scale before seller planning",
    )
    keepa_volume_model_version: str = Field(
        "cortex_volume_v1",
        validation_alias=AliasChoices(
            "KEEPA_VOLUME_MODEL_VERSION",
            "keepa_volume_model_version",
        ),
        description="Version tag stored on demand.volume_intelligence for audits",
    )
    volume_calibration_store_path: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "VOLUME_CALIBRATION_STORE_PATH",
            "volume_calibration_store_path",
        ),
        description="Optional JSON path for per-category scale_ema learning (actual vs predicted monthly units)",
    )
    volume_calibration_alpha: float = Field(
        0.15,
        validation_alias=AliasChoices(
            "VOLUME_CALIBRATION_ALPHA",
            "volume_calibration_alpha",
        ),
        ge=0.01,
        le=0.5,
        description="EMA weight for each volume calibration observation",
    )
    placement_mock_destinations_per_warehouse: int = Field(
        48,
        validation_alias=AliasChoices(
            "PLACEMENT_MOCK_DESTINATIONS_PER_WAREHOUSE",
            "placement_mock_destinations_per_warehouse",
        ),
        description="Mock parcel quotes per warehouse (default 48 = one hub per contiguous state)",
    )
    placement_mock_midpoint_tie_band: float = Field(
        0.07,
        validation_alias=AliasChoices(
            "PLACEMENT_MOCK_MIDPOINT_TIE_BAND",
            "placement_mock_midpoint_tie_band",
        ),
        description="Relative distance band: destinations within this fraction of best distance attach to multiple warehouses",
    )
    placement_mock_state_primary_assignment: str = Field(
        "min_mock_parcel",
        validation_alias=AliasChoices(
            "PLACEMENT_MOCK_STATE_PRIMARY_ASSIGNMENT",
            "placement_mock_state_primary_assignment",
        ),
        description="How each state hub picks primary DC for demand-weighted metrics: min_mock_parcel | distance_tie_band",
    )
    label_state_weight_blend_min_lines: float = Field(
        200.0,
        validation_alias=AliasChoices(
            "LABEL_STATE_WEIGHT_BLEND_MIN_LINES",
            "label_state_weight_blend_min_lines",
        ),
        description="Label line count at which blend_lambda reaches 1.0 when merging label state mix with default prior",
    )
    placement_min_inter_warehouse_transfer_units: float = Field(
        100.0,
        validation_alias=AliasChoices(
            "PLACEMENT_MIN_INTER_WAREHOUSE_TRANSFER_UNITS",
            "placement_min_inter_warehouse_transfer_units",
        ),
        description="Hub→node replenishment batch guidance: 0 disables; else prefer 2-mo cover when it clears this minimum",
    )
    placement_max_months_min_transfer_horizon: int = Field(
        12,
        validation_alias=AliasChoices(
            "PLACEMENT_MAX_MONTHS_MIN_TRANSFER_HORIZON",
            "placement_max_months_min_transfer_horizon",
        ),
        description="Max months of destination flow to search when sizing a batch to meet min transfer units",
    )
    smart_network_min_monthly_units_to_expand_beyond_one: float = Field(
        250.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_MONTHLY_UNITS_TO_EXPAND_BEYOND_ONE",
            "smart_network_min_monthly_units_to_expand_beyond_one",
        ),
        description=(
            "Minimum total catalog monthly demand (MOQ) to consider multi-warehouse expansion (k≥2). "
            "Also used with uplift off: stay single-node below this threshold unless uplift raises gate demand. "
            "Default 250; pair with per-secondary-node floors below."
        ),
    )
    smart_network_multi_node_moq_gate_uplift_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MULTI_NODE_MOQ_GATE_UPLIFT_ENABLED",
            "smart_network_multi_node_moq_gate_uplift_enabled",
        ),
        description=(
            "For k≥2 layouts, evaluate MOQ gates at max(stated gate demand, min catalog velocity implied by inverse-mock "
            "shares and per-node flow floors) so multi-DC + inter-warehouse transfer thresholds can be planned without "
            "collapsing to one node purely on low *stated* velocity."
        ),
    )
    smart_network_min_units_per_warehouse_monthly_flow: float = Field(
        100.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_UNITS_PER_WAREHOUSE_MONTHLY_FLOW",
            "smart_network_min_units_per_warehouse_monthly_flow",
        ),
        description="MOQ-style floor on modeled monthly units per active warehouse (1–2 nodes)",
    )
    smart_network_min_units_per_warehouse_when_three_or_more_nodes: float = Field(
        100.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_UNITS_PER_WAREHOUSE_WHEN_THREE_OR_MORE_NODES",
            "smart_network_min_units_per_warehouse_when_three_or_more_nodes",
        ),
        description="Per-node monthly flow floor when three or more warehouses are active",
    )
    smart_network_min_units_per_secondary_warehouse_monthly_flow: float = Field(
        100.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_UNITS_PER_SECONDARY_WAREHOUSE_MONTHLY_FLOW",
            "smart_network_min_units_per_secondary_warehouse_monthly_flow",
        ),
        description=(
            "Minimum modeled monthly units for 2nd/3rd+ active DCs (non-primary in priority layout). "
            "Default 100 for flexible multi-DC; TODO: derive per facility from WMS inbound MOQ when available."
        ),
    )
    smart_network_max_warehouses: int = Field(
        8,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MAX_WAREHOUSES",
            "smart_network_max_warehouses",
        ),
        description="Hard cap on auto-expanded warehouse count (US regional archetypes)",
    )
    smart_network_monthly_orders_per_additional_warehouse: float = Field(
        1250.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MONTHLY_ORDERS_PER_ADDITIONAL_WAREHOUSE",
            "smart_network_monthly_orders_per_additional_warehouse",
        ),
        ge=1.0,
        description=(
            "Multi-DC target count scales as min(max_warehouses, base_multi + floor(monthly_units / this)) "
            "when ``smart_network_use_step_formula_for_max_nodes`` is true (legacy) and explicit volume tiers "
            "are not passed."
        ),
    )
    smart_network_use_step_formula_for_max_nodes: bool = Field(
        False,
        validation_alias=AliasChoices(
            "SMART_NETWORK_USE_STEP_FORMULA_FOR_MAX_NODES",
            "smart_network_use_step_formula_for_max_nodes",
        ),
        description=(
            "When false (default), ``recommend_warehouse_network`` / trim / recommendation options cap node count "
            "using default volume tiers (third DC at ≥1500 catalog units/mo). "
            "When true, restores the legacy base_multi_dc + floor(monthly/step) formula for callers that omit explicit tiers."
        ),
    )
    smart_network_multi_origin_min_separation_miles: float = Field(
        150.0,
        ge=0.0,
        le=3000.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MULTI_ORIGIN_MIN_SEPARATION_MILES",
            "smart_network_multi_origin_min_separation_miles",
        ),
        description=(
            "When multiple product-origin ZIPs are closer than this (great-circle), collapse to one anchor seed "
            "before smart-network expansion; keep distinct origins when farther apart."
        ),
    )
    smart_network_min_multi_dc_warehouse_count: int = Field(
        2,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_MULTI_DC_WAREHOUSE_COUNT",
            "smart_network_min_multi_dc_warehouse_count",
        ),
        ge=2,
        le=8,
        description="Minimum warehouses in the multi-DC recommendation option (before volume-based steps).",
    )
    smart_network_default_lane_cost_per_lb: float = Field(
        0.15,
        validation_alias=AliasChoices(
            "SMART_NETWORK_DEFAULT_LANE_COST_PER_LB",
            "smart_network_default_lane_cost_per_lb",
        ),
        description="Star replenishment $/lb from hub to each spoke when auto-building lanes",
    )
    smart_network_primary_dc_by_supplier_proximity: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_PRIMARY_DC_BY_SUPPLIER_PROXIMITY",
            "smart_network_primary_dc_by_supplier_proximity",
        ),
        description=(
            "When product_origin_postal is set on the run, pick the primary stocking DC (hub) as the candidate "
            "warehouse closest to that ZIP (great-circle on resolved lat/lon). Additional DCs rank by contract "
            "fee proxy + demand-weighted mock last mile."
        ),
    )
    smart_network_secondary_require_opposite_coast: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_SECONDARY_REQUIRE_OPPOSITE_COAST",
            "smart_network_secondary_require_opposite_coast",
        ),
        description=(
            "When ranking 2nd+ warehouses, list Pacific (CA/OR/WA) candidates before non-Pacific when the primary "
            "is non-Pacific, and the reverse when the primary is Pacific, so the first secondary is the best-scoring "
            "option on the other coast whenever the merged candidate pool includes at least one opposite-coast node. "
            "Does not inject warehouses; use the default archetype pool or Prep Center export with both coasts. "
            "Remaining nodes follow the same fee + 48-state mock score."
        ),
    )
    smart_network_cuopt_rank_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_CUOPT_RANK_ENABLED",
            "smart_network_cuopt_rank_enabled",
        ),
        description=(
            "When True and a cuOpt solver is configured (CUOPT_SELF_HOSTED_URL and/or "
            "multi_dc_cuopt_cloud_enabled with CUOPT_API_KEY or NVIDIA_API_KEY), reorder secondary warehouses using "
            "cuOpt visit order on a fused cost matrix (geo + 48-state mock parcel proxies), preserving opposite-coast "
            "tiers when smart_network_secondary_require_opposite_coast is on. Same stack as item intelligence."
        ),
    )
    smart_network_cuopt_rank_timeout_seconds: float = Field(
        25.0,
        ge=3.0,
        le=120.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_CUOPT_RANK_TIMEOUT_SECONDS",
            "smart_network_cuopt_rank_timeout_seconds",
        ),
        description="Poll timeout for self-hosted cuOpt when refining smart-network secondary order.",
    )
    smart_network_secondary_rank_contract_fee_weight: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_SECONDARY_RANK_CONTRACT_FEE_WEIGHT",
            "smart_network_secondary_rank_contract_fee_weight",
        ),
        ge=0.0,
        le=100.0,
        description="Weight on inbound+outbound+storage fee proxy when ranking 2nd+ warehouses (with origin) or spokes after request hub.",
    )
    smart_network_secondary_rank_last_mile_weight: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_SECONDARY_RANK_LAST_MILE_WEIGHT",
            "smart_network_secondary_rank_last_mile_weight",
        ),
        ge=0.0,
        le=100.0,
        description="Weight on demand-weighted mock parcel (+ hot ZIP3 proxy) when ranking secondary warehouses.",
    )
    seller_planning_rate_shop_max_warehouses: int = Field(
        8,
        ge=1,
        le=25,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_RATE_SHOP_MAX_WAREHOUSES",
            "seller_planning_rate_shop_max_warehouses",
        ),
        description=(
            "Seller order-financial placement grids: mock parcel / zone comparison across up to this many DCs "
            "(smart-network selected nodes first, then engagement default archetypes). Feeds cuOpt fusion when "
            "the FBM scenario still uses one linehaul-active node but national hot-zone rate shopping spans several."
        ),
    )
    seller_planning_hot_zone_node_expansion_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_HOT_ZONE_NODE_EXPANSION_ENABLED",
            "seller_planning_hot_zone_node_expansion_enabled",
        ),
        description=(
            "When true, Seller planning candidate node expansion prioritizes warehouses in top-demand hot states "
            "first, then nearby candidates within SELLER_PLANNING_HOT_ZONE_RADIUS_MILES before generic fallback fill."
        ),
    )
    seller_planning_hot_zone_top_states: int = Field(
        8,
        ge=1,
        le=24,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_HOT_ZONE_TOP_STATES",
            "seller_planning_hot_zone_top_states",
        ),
        description="Number of highest-demand states (from blended CSV demand weights) used for hot-zone node prioritization.",
    )
    seller_planning_hot_zone_radius_miles: float = Field(
        250.0,
        ge=0.0,
        le=3000.0,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_HOT_ZONE_RADIUS_MILES",
            "seller_planning_hot_zone_radius_miles",
        ),
        description=(
            "Secondary expansion radius around hot-state hub ZIPs. Candidate warehouses within this great-circle "
            "distance are prioritized before generic national fallback nodes."
        ),
    )
    smart_network_auto_trim_client_warehouses: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_AUTO_TRIM_CLIENT_WAREHOUSES",
            "smart_network_auto_trim_client_warehouses",
        ),
        description=(
            "When auto_expand is off, trim client-supplied warehouses to MOQ/volume-feasible count "
            "(same gates as smart network expand; does not add nodes outside the request)."
        ),
    )
    smart_network_subset_cost_optimization_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_SUBSET_COST_OPTIMIZATION_ENABLED",
            "smart_network_subset_cost_optimization_enabled",
        ),
        description=(
            "When True, evaluate MOQ-feasible warehouse subsets (primary + combinations from the ranked branch) "
            "and pick the layout minimizing last-mile + hub→spoke linehaul proxy; not only prefix-of-priority greedy."
        ),
    )
    smart_network_subset_branch_width: int = Field(
        8,
        ge=2,
        le=16,
        validation_alias=AliasChoices(
            "SMART_NETWORK_SUBSET_BRANCH_WIDTH",
            "smart_network_subset_branch_width",
        ),
        description="Max non-primary candidates considered in subset enumeration (combinatorial cap).",
    )
    smart_network_moq_gate_demand_stress_factor: float = Field(
        0.85,
        ge=0.3,
        le=1.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MOQ_GATE_DEMAND_STRESS_FACTOR",
            "smart_network_moq_gate_demand_stress_factor",
        ),
        description=(
            "When no explicit monthly_total_demand_units_low is passed, MOQ gates use mid × this factor "
            "(<1 = conservative vs planning mid). Ignored when low band is supplied from catalog Keepa estimates."
        ),
    )
    smart_network_linehaul_km_scale_for_selection_proxy: float = Field(
        800.0,
        ge=50.0,
        le=5000.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_LINEHAUL_KM_SCALE_FOR_SELECTION_PROXY",
            "smart_network_linehaul_km_scale_for_selection_proxy",
        ),
        description="Hub→spoke linehaul proxy multiplier uses 1 + haversine_km / this scale.",
    )
    smart_network_fixed_cost_usd_per_active_node_monthly: float = Field(
        0.0,
        ge=0.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_FIXED_COST_USD_PER_ACTIVE_NODE_MONTHLY",
            "smart_network_fixed_cost_usd_per_active_node_monthly",
        ),
        description="Optional fixed $/month per active DC added to the subset selection objective (discourages extra nodes).",
    )
    smart_network_free_delivery_soft_score_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_FREE_DELIVERY_SOFT_SCORE_ENABLED",
            "smart_network_free_delivery_soft_score_enabled",
        ),
        description="When True, include per-SKU free-delivery policy penalty as a soft term in network subset objective.",
    )
    smart_network_free_delivery_coverage_penalty_weight: float = Field(
        1.0,
        ge=0.0,
        le=20.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_FREE_DELIVERY_COVERAGE_PENALTY_WEIGHT",
            "smart_network_free_delivery_coverage_penalty_weight",
        ),
        description=(
            "Weight on uncovered free-delivery policy monthly-shipping penalty "
            "for the soft network objective term."
        ),
    )
    smart_network_free_delivery_threshold_gap_penalty_weight: float = Field(
        1.0,
        ge=0.0,
        le=20.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_FREE_DELIVERY_THRESHOLD_GAP_PENALTY_WEIGHT",
            "smart_network_free_delivery_threshold_gap_penalty_weight",
        ),
        description="Weight on minimum-purchase threshold-gap shipping penalty in the soft network objective term.",
    )
    smart_network_learned_rank_weights_enabled: bool = Field(
        False,
        validation_alias=AliasChoices(
            "SMART_NETWORK_LEARNED_RANK_WEIGHTS_ENABLED",
            "smart_network_learned_rank_weights_enabled",
        ),
        description="When True, multiply secondary DC rank weights by the learned multipliers below (offline tuning hook).",
    )
    smart_network_learned_fee_weight_multiplier: float = Field(
        1.0,
        ge=0.0,
        le=10.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_LEARNED_FEE_WEIGHT_MULTIPLIER",
            "smart_network_learned_fee_weight_multiplier",
        ),
        description="Applied to contract-fee proxy weight in secondary ranking when learned hook is enabled.",
    )
    smart_network_learned_last_mile_weight_multiplier: float = Field(
        1.0,
        ge=0.0,
        le=10.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_LEARNED_LAST_MILE_WEIGHT_MULTIPLIER",
            "smart_network_learned_last_mile_weight_multiplier",
        ),
        description="Applied to demand-weighted mock last-mile weight in secondary ranking when learned hook is enabled.",
    )
    smart_network_emit_catalog_velocity_tercile_rollups: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SMART_NETWORK_EMIT_CATALOG_VELOCITY_TERCILE_ROLLUPS",
            "smart_network_emit_catalog_velocity_tercile_rollups",
        ),
        description="Attach high/mid/low velocity tercile demand rollups to warehouse network recommendation metadata.",
    )
    planning_default_target_days_cover: float = Field(
        75.0,
        validation_alias=AliasChoices(
            "PLANNING_DEFAULT_TARGET_DAYS_COVER",
            "planning_default_target_days_cover",
        ),
        ge=1.0,
        le=365.0,
        description="Default ~60–90d stocking target for placement summaries and allocation baselines (units = daily × days).",
    )
    planning_manual_monthly_units_override_minimum: int = Field(
        150,
        validation_alias=AliasChoices(
            "PLANNING_MANUAL_MONTHLY_UNITS_OVERRIDE_MINIMUM",
            "planning_manual_monthly_units_override_minimum",
        ),
        ge=0,
        le=1_000_000,
        description=(
            "Manual planning_monthly_units_override_by_sku must be >= this value (units/mo) when sent; "
            "omit override to use Keepa + buy-box modeled velocity. Set 0 to disable the floor (not recommended)."
        ),
    )
    network_placement_adjustment_max_days_cover: float = Field(
        90.0,
        validation_alias=AliasChoices(
            "NETWORK_PLACEMENT_ADJUSTMENT_MAX_DAYS_COVER",
            "network_placement_adjustment_max_days_cover",
        ),
        ge=30.0,
        le=365.0,
        description="Cap extended cover in network_placement_adjustment (MOQ batch sizing) so planning does not imply multi-month buys.",
    )
    network_consolidated_linehaul_cost_multiplier: float = Field(
        0.62,
        validation_alias=AliasChoices(
            "NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER",
            "network_consolidated_linehaul_cost_multiplier",
        ),
        ge=0.05,
        le=1.0,
        description=(
            "Scales mock LTL/FTL linehaul USD on the consolidated (hub→receive→parcel) path only; "
            "direct multi-origin parcel is unchanged. <1.0 reflects contracted lanes vs conservative mock."
        ),
    )
    seller_mixed_pallet_linehaul_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SELLER_MIXED_PALLET_LINEHAUL_ENABLED",
            "seller_mixed_pallet_linehaul_enabled",
        ),
        description=(
            "When true, order-planning integrated compare uses mixed-pallet fraction linehaul on the consolidated leg "
            "(HTTP /scenarios/compare-v2-integrated unchanged; default false there)."
        ),
    )
    seller_planning_ltl_engine_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_ENGINE_ENABLED",
            "seller_planning_ltl_engine_enabled",
        ),
        description=(
            "When true and TMS Postgres (TMS_DB_*) is available, seller consolidated linehaul uses "
            "quote_ltl_engine (sv_lanes/sv_zones) instead of mixed-pallet mock; falls back to mock if no quote."
        ),
    )
    seller_planning_ltl_engine_require_tms_db: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_ENGINE_REQUIRE_TMS_DB",
            "seller_planning_ltl_engine_require_tms_db",
        ),
        description="If true, skip LTL engine when no WMS/TMS intelligence DB URL can be built from env.",
    )
    seller_planning_ltl_engine_fallback_to_mock: bool = Field(
        True,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_ENGINE_FALLBACK_TO_MOCK",
            "seller_planning_ltl_engine_fallback_to_mock",
        ),
        description="When the LTL engine returns no_quote, use mixed-pallet mock linehaul (same as before).",
    )
    seller_planning_ltl_tenant_id: str = Field(
        "__default__",
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_TENANT_ID",
            "seller_planning_ltl_tenant_id",
        ),
        description="Tenant id passed to quote_ltl_engine for seller optimization (matches sv_* scope).",
    )
    seller_planning_ltl_source_system_id: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_SOURCE_SYSTEM_ID",
            "seller_planning_ltl_source_system_id",
        ),
    )
    seller_planning_ltl_provider_id: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_PROVIDER_ID",
            "seller_planning_ltl_provider_id",
        ),
    )
    seller_planning_ltl_pricing_version_id: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_PRICING_VERSION_ID",
            "seller_planning_ltl_pricing_version_id",
        ),
    )
    seller_planning_ltl_expand_all_scopes: bool = Field(
        False,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_EXPAND_ALL_SCOPES",
            "seller_planning_ltl_expand_all_scopes",
        ),
        description="When true, quote_ltl_engine evaluates all provider/source/pricing tuples for the tenant.",
    )
    seller_planning_ltl_allow_cross_provider_stitch: bool = Field(
        False,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_LTL_ALLOW_CROSS_PROVIDER_STITCH",
            "seller_planning_ltl_allow_cross_provider_stitch",
        ),
    )
    seller_planning_cube_packaging_buffer_multiplier: float = Field(
        1.15,
        validation_alias=AliasChoices(
            "SELLER_PLANNING_CUBE_PACKAGING_BUFFER_MULTIPLIER",
            "seller_planning_cube_packaging_buffer_multiplier",
        ),
        ge=1.0,
        le=2.0,
        description=(
            "Multiply product cube (L×W×H×qty) for consolidated linehaul and pallet-slot quoting only. "
            "Default 1.15 = 15% buffer for box, dunnage, and handling slack. Direct parcel legs still use raw dims."
        ),
    )
    us_state_demand_forecast_id: str = Field(
        "2026_retail_ecommerce_population_parcel_blend_v1",
        validation_alias=AliasChoices(
            "US_STATE_DEMAND_FORECAST_ID",
            "us_state_demand_forecast_id",
        ),
        description="Label for default contiguous-US state demand shares (planning prior)",
    )
    us_state_demand_forecast_effective_as_of: str = Field(
        "2026-01-01",
        validation_alias=AliasChoices(
            "US_STATE_DEMAND_FORECAST_EFFECTIVE_AS_OF",
            "us_state_demand_forecast_effective_as_of",
        ),
        description="As-of date for static state share table (no in-year seasonality in-model)",
    )
    us_state_demand_forecast_refresh_note: str = Field(
        "Annual or on deploy; replace table in us_state_demand_share.py or future config-driven loader.",
        validation_alias=AliasChoices(
            "US_STATE_DEMAND_FORECAST_REFRESH_NOTE",
            "us_state_demand_forecast_refresh_note",
        ),
        description="How operators refresh the prior (documentation only unless loader is added)",
    )
    economics_default_inbound_receiving_per_unit_usd: float = Field(
        0.35,
        validation_alias=AliasChoices(
            "ECONOMICS_DEFAULT_INBOUND_RECEIVING_PER_UNIT_USD",
            "economics_default_inbound_receiving_per_unit_usd",
        ),
        description="Fallback receiving $/unit when warehouse nodes omit inbound_receiving_per_unit_usd",
    )
    economics_default_outbound_handling_per_unit_usd: float = Field(
        0.12,
        validation_alias=AliasChoices(
            "ECONOMICS_DEFAULT_OUTBOUND_HANDLING_PER_UNIT_USD",
            "economics_default_outbound_handling_per_unit_usd",
        ),
        description="Fallback outbound handling $/unit when warehouse nodes omit outbound_handling_per_unit_usd",
    )
    economics_default_storage_per_unit_month_usd: float = Field(
        0.02,
        validation_alias=AliasChoices(
            "ECONOMICS_DEFAULT_STORAGE_PER_UNIT_MONTH_USD",
            "economics_default_storage_per_unit_month_usd",
        ),
        description="Fallback storage $/unit/month when warehouse nodes omit storage_per_unit_month_usd",
    )
    economics_inbound_flow_model: str = Field(
        "hub_spoke_rate_card_v1",
        validation_alias=AliasChoices(
            "ECONOMICS_INBOUND_FLOW_MODEL",
            "economics_inbound_flow_model",
        ),
        description="Item intelligence landed cost: hub_spoke_rate_card_v1 (default) | blended_legacy",
    )
    economics_default_pricing_profile_id: str = Field(
        "profile_nj_v1",
        validation_alias=AliasChoices(
            "ECONOMICS_DEFAULT_PRICING_PROFILE_ID",
            "economics_default_pricing_profile_id",
        ),
        description="Mock rate card profile when warehouse nodes omit pricing_profile_id (hub-spoke model)",
    )
    wms_pricing_threshold_usd: float = Field(
        1000.0,
        validation_alias=AliasChoices("WMS_PRICING_THRESHOLD_USD", "wms_pricing_threshold_usd"),
        description="Threshold branch for pricing mode selection (>= threshold optimize storage mode, below threshold force regular).",
    )
    wms_under_threshold_mode: str = Field(
        "per_unit_per_order_only",
        validation_alias=AliasChoices("WMS_UNDER_THRESHOLD_MODE", "wms_under_threshold_mode"),
        description="Under-threshold pricing mode policy.",
    )
    fba_immediate_send_forecast_days: int = Field(
        30,
        ge=1,
        le=365,
        validation_alias=AliasChoices("FBA_IMMEDIATE_SEND_FORECAST_DAYS", "fba_immediate_send_forecast_days"),
        description="Days used for immediate-send FBA plan before overflow storage applies.",
    )
    wms_storage_default_custom_days: int = Field(
        30,
        ge=1,
        le=365,
        validation_alias=AliasChoices("WMS_STORAGE_DEFAULT_CUSTOM_DAYS", "wms_storage_default_custom_days"),
        description="Default billing cycle days when storage cycle is custom_days and explicit days are missing.",
    )
    wms_constraint_dock_mismatch_hard: bool = Field(
        False,
        validation_alias=AliasChoices("WMS_CONSTRAINT_DOCK_MISMATCH_HARD", "wms_constraint_dock_mismatch_hard"),
        description="When true, dock mismatch becomes a hard forbidden arc; otherwise emits penalty.",
    )
    wms_constraint_call_ahead_hard: bool = Field(
        False,
        validation_alias=AliasChoices("WMS_CONSTRAINT_CALL_AHEAD_HARD", "wms_constraint_call_ahead_hard"),
        description="When true, call-ahead mismatch becomes a hard forbidden arc; otherwise emits penalty.",
    )
    item_intelligence_cuopt_overview_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "ITEM_INTELLIGENCE_CUOPT_OVERVIEW_ENABLED",
            "item_intelligence_cuopt_overview_enabled",
        ),
        description="Attach multi_dc_placement_tri_modal (original input + baseline + NVIDIA cuOpt) to item intelligence",
    )
    item_intelligence_nvidia_cuopt_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "ITEM_INTELLIGENCE_NVIDIA_CUOPT_ENABLED",
            "item_intelligence_nvidia_cuopt_enabled",
        ),
        description="When True and overview enabled, attempt NVIDIA cuOpt NIM/cloud layer (else skipped with reason)",
    )
    amazon_fee_model_2026_version: str = Field(
        "amazon_fee_model_2026_v1",
        validation_alias=AliasChoices(
            "AMAZON_FEE_MODEL_2026_VERSION",
            "amazon_fee_model_2026_version",
        ),
        description="Version label for order-financial 2025 to 2026 inflation artifact",
    )
    amazon_fba_fee_increase_effective_date: str = Field(
        "2026-01-15",
        validation_alias=AliasChoices(
            "AMAZON_FBA_FEE_INCREASE_EFFECTIVE_DATE",
            "amazon_fba_fee_increase_effective_date",
        ),
    )
    amazon_marketplace_fee_schedule_effective_date: str = Field(
        "2026-01-01",
        validation_alias=AliasChoices(
            "AMAZON_MARKETPLACE_FEE_SCHEDULE_EFFECTIVE_DATE",
            "amazon_marketplace_fee_schedule_effective_date",
        ),
        description=(
            "Orders on/after this date are treated as on the current public fee schedule; "
            "earlier orders get CSV-period alignment for the Current planning column."
        ),
    )
    amazon_pre_effective_referral_multiplier_vs_modeled: float = Field(
        0.992,
        validation_alias=AliasChoices(
            "AMAZON_PRE_EFFECTIVE_REFERRAL_MULTIPLIER_VS_MODELED",
            "amazon_pre_effective_referral_multiplier_vs_modeled",
        ),
        description=(
            "Heuristic multiplier on modeled referral for orders before amazon_marketplace_fee_schedule_effective_date "
            "when 2025 referral tables are not loaded (tune 0.98–1.0)."
        ),
    )
    amazon_fba_prep_services_us_end_date: str = Field(
        "2026-01-01",
        validation_alias=AliasChoices(
            "AMAZON_FBA_PREP_SERVICES_US_END_DATE",
            "amazon_fba_prep_services_us_end_date",
        ),
    )
    amazon_payout_dd7_effective_date: str = Field(
        "2026-03-12",
        validation_alias=AliasChoices(
            "AMAZON_PAYOUT_DD7_EFFECTIVE_DATE",
            "amazon_payout_dd7_effective_date",
        ),
    )
    amazon_fba_default_size_tier_assumption: str = Field(
        "small_standard",
        validation_alias=AliasChoices(
            "AMAZON_FBA_DEFAULT_SIZE_TIER_ASSUMPTION",
            "amazon_fba_default_size_tier_assumption",
        ),
        description="When CSV has no dimensions: small_standard or large_standard",
    )
    amazon_inbound_placement_delta_standard_usd: float = Field(
        0.05,
        validation_alias=AliasChoices(
            "AMAZON_INBOUND_PLACEMENT_DELTA_STANDARD_USD",
            "amazon_inbound_placement_delta_standard_usd",
        ),
    )
    amazon_inbound_placement_delta_large_bulky_usd: float = Field(
        0.27,
        validation_alias=AliasChoices(
            "AMAZON_INBOUND_PLACEMENT_DELTA_LARGE_BULKY_USD",
            "amazon_inbound_placement_delta_large_bulky_usd",
        ),
    )
    amazon_mcf_avg_increase_usd_per_unit: float = Field(
        0.30,
        validation_alias=AliasChoices(
            "AMAZON_MCF_AVG_INCREASE_USD_PER_UNIT",
            "amazon_mcf_avg_increase_usd_per_unit",
        ),
    )
    amazon_buy_with_prime_fulfillment_avg_increase_usd: float = Field(
        0.24,
        validation_alias=AliasChoices(
            "AMAZON_BUY_WITH_PRIME_FULFILLMENT_AVG_INCREASE_USD",
            "amazon_buy_with_prime_fulfillment_avg_increase_usd",
        ),
    )
    amazon_referral_fee_model_version: str = Field(
        "amazon_referral_fees_2026_v1",
        validation_alias=AliasChoices(
            "AMAZON_REFERRAL_FEE_MODEL_VERSION",
            "amazon_referral_fee_model_version",
        ),
    )
    amazon_fee_audit_grade: bool = Field(
        True,
        validation_alias=AliasChoices(
            "AMAZON_FEE_AUDIT_GRADE",
            "amazon_fee_audit_grade",
        ),
        description="Apply US referral minimums and emit FBA fulfillment audit estimates (verify on Seller Central).",
    )
    amazon_referral_minimum_usd_per_item: float = Field(
        0.30,
        validation_alias=AliasChoices(
            "AMAZON_REFERRAL_MINIMUM_USD_PER_ITEM",
            "amazon_referral_minimum_usd_per_item",
        ),
        description="Typical US referral fee floor per unit (exemptions in amazon_fees_audit_us).",
    )
    amazon_fba_audit_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "AMAZON_FBA_AUDIT_ENABLED",
            "amazon_fba_audit_enabled",
        ),
    )
    amazon_fba_audit_default_shipping_weight_lb: float = Field(
        0.5,
        validation_alias=AliasChoices(
            "AMAZON_FBA_AUDIT_DEFAULT_SHIPPING_WEIGHT_LB",
            "amazon_fba_audit_default_shipping_weight_lb",
        ),
        description="When CSV has no package weight: assumed lb/unit for FBA audit estimate.",
    )
    amazon_fba_audit_default_size_tier: str = Field(
        "small_standard",
        validation_alias=AliasChoices(
            "AMAZON_FBA_AUDIT_DEFAULT_SIZE_TIER",
            "amazon_fba_audit_default_size_tier",
        ),
        description="When shipment has no dimensions: tier hint (small_standard | large_standard).",
    )
    amazon_fba_audit_dimensional_divisor: float = Field(
        139.0,
        validation_alias=AliasChoices(
            "AMAZON_FBA_AUDIT_DIMENSIONAL_DIVISOR",
            "amazon_fba_audit_dimensional_divisor",
        ),
    )
    order_financial_enrich_package_from_catalog: bool = Field(
        True,
        validation_alias=AliasChoices(
            "ORDER_FINANCIAL_ENRICH_PACKAGE_FROM_CATALOG",
            "order_financial_enrich_package_from_catalog",
        ),
        description="When CSV omits package weight/dims, fill from SP-API catalog (cache/live) then Keepa per ASIN.",
    )
    item_intelligence_enrich_package_from_catalog: bool = Field(
        True,
        validation_alias=AliasChoices(
            "ITEM_INTELLIGENCE_ENRICH_PACKAGE_FROM_CATALOG",
            "item_intelligence_enrich_package_from_catalog",
        ),
        description="Item intelligence / PRO: before allocation, fill missing catalog weight/dims from SP-API then Keepa.",
    )
    item_intelligence_persist_catalog_package_hints: bool = Field(
        True,
        validation_alias=AliasChoices(
            "ITEM_INTELLIGENCE_PERSIST_CATALOG_PACKAGE_HINTS",
            "item_intelligence_persist_catalog_package_hints",
        ),
        description="When automatic package hints fill gaps, write back to cortex_sku_catalog (Mongo or SQL).",
    )
    placement_one_warehouse_per_contiguous_state: bool = Field(
        True,
        validation_alias=AliasChoices(
            "PLACEMENT_ONE_WAREHOUSE_PER_CONTIGUOUS_STATE",
            "placement_one_warehouse_per_contiguous_state",
        ),
        description="Mock placement / seller rate-shop node lists: at most one warehouse per contiguous-US state (ZIP3→state).",
    )
    amazon_seller_professional_plan: bool = Field(
        True,
        validation_alias=AliasChoices(
            "AMAZON_SELLER_PROFESSIONAL_PLAN",
            "amazon_seller_professional_plan",
        ),
        description="If False, add Individual $0.99/item to modeled referral fees",
    )
    spapi_refresh_token: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_REFRESH_TOKEN",
            "AMAZON_LWA_REFRESH_TOKEN",
            "AMAZON_SPAPI_REFRESH_TOKEN",
            "spapi_refresh_token",
        ),
    )
    spapi_client_id: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_CLIENT_ID",
            "LWA_CLIENT_ID",
            "AMAZON_LWA_CLIENT_ID",
            "spapi_client_id",
        ),
    )
    spapi_client_secret: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_CLIENT_SECRET",
            "LWA_CLIENT_SECRET",
            "AMAZON_LWA_CLIENT_SECRET",
            "spapi_client_secret",
        ),
    )
    spapi_aws_access_key_id: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_AWS_ACCESS_KEY_ID",
            "AWS_ACCESS_KEY_ID",
            "AMAZON_SPAPI_AWS_ACCESS_KEY_ID",
            "spapi_aws_access_key_id",
        ),
    )
    spapi_aws_secret_access_key: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_AWS_SECRET_ACCESS_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AMAZON_SPAPI_AWS_SECRET_ACCESS_KEY",
            "spapi_aws_secret_access_key",
        ),
    )
    spapi_aws_session_token: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_AWS_SESSION_TOKEN",
            "AWS_SESSION_TOKEN",
            "AMAZON_SPAPI_AWS_SESSION_TOKEN",
            "spapi_aws_session_token",
        ),
    )
    spapi_role_arn: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "SPAPI_ROLE_ARN",
            "AMAZON_SPAPI_ROLE_ARN",
            "spapi_role_arn",
        ),
        description="If set, AssumeRole before signing SP-API requests",
    )
    amazon_region: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "AMAZON_REGION",
            "amazon_region",
            "AMAZON_SPAPI_REGION_CODE",
        ),
        description="Selling Partner region hint: na, eu, fe (sets endpoint/region if not overridden)",
    )
    spapi_region: str = Field(
        "us-east-1",
        validation_alias=AliasChoices("SPAPI_REGION", "spapi_region"),
    )
    spapi_endpoint_host: str = Field(
        "sellingpartnerapi-na.amazon.com",
        validation_alias=AliasChoices("SPAPI_ENDPOINT_HOST", "spapi_endpoint_host"),
    )
    spapi_marketplace_id: str = Field(
        "ATVPDKIKX0DER",
        validation_alias=AliasChoices("SPAPI_MARKETPLACE_ID", "spapi_marketplace_id"),
    )
    spapi_catalog_ttl_days: int = Field(
        30,
        validation_alias=AliasChoices("SPAPI_CATALOG_TTL_DAYS", "spapi_catalog_ttl_days"),
    )
    rate_limit_integrations: int = Field(
        30,
        validation_alias=AliasChoices("RATE_LIMIT_INTEGRATIONS", "rate_limit_integrations"),
        description="Max requests per minute per IP for integration routes (0=disabled)",
    )
    rate_shop_cache_ttl_days: int = Field(
        30,
        validation_alias=AliasChoices("RATE_SHOP_CACHE_TTL_DAYS", "rate_shop_cache_ttl_days"),
        description="Reuse cached parcel quotes for same physical bucket + lane (days)",
    )

    taxjar_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("TAXJAR_API_KEY", "taxjar_api_key"),
        description="TaxJar API token for GET /v2/summary_rates (monthly nationwide sync)",
    )
    tax_sync_mock_mode: bool = Field(
        False,
        validation_alias=AliasChoices("TAX_SYNC_MOCK_MODE", "tax_sync_mock_mode"),
        description="When true, /integrations/tax/sync uses static US state stubs (no TaxJar call)",
    )

    # Google Address Validation API (preferred when set — same Maps API key as other Google Maps products)
    google_maps_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "GOOGLE_MAPS_API_KEY",
            "google_maps_api_key",
            "GOOGLE_ADDRESS_VALIDATION_API_KEY",
        ),
    )
    google_address_validation_usps_cass: bool = Field(
        True,
        validation_alias=AliasChoices(
            "GOOGLE_ADDRESS_VALIDATION_USPS_CASS",
            "google_address_validation_usps_cass",
        ),
    )

    address_validation_url: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "ADDRESS_VALIDATION_URL", "address_validation_url", "SMARTY_AUTH_URL"
        ),
    )
    address_validation_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "ADDRESS_VALIDATION_API_KEY", "address_validation_api_key", "SMARTY_AUTH_ID"
        ),
    )

    nvidia_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("NVIDIA_API_KEY", "nvidia_api_key"),
        description=(
            "Bearer for NVIDIA managed cuOpt cloud (optimize.api.nvidia.com) AND for NIM "
            "LLM chat completions (nim_post_chat_completions). Same key covers both surfaces."
        ),
    )
    nim_base_url: str = Field(
        "https://integrate.api.nvidia.com/v1",
        validation_alias=AliasChoices("NIM_BASE_URL", "nim_base_url"),
        description=(
            "Base URL for NVIDIA NIM chat completions API. nim_post_chat_completions appends "
            "/chat/completions to this. Default targets NVIDIA-hosted NIM (integrate.api.nvidia.com)."
        ),
    )
    nim_allow_unauth_local: bool = Field(
        True,
        validation_alias=AliasChoices("NIM_ALLOW_UNAUTH_LOCAL", "nim_allow_unauth_local"),
        description=(
            "Allow chat/completions without NVIDIA_API_KEY when NIM_BASE_URL points to a local endpoint "
            "(localhost/127.0.0.1/::1). Intended for self-hosted NIM on EC2."
        ),
    )
    nim_model: str = Field(
        "meta/llama-3.1-70b-instruct",
        validation_alias=AliasChoices("NIM_MODEL", "nim_model"),
        description=(
            "Model identifier for NIM chat completions (e.g. meta/llama-3.1-70b-instruct, "
            "mistralai/mixtral-8x22b-instruct-v0.1). Used by MAIW conversational chat + audit narrative."
        ),
    )
    nim_csv_mapping_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("NIM_CSV_MAPPING_ENABLED", "nim_csv_mapping_enabled"),
        description="Legacy flag; CSV column inference uses heuristics only (no LLM).",
    )

    ai_observability_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("AI_OBSERVABILITY_ENABLED", "ai_observability_enabled"),
        description="When true, observability hooks may persist AiInvocation rows where applicable.",
    )
    ai_observability_preview_max_chars: int = Field(
        0,
        ge=0,
        le=8192,
        validation_alias=AliasChoices(
            "AI_OBSERVABILITY_PREVIEW_MAX_CHARS",
            "ai_observability_preview_max_chars",
        ),
        description="When >0, store truncated prompt/response previews on AI invocations.",
    )
    observability_audit_write_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "OBSERVABILITY_AUDIT_WRITE_ENABLED",
            "observability_audit_write_enabled",
        ),
        description="Enable persistence of run_module_audits and intelligence_jobs instrumentation rows.",
    )
    navigator_observability_ui_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "NAVIGATOR_OBSERVABILITY_UI_ENABLED",
            "navigator_observability_ui_enabled",
        ),
        description="Enable observability/JOBS collections and API payloads used by Intelligence Navigator UI.",
    )

    cuopt_nim_url: str | None = Field(
        None,
        validation_alias=AliasChoices("CUOPT_NIM_URL", "cuopt_nim_url"),
    )
    cuopt_self_hosted_url: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "CUOPT_SELF_HOSTED_URL",
            "cuopt_self_hosted_url",
        ),
        description=(
            "Base URL for self-hosted cuOpt REST server (e.g. http://127.0.0.1:8787). "
            "Uses POST /cuopt/request and GET /cuopt/solution/{reqId}. Takes precedence over "
            "CUOPT_NIM_URL /optimize when set."
        ),
    )
    cuopt_matrix_lane_cost_weight: float = Field(
        0.35,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "CUOPT_MATRIX_LANE_COST_WEIGHT",
            "cuopt_matrix_lane_cost_weight",
        ),
        description="Scale haversine cost matrix by lane cost_per_lb when building multi-DC cuOpt jobs (0=geo only).",
    )
    cuopt_inform_allocation_weights: bool = Field(
        True,
        validation_alias=AliasChoices(
            "CUOPT_INFORM_ALLOCATION_WEIGHTS",
            "cuopt_inform_allocation_weights",
        ),
        description=(
            "When true, after seller / PRO tri-modal cuOpt completes, compute cuopt_allocation_intelligence "
            "(share nudges). intelligence_run also attaches allocation_cuopt_counterfactual when applicable."
        ),
    )
    cuopt_allocation_min_csv_confidence_for_full_nudge: float | None = Field(
        65.0,
        validation_alias=AliasChoices(
            "CUOPT_ALLOCATION_MIN_CSV_CONFIDENCE_FOR_FULL_NUDGE",
            "cuopt_allocation_min_csv_confidence_for_full_nudge",
        ),
        description=(
            "When order-financial planning passes csv_intelligence_confidence_score below this threshold, "
            "cap nudges at cuopt_allocation_nudge_max_pct_low_confidence. None disables the gate."
        ),
    )
    cuopt_allocation_nudge_max_pct_low_confidence: float = Field(
        1.0,
        ge=0.1,
        le=10.0,
        validation_alias=AliasChoices(
            "CUOPT_ALLOCATION_NUDGE_MAX_PCT_LOW_CONFIDENCE",
            "cuopt_allocation_nudge_max_pct_low_confidence",
        ),
        description="Max ±pp nudge per warehouse when CSV confidence is below the full-nudge threshold.",
    )
    cuopt_allocation_nudge_max_pct: float = Field(
        2.5,
        ge=0.1,
        le=15.0,
        validation_alias=AliasChoices(
            "CUOPT_ALLOCATION_NUDGE_MAX_PCT",
            "cuopt_allocation_nudge_max_pct",
        ),
        description="Max ± percentage-point nudge per warehouse when deriving cuOpt-informed share adjustments.",
    )
    cuopt_allocation_cost_refit_blend: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "CUOPT_ALLOCATION_COST_REFIT_BLEND",
            "cuopt_allocation_cost_refit_blend",
        ),
        description=(
            "Blend cuOpt visit-order nudges with mock-parcel cost-rank nudges: 0 = visit order only, 1 = cost rank only."
        ),
    )
    cuopt_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("CUOPT_API_KEY", "cuopt_api_key"),
    )

    local_nim_url: str | None = Field(
        None,
        validation_alias=AliasChoices("LOCAL_NIM_URL", "local_nim_url"),
        description=(
            "Base URL of self-hosted NVIDIA NIM container (e.g. http://localhost:8000). "
            "When set, warehouse audit four-track uses the local NIM for narrative overlays "
            "instead of hosted NVIDIA Cloud. Required for on-prem privacy."
        ),
    )
    local_nim_model: str | None = Field(
        None,
        validation_alias=AliasChoices("LOCAL_NIM_MODEL", "local_nim_model"),
        description="Model tag the self-hosted NIM container serves (e.g. meta/llama-3.1-70b-instruct).",
    )
    local_cuopt_url: str | None = Field(
        None,
        validation_alias=AliasChoices("LOCAL_CUOPT_URL", "local_cuopt_url"),
        description=(
            "Base URL of self-hosted NVIDIA cuOpt server (e.g. http://localhost:5000). "
            "When set, warehouse optimization calls route here instead of hosted NVIDIA Cloud."
        ),
    )
    local_nim_timeout_sec: float = Field(
        12.0,
        validation_alias=AliasChoices("LOCAL_NIM_TIMEOUT_SEC", "local_nim_timeout_sec"),
        description="Timeout for local NIM calls. Four-track falls back to deterministic on timeout.",
    )

    maiw_force_internal_only: bool = Field(
        False,
        validation_alias=AliasChoices("MAIW_FORCE_INTERNAL_ONLY", "maiw_force_internal_only"),
        description="When true, Warehouse Intelligence (/v1 pick-pathing, labor, etc.) skips NVIDIA enrichment (nvidia variants return skipped).",
    )

    multi_dc_cuopt_cloud_enabled: bool = Field(
        False,
        validation_alias=AliasChoices(
            "MULTI_DC_CUOPT_CLOUD_ENABLED",
            "multi_dc_cuopt_cloud_enabled",
        ),
        description=(
            "When true and CUOPT_API_KEY or NVIDIA_API_KEY is set, POST /assessment/multi-dc-preview "
            "calls optimize.api.nvidia.com (same flow as TMS cuOpt cloud), not CUOPT_NIM_URL."
        ),
    )

    tms_cuopt_sequencing: bool = Field(
        False,
        validation_alias=AliasChoices("TMS_CUOPT_SEQUENCING", "tms_cuopt_sequencing"),
        description="When true and CUOPT_NIM_URL is set, try NIM /tms/vrp for pickup/delivery order before heuristics.",
    )

    nvidia_cuopt_cloud_invoke_url: str = Field(
        "https://optimize.api.nvidia.com/v1/nvidia/cuopt",
        validation_alias=AliasChoices(
            "NVIDIA_CUOPT_CLOUD_INVOKE_URL",
            "nvidia_cuopt_cloud_invoke_url",
        ),
        description="NVIDIA managed cuOpt invoke URL (Optimized Routing).",
    )
    nvidia_cuopt_cloud_status_url_prefix: str = Field(
        "https://optimize.api.nvidia.com/v1/status/",
        validation_alias=AliasChoices(
            "NVIDIA_CUOPT_CLOUD_STATUS_URL_PREFIX",
            "nvidia_cuopt_cloud_status_url_prefix",
        ),
        description="Prefix for GET status polling; request id is appended.",
    )
    nvidia_cuopt_cloud_poll_interval_seconds: float = Field(
        1.0,
        ge=0.05,
        le=30.0,
        validation_alias=AliasChoices(
            "NVIDIA_CUOPT_CLOUD_POLL_INTERVAL_SECONDS",
            "nvidia_cuopt_cloud_poll_interval_seconds",
        ),
    )
    nvidia_cuopt_cloud_poll_timeout_seconds: float = Field(
        300.0,
        ge=5.0,
        le=3600.0,
        validation_alias=AliasChoices(
            "NVIDIA_CUOPT_CLOUD_POLL_TIMEOUT_SECONDS",
            "nvidia_cuopt_cloud_poll_timeout_seconds",
        ),
    )

    tms_nvidia_cuopt_cloud_enabled: bool = Field(
        False,
        validation_alias=AliasChoices(
            "TMS_NVIDIA_CUOPT_CLOUD_ENABLED",
            "tms_nvidia_cuopt_cloud_enabled",
        ),
        description="When true, propose_routes may call NVIDIA cuOpt cloud and append an alternative route_variants entry.",
    )
    tms_cuopt_use_self_hosted: bool = Field(
        True,
        validation_alias=AliasChoices(
            "TMS_CUOPT_USE_SELF_HOSTED",
            "tms_cuopt_use_self_hosted",
        ),
        description=(
            "When true and CUOPT_SELF_HOSTED_URL is set, TMS propose_routes uses self-hosted cuOpt REST "
            "before NVIDIA managed cloud."
        ),
    )
    tms_nvidia_cuopt_max_nodes: int = Field(
        25,
        ge=3,
        le=25,
        validation_alias=AliasChoices(
            "TMS_NVIDIA_CUOPT_MAX_NODES",
            "tms_nvidia_cuopt_max_nodes",
        ),
        description="Max matrix nodes when building cuOpt job from a Cortex route.",
    )
    tms_nvidia_cuopt_time_limit_seconds: int = Field(
        30,
        ge=1,
        le=120,
        validation_alias=AliasChoices(
            "TMS_NVIDIA_CUOPT_TIME_LIMIT_SECONDS",
            "tms_nvidia_cuopt_time_limit_seconds",
        ),
    )
    cuopt_storage_monthly_usd_to_matrix: float = Field(
        0.012,
        ge=0.0,
        validation_alias=AliasChoices(
            "CUOPT_STORAGE_MONTHLY_USD_TO_MATRIX",
            "cuopt_storage_monthly_usd_to_matrix",
        ),
        description="Scale storage $/month proxy into cost-matrix additive (destination column).",
    )
    cuopt_inbound_monthly_usd_to_matrix: float = Field(
        0.015,
        ge=0.0,
        validation_alias=AliasChoices(
            "CUOPT_INBOUND_MONTHLY_USD_TO_MATRIX",
            "cuopt_inbound_monthly_usd_to_matrix",
        ),
        description="Scale inbound receive $/month proxy into matrix (destination column).",
    )
    cuopt_physical_cube_arc_factor: float = Field(
        0.00025,
        ge=0.0,
        validation_alias=AliasChoices(
            "CUOPT_PHYSICAL_CUBE_ARC_FACTOR",
            "cuopt_physical_cube_arc_factor",
        ),
        description="Off-diagonal *= 1+min(0.25, max_network_cube_cuft×factor) for dimensional stress.",
    )
    cuopt_dual_capacity_cube_dimension_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "CUOPT_DUAL_CAPACITY_CUBE_DIMENSION_ENABLED",
            "cuopt_dual_capacity_cube_dimension_enabled",
        ),
        description="Second demand/capacity dimension uses allocated monthly cuft (cube) vs units.",
    )
    cuopt_task_service_time_seconds_base: int = Field(
        0,
        ge=0,
        le=3600,
        validation_alias=AliasChoices(
            "CUOPT_TASK_SERVICE_TIME_SECONDS_BASE",
            "cuopt_task_service_time_seconds_base",
        ),
    )
    cuopt_task_service_time_seconds_per_demand_unit: float = Field(
        0.4,
        ge=0.0,
        le=60.0,
        validation_alias=AliasChoices(
            "CUOPT_TASK_SERVICE_TIME_SECONDS_PER_DEMAND_UNIT",
            "cuopt_task_service_time_seconds_per_demand_unit",
        ),
    )
    cuopt_forbidden_arc_cost: float = Field(
        1e9,
        ge=1e6,
        le=1e12,
        validation_alias=AliasChoices("CUOPT_FORBIDDEN_ARC_COST", "cuopt_forbidden_arc_cost"),
    )
    cuopt_linehaul_monthly_usd_to_matrix: float = Field(
        0.018,
        ge=0.0,
        validation_alias=AliasChoices(
            "CUOPT_LINEHAUL_MONTHLY_USD_TO_MATRIX",
            "cuopt_linehaul_monthly_usd_to_matrix",
        ),
        description="Monthly modeled linehaul $ on a leg → additive matrix cost on that directed arc.",
    )
    cuopt_sensitivity_parcel_pct: float = Field(
        10.0,
        ge=0.0,
        le=50.0,
        validation_alias=AliasChoices("CUOPT_SENSITIVITY_PARCEL_PCT", "cuopt_sensitivity_parcel_pct"),
        description="±% for client-side parcel proxy sensitivity rows (no extra NVIDIA HTTP).",
    )
    tms_nvidia_cuopt_poll_cap_seconds: float = Field(
        120.0,
        ge=10.0,
        le=600.0,
        validation_alias=AliasChoices(
            "TMS_NVIDIA_CUOPT_POLL_CAP_SECONDS",
            "tms_nvidia_cuopt_poll_cap_seconds",
        ),
        description="Cap status polling duration for TMS-triggered cuOpt calls.",
    )
    tms_nim_dispatch_summary_enabled: bool = Field(
        False,
        validation_alias=AliasChoices(
            "TMS_NIM_DISPATCH_SUMMARY_ENABLED",
            "tms_nim_dispatch_summary_enabled",
        ),
        description=(
            "When true, attach a NIM-generated plain-text dispatch summary to propose_routes "
            "responses (read-only narrative over structured facts) using local/hosted NIM runtime."
        ),
    )
    optimization_core_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "OPTIMIZATION_CORE_ENABLED",
            "optimization_core_enabled",
        ),
        description=(
            "When true, TMS / LTL / seller / item-intelligence / scenarios use the shared "
            "unie_cortex.optimization core (pallet/trailer fill, demand contract, cuopt_client, "
            "envelope). Single source of truth for smart, realistic, deterministic outputs."
        ),
    )
    cuopt_solver_seed: int = Field(
        42,
        ge=0,
        le=2_000_000_000,
        validation_alias=AliasChoices("CUOPT_SOLVER_SEED", "cuopt_solver_seed"),
        description=(
            "Seed injected into solver_config for every cuopt_client call. Combined with a "
            "fixed time_limit on a single self-hosted cuOpt instance, this makes solves "
            "reproducible across reruns of the same canonicalized contract."
        ),
    )
    cuopt_solver_time_limit_s: int = Field(
        30,
        ge=1,
        le=600,
        validation_alias=AliasChoices(
            "CUOPT_SOLVER_TIME_LIMIT_S",
            "cuopt_solver_time_limit_s",
        ),
        description="Time limit (seconds) injected into solver_config for every cuopt_client call.",
    )
    cuopt_cache_ttl_seconds: int = Field(
        86_400,
        ge=0,
        le=14 * 86_400,
        validation_alias=AliasChoices(
            "CUOPT_CACHE_TTL_SECONDS",
            "cuopt_cache_ttl_seconds",
        ),
        description=(
            "TTL (seconds) for the in-memory solve cache keyed by canonical contract SHA-256. "
            "Same input contract => byte-identical response within this window."
        ),
    )
    cuopt_cache_backend: str = Field(
        "memory",
        validation_alias=AliasChoices("CUOPT_CACHE_BACKEND", "cuopt_cache_backend"),
        description="Solve cache backend. Currently only 'memory' is implemented; 'postgres' reserved for v2.",
    )
    ltl_fuel_index_baseline_usd_per_gal: float = Field(
        4.00,
        gt=0.0,
        le=20.0,
        validation_alias=AliasChoices(
            "LTL_FUEL_INDEX_BASELINE_USD_PER_GAL",
            "ltl_fuel_index_baseline_usd_per_gal",
        ),
        description=(
            "Baseline diesel $/gal used to scale sv_fuel_rules percentage rates against the live "
            "EIA US weekly diesel index. Multiplier = live_price / baseline. Only fuel rule rows "
            "that opt in via fuel_index_source/fuel_index_enabled are scaled."
        ),
    )
    tms_db_health_cache_ttl_seconds: int = Field(
        600,
        ge=10,
        le=24 * 3600,
        validation_alias=AliasChoices(
            "TMS_DB_HEALTH_CACHE_TTL_SECONDS",
            "tms_db_health_cache_ttl_seconds",
        ),
        description=(
            "TTL (seconds) for the cached TMS Postgres health probe. Default 600 = 10 minutes. "
            "Within the TTL the /v1/integrations/tms/db/health endpoint serves the cached "
            "snapshot; after the TTL the next call runs a fresh SELECT 1."
        ),
    )
    tms_db_health_query_timeout_seconds: float = Field(
        3.0,
        ge=0.5,
        le=30.0,
        validation_alias=AliasChoices(
            "TMS_DB_HEALTH_QUERY_TIMEOUT_SECONDS",
            "tms_db_health_query_timeout_seconds",
        ),
        description="Connect timeout (seconds) for the TMS DB health SELECT 1 probe.",
    )
    road_matrix_provider: str = Field(
        "none",
        validation_alias=AliasChoices("ROAD_MATRIX_PROVIDER", "road_matrix_provider"),
        description="none | osrm_demo | osrm (custom base URL via ROAD_MATRIX_OSRM_BASE_URL)",
    )
    road_matrix_osrm_base_url: str | None = Field(
        None,
        validation_alias=AliasChoices("ROAD_MATRIX_OSRM_BASE_URL", "road_matrix_osrm_base_url"),
    )
    road_matrix_cache_ttl_seconds: int = Field(
        3600,
        ge=60,
        validation_alias=AliasChoices("ROAD_MATRIX_CACHE_TTL_SECONDS", "road_matrix_cache_ttl_seconds"),
    )
    road_matrix_request_timeout_seconds: float = Field(
        8.0,
        ge=1.0,
        le=120.0,
        validation_alias=AliasChoices(
            "ROAD_MATRIX_REQUEST_TIMEOUT_SECONDS", "road_matrix_request_timeout_seconds"
        ),
    )
    ltl_ai_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("LTL_AI_ENABLED", "ltl_ai_enabled"),
        description="Enable NVIDIA-ready LTL route ranking extension (shadow/canary/assisted modes).",
    )
    ltl_ai_mode: str = Field(
        "off",
        validation_alias=AliasChoices("LTL_AI_MODE", "ltl_ai_mode"),
        description="off | shadow | canary | assisted | general",
    )
    ltl_ai_min_confidence_for_override: float = Field(
        0.85,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "LTL_AI_MIN_CONFIDENCE_FOR_OVERRIDE",
            "ltl_ai_min_confidence_for_override",
        ),
    )
    ltl_ai_allowed_tenant_provider_allowlist: str | None = Field(
        None,
        validation_alias=AliasChoices(
            "LTL_AI_ALLOWED_TENANT_PROVIDER_ALLOWLIST",
            "ltl_ai_allowed_tenant_provider_allowlist",
        ),
        description="Optional csv allowlist entries `tenant_id:provider_id` for staged NVIDIA canary.",
    )
    ltl_ai_model_version: str = Field(
        "unconfigured",
        validation_alias=AliasChoices("LTL_AI_MODEL_VERSION", "ltl_ai_model_version"),
    )
    ltl_cuopt_cloud_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("LTL_CUOPT_CLOUD_ENABLED", "ltl_cuopt_cloud_enabled"),
        description="When true, LTL quote ranking attempts NVIDIA cuOpt cloud before deterministic fallback.",
    )
    ltl_cuopt_cloud_timeout_seconds: float = Field(
        90.0,
        ge=5.0,
        le=600.0,
        validation_alias=AliasChoices("LTL_CUOPT_CLOUD_TIMEOUT_SECONDS", "ltl_cuopt_cloud_timeout_seconds"),
        description="Per-quote poll cap for LTL cuOpt cloud ranking calls.",
    )
    ltl_cuopt_objective_cost_weight: float = Field(
        0.4,
        ge=0.0,
        le=5.0,
        validation_alias=AliasChoices("LTL_CUOPT_OBJECTIVE_COST_WEIGHT", "ltl_cuopt_objective_cost_weight"),
    )
    ltl_cuopt_objective_service_weight: float = Field(
        0.25,
        ge=0.0,
        le=5.0,
        validation_alias=AliasChoices(
            "LTL_CUOPT_OBJECTIVE_SERVICE_WEIGHT",
            "ltl_cuopt_objective_service_weight",
        ),
    )
    ltl_cuopt_objective_empty_miles_weight: float = Field(
        0.2,
        ge=0.0,
        le=5.0,
        validation_alias=AliasChoices(
            "LTL_CUOPT_OBJECTIVE_EMPTY_MILES_WEIGHT",
            "ltl_cuopt_objective_empty_miles_weight",
        ),
    )
    ltl_cuopt_objective_consolidation_weight: float = Field(
        0.15,
        ge=0.0,
        le=5.0,
        validation_alias=AliasChoices(
            "LTL_CUOPT_OBJECTIVE_CONSOLIDATION_WEIGHT",
            "ltl_cuopt_objective_consolidation_weight",
        ),
    )
    ltl_dynamic_stitching_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("LTL_DYNAMIC_STITCHING_ENABLED", "ltl_dynamic_stitching_enabled"),
        description="Enable runtime policy to dynamically allow cross-provider stitched candidates.",
    )
    ltl_dynamic_stitching_max_legs: int = Field(
        2,
        ge=1,
        le=3,
        validation_alias=AliasChoices("LTL_DYNAMIC_STITCHING_MAX_LEGS", "ltl_dynamic_stitching_max_legs"),
        description="Maximum composite legs during normal dynamic candidate expansion.",
    )
    ltl_dynamic_allow_three_leg_fallback: bool = Field(
        True,
        validation_alias=AliasChoices(
            "LTL_DYNAMIC_ALLOW_THREE_LEG_FALLBACK",
            "ltl_dynamic_allow_three_leg_fallback",
        ),
        description="When true, engine may attempt 3-leg stitched fallback if 1-2 leg paths are unavailable.",
    )
    ltl_dynamic_congestion_lane_threshold: int = Field(
        25,
        ge=1,
        le=5000,
        validation_alias=AliasChoices(
            "LTL_DYNAMIC_CONGESTION_LANE_THRESHOLD",
            "ltl_dynamic_congestion_lane_threshold",
        ),
        description="Lane-count threshold used as a congestion proxy in dynamic stitching policy.",
    )
    ltl_margin_guardrail_over_cheapest_pct: float = Field(
        0.15,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "LTL_MARGIN_GUARDRAIL_OVER_CHEAPEST_PCT",
            "ltl_margin_guardrail_over_cheapest_pct",
        ),
        description="Maximum allowed premium over cheapest feasible candidate (0.15 = +15%).",
    )
    direct_parcel_network_detour_multiplier: float = Field(
        1.0,
        ge=1.0,
        le=3.0,
        validation_alias=AliasChoices(
            "DIRECT_PARCEL_NETWORK_DETOUR_MULTIPLIER",
            "direct_parcel_network_detour_multiplier",
        ),
        description=(
            "Scales only direct multi-origin mile totals in transport_miles_v1 (geodesic + road proxy); "
            "1.0 = off. Optional heuristic (~1.1–1.25) when direct O→D understates parcel hub circuit miles."
        ),
    )
    green_last_mile_kg_co2e_per_package_mile: float = Field(
        0.00012,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "GREEN_LAST_MILE_KG_CO2E_PER_PACKAGE_MILE",
            "green_last_mile_kg_co2e_per_package_mile",
        ),
        description=(
            "Illustrative kg CO₂e per package-mile for green_logistics_impact last-mile delta (not audited). "
            "Default matches transport_geo.CO2E_KG_PER_PACKAGE_MILE_ILLUSTRATIVE."
        ),
    )
    green_linehaul_kg_co2e_per_mile: float = Field(
        0.00015,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "GREEN_LINEHAUL_KG_CO2E_PER_MILE",
            "green_linehaul_kg_co2e_per_mile",
        ),
        description=(
            "Illustrative kg CO₂e per hub→spoke mile×units month total for green_logistics_impact (not audited)."
        ),
    )

    eia_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("EIA_ENABLED", "eia_enabled"),
        description="When false, EIA routes return skipped and propose_routes omits fuel enrichment.",
    )
    eia_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("EIA_API_KEY", "eia_api_key"),
    )
    eia_cache_ttl_seconds: int = Field(
        86400,
        ge=300,
        validation_alias=AliasChoices("EIA_CACHE_TTL_SECONDS", "eia_cache_ttl_seconds"),
    )
    eia_request_timeout_seconds: float = Field(
        15.0,
        ge=2.0,
        le=120.0,
        validation_alias=AliasChoices("EIA_REQUEST_TIMEOUT_SECONDS", "eia_request_timeout_seconds"),
    )
    default_tractor_mpg: float = Field(
        6.5,
        gt=0,
        le=30.0,
        validation_alias=AliasChoices("DEFAULT_TRACTOR_MPG", "default_tractor_mpg"),
    )

    sku_inherit_min_label_lines: int = Field(
        12,
        validation_alias=AliasChoices("SKU_INHERIT_MIN_LABEL_LINES", "sku_inherit_min_label_lines"),
        description="Below this many label lines with SKU, borrow shipping stats from physical twin",
    )
    physical_signature_weight_step_lb: float = Field(
        0.5,
        validation_alias=AliasChoices(
            "PHYSICAL_SIGNATURE_WEIGHT_STEP_LB", "physical_signature_weight_step_lb"
        ),
    )
    physical_signature_dim_step_in: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "PHYSICAL_SIGNATURE_DIM_STEP_IN", "physical_signature_dim_step_in"
        ),
    )

    network_intelligence_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "NETWORK_INTELLIGENCE_ENABLED",
            "network_intelligence_enabled",
        ),
        description="When false, /v1/network/* returns 404",
    )
    audit_complementary_network_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "AUDIT_COMPLEMENTARY_NETWORK_ENABLED",
            "audit_complementary_network_enabled",
        ),
        description="When false, audit-synthesis skips complementary_network_audit (rate-shop batch).",
    )
    complementary_audit_max_easy_zone: int = Field(
        3,
        ge=1,
        le=8,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_MAX_EASY_ZONE",
            "complementary_audit_max_easy_zone",
        ),
        description="Mock parcel zone ceiling: exclude complementary DCs with zone(origin→DC) ≤ this (same/easy-reach).",
    )
    complementary_audit_in_region_max_zone: int = Field(
        3,
        ge=1,
        le=8,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_IN_REGION_MAX_ZONE",
            "complementary_audit_in_region_max_zone",
        ),
        description="Destinations with zone(origin→dest) ≤ this are treated as in-region for the audit split.",
    )
    complementary_audit_zone_carrier: str = Field(
        "ups",
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_ZONE_CARRIER",
            "complementary_audit_zone_carrier",
        ),
        description="Carrier mock for zone exclusivity / in-region split: usps | ups | fedex",
    )
    complementary_audit_max_destinations: int = Field(
        25,
        ge=1,
        le=100,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_MAX_DESTINATIONS",
            "complementary_audit_max_destinations",
        ),
        description="Cap ZIP3 destinations quoted per audit (performance).",
    )
    complementary_audit_default_weight_lb: float = Field(
        1.4,
        gt=0,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_DEFAULT_WEIGHT_LB",
            "complementary_audit_default_weight_lb",
        ),
    )
    complementary_audit_default_length_in: float = Field(
        9.0,
        gt=0,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_DEFAULT_LENGTH_IN",
            "complementary_audit_default_length_in",
        ),
    )
    complementary_audit_default_width_in: float = Field(
        7.0,
        gt=0,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_DEFAULT_WIDTH_IN",
            "complementary_audit_default_width_in",
        ),
    )
    complementary_audit_default_height_in: float = Field(
        5.0,
        gt=0,
        validation_alias=AliasChoices(
            "COMPLEMENTARY_AUDIT_DEFAULT_HEIGHT_IN",
            "complementary_audit_default_height_in",
        ),
    )

    # ── Unified intelligence data layer ──────────────────────────────────────
    # Deploy-time feature flags. Per-key runtime knobs (radius, tolerances,
    # alert thresholds) live in the `intelligence_settings` table and are
    # editable from the admin UI; the values below are fallbacks only.
    intel_layer_persist_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("INTEL_LAYER_PERSIST_ENABLED", "intel_layer_persist_enabled"),
    )
    intel_layer_lookup_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("INTEL_LAYER_LOOKUP_ENABLED", "intel_layer_lookup_enabled"),
    )
    intel_layer_scheduler_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("INTEL_LAYER_SCHEDULER_ENABLED", "intel_layer_scheduler_enabled"),
    )
    intel_layer_dual_write_legacy_pqo: bool = Field(
        True,
        validation_alias=AliasChoices(
            "INTEL_LAYER_DUAL_WRITE_LEGACY_PQO",
            "intel_layer_dual_write_legacy_pqo",
        ),
    )
    intel_layer_export_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("INTEL_LAYER_EXPORT_ENABLED", "intel_layer_export_enabled"),
    )
    intel_parcel_radius_mi_default: float = Field(5.0, gt=0)
    intel_ltl_radius_mi_default: float = Field(5.0, gt=0)
    intel_weight_tolerance_lb_default: float = Field(0.3, gt=0)
    intel_dim_tolerance_in_default: float = Field(0.7874, gt=0)
    intel_alert_high_density_min_deliveries_default: int = Field(250, ge=0)
    intel_alert_high_density_growth_pct_default: float = Field(30.0)
    intel_alert_rate_anomaly_pct_default: float = Field(25.0)
    intel_alert_min_observations_default: int = Field(5, ge=1)
    intel_retention_days_default: int = Field(365, ge=30)
    intel_settings_cache_ttl_seconds: int = Field(60, ge=1)

    # ── Cortex Audit / Vault / What-If / Rate Broker ────────────────────────
    # Local-only NVIDIA services for the parcel-audit package. URLs default
    # to None; when unset, the cortex-audit routers return 503 from a
    # dependency check and no background task does work.
    audit_etl_url: str | None = Field(
        None,
        validation_alias=AliasChoices("AUDIT_ETL_URL", "audit_etl_url"),
        description="cortex-audit-etl (RAPIDS/cuDF) container, e.g. http://127.0.0.1:8788",
    )
    audit_triton_http_url: str | None = Field(
        None,
        validation_alias=AliasChoices("AUDIT_TRITON_HTTP_URL", "audit_triton_http_url"),
        description="Self-hosted Triton inference server HTTP endpoint, e.g. http://127.0.0.1:8001",
    )
    audit_triton_model: str = Field(
        "audit_decision_pipeline",
        validation_alias=AliasChoices("AUDIT_TRITON_MODEL", "audit_triton_model"),
        description="Triton model/ensemble name for refundability classification.",
    )
    audit_vault_encryption_key: str | None = Field(
        None,
        validation_alias=AliasChoices("AUDIT_VAULT_ENCRYPTION_KEY", "audit_vault_encryption_key"),
        description="base64-encoded 32-byte Fernet key for carrier-credential encryption.",
    )
    audit_dispute_dry_run: bool = Field(
        True,
        validation_alias=AliasChoices("AUDIT_DISPUTE_DRY_RUN", "audit_dispute_dry_run"),
        description="When true, dispute submitter persists rows but does NOT call carrier APIs.",
    )

    # Carrier API roots (env-overridable for sandboxes)
    fedex_api_base_url: str = Field(
        "https://apis.fedex.com",
        validation_alias=AliasChoices("FEDEX_API_BASE_URL", "fedex_api_base_url"),
    )
    ups_api_base_url: str = Field(
        "https://onlinetools.ups.com",
        validation_alias=AliasChoices("UPS_API_BASE_URL", "ups_api_base_url"),
    )
    usps_api_base_url: str = Field(
        "https://api.usps.com",
        validation_alias=AliasChoices("USPS_API_BASE_URL", "usps_api_base_url"),
    )

    # UPS — OAuth 2.0 Authorization Code (3-legged); callback REQUIRED
    ups_oauth_client_id: str | None = Field(
        None, validation_alias=AliasChoices("UPS_OAUTH_CLIENT_ID", "ups_oauth_client_id"),
    )
    ups_oauth_client_secret: str | None = Field(
        None, validation_alias=AliasChoices("UPS_OAUTH_CLIENT_SECRET", "ups_oauth_client_secret"),
    )
    ups_oauth_auth_url: str = Field(
        "https://onlinetools.ups.com/security/v1/oauth/authorize",
        validation_alias=AliasChoices("UPS_OAUTH_AUTH_URL", "ups_oauth_auth_url"),
    )
    ups_oauth_token_url: str = Field(
        "https://onlinetools.ups.com/security/v1/oauth/token",
        validation_alias=AliasChoices("UPS_OAUTH_TOKEN_URL", "ups_oauth_token_url"),
    )
    ups_oauth_redirect_uri: str | None = Field(
        None,
        validation_alias=AliasChoices("UPS_OAUTH_REDIRECT_URI", "ups_oauth_redirect_uri"),
        description="Must match a redirect URI registered in the UPS developer portal.",
    )

    # FedEx — Credential Registration (server-to-server); NO browser callback
    fedex_parent_api_key: str | None = Field(
        None, validation_alias=AliasChoices("FEDEX_PARENT_API_KEY", "fedex_parent_api_key"),
    )
    fedex_parent_secret_key: str | None = Field(
        None, validation_alias=AliasChoices("FEDEX_PARENT_SECRET_KEY", "fedex_parent_secret_key"),
    )
    fedex_credential_registration_url: str = Field(
        "https://apis.fedex.com/auth/oauth/v2/credential-registration",
        validation_alias=AliasChoices(
            "FEDEX_CREDENTIAL_REGISTRATION_URL", "fedex_credential_registration_url",
        ),
    )

    # USPS API 3.0 — OAuth 2.0 Authorization Code; callback REQUIRED
    usps_oauth_client_id: str | None = Field(
        None, validation_alias=AliasChoices("USPS_OAUTH_CLIENT_ID", "usps_oauth_client_id"),
    )
    usps_oauth_client_secret: str | None = Field(
        None, validation_alias=AliasChoices("USPS_OAUTH_CLIENT_SECRET", "usps_oauth_client_secret"),
    )
    usps_oauth_auth_url: str = Field(
        "https://api.usps.com/oauth2/v3/authorize",
        validation_alias=AliasChoices("USPS_OAUTH_AUTH_URL", "usps_oauth_auth_url"),
    )
    usps_oauth_token_url: str = Field(
        "https://api.usps.com/oauth2/v3/token",
        validation_alias=AliasChoices("USPS_OAUTH_TOKEN_URL", "usps_oauth_token_url"),
    )
    usps_oauth_redirect_uri: str | None = Field(
        None,
        validation_alias=AliasChoices("USPS_OAUTH_REDIRECT_URI", "usps_oauth_redirect_uri"),
        description="Must match a redirect URI registered in the USPS developer portal.",
    )

    @field_validator(
        "shippo_mock_mode",
        "user_auth_enabled",
        "bootstrap_auth_must_rotate_password",
        "geocoding_nominatim",
        "network_intelligence_enabled",
        "wms_only_strict",
        "wms_only_require_complete_baseline",
        "wms_constraint_dock_mismatch_hard",
        "wms_constraint_call_ahead_hard",
        "audit_complementary_network_enabled",
        "tms_cuopt_sequencing",
        "tms_nvidia_cuopt_cloud_enabled",
        "tms_nim_dispatch_summary_enabled",
        "multi_dc_cuopt_cloud_enabled",
        "optimization_core_enabled",
        "tms_db_preferred_for_intelligence",
        "eia_enabled",
        "nim_csv_mapping_enabled",
        "ai_observability_enabled",
        "intel_layer_persist_enabled",
        "intel_layer_lookup_enabled",
        "intel_layer_scheduler_enabled",
        "intel_layer_dual_write_legacy_pqo",
        "intel_layer_export_enabled",
        "ltl_ai_enabled",
        "ltl_cuopt_cloud_enabled",
        "ltl_dynamic_stitching_enabled",
        "ltl_dynamic_allow_three_leg_fallback",
        "semantic_memory_enabled",
        "product_research_require_s3_durability_in_prod",
        "audit_dispute_dry_run",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, v):
        return _env_bool(v)

    @field_validator("google_address_validation_usps_cass", mode="before")
    @classmethod
    def _coerce_usps_cass(cls, v):
        return _env_bool(v)

    @model_validator(mode="after")
    def _spapi_endpoint_from_amazon_region(self) -> Self:
        """Map AMAZON_REGION=na|eu|fe to SP-API host + SigV4 region when not explicitly set."""
        code = (self.amazon_region or "").strip().lower()
        if not code:
            return self
        presets: dict[str, tuple[str, str]] = {
            "na": ("sellingpartnerapi-na.amazon.com", "us-east-1"),
            "us": ("sellingpartnerapi-na.amazon.com", "us-east-1"),
            "north_america": ("sellingpartnerapi-na.amazon.com", "us-east-1"),
            "eu": ("sellingpartnerapi-eu.amazon.com", "eu-west-1"),
            "europe": ("sellingpartnerapi-eu.amazon.com", "eu-west-1"),
            "fe": ("sellingpartnerapi-fe.amazon.com", "us-west-2"),
            "far_east": ("sellingpartnerapi-fe.amazon.com", "us-west-2"),
        }
        if code not in presets:
            return self
        host, region = presets[code]
        updates: dict[str, str] = {}
        if "spapi_endpoint_host" not in self.model_fields_set:
            updates["spapi_endpoint_host"] = host
        if "spapi_region" not in self.model_fields_set:
            updates["spapi_region"] = region
        if updates:
            return self.model_copy(update=updates)
        return self

    @property
    def use_mongodb(self) -> bool:
        return bool(self.mongodb_uri and str(self.mongodb_uri).strip())

    @property
    def use_aurora_dsql(self) -> bool:
        return bool(self.aurora_dsql_cluster_host and str(self.aurora_dsql_cluster_host).strip())

    @property
    def semantic_brain_configured(self) -> bool:
        if not self.semantic_memory_enabled:
            return False
        return bool(
            self.use_aurora_dsql
            or (self.semantic_database_url and str(self.semantic_database_url).strip())
            or (
                self.semantic_database_secret_arn
                and str(self.semantic_database_secret_arn).strip()
            )
        )

    @property
    def s3_artifacts_configured(self) -> bool:
        return bool(self.s3_artifacts_bucket and str(self.s3_artifacts_bucket).strip())

    @property
    def shippo_configured(self) -> bool:
        return bool(self.shippo_api_key and str(self.shippo_api_key).strip())


settings = Settings()
