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
    cors_origins: str = Field(
        "",
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"),
        description="Comma-separated allowed origins; empty = * for dev",
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

    keepa_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("KEEPA_API_KEY", "keepa_api_key"),
    )
    keepa_ttl_days: int = Field(
        30,
        validation_alias=AliasChoices("KEEPA_TTL_DAYS", "keepa_ttl_days"),
        description="Per-ASIN Keepa cache TTL in days (full product JSON reuses until expiry)",
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
        description="Below this catalog-wide monthly demand, auto network stays single-node",
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
        500.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_UNITS_PER_WAREHOUSE_WHEN_THREE_OR_MORE_NODES",
            "smart_network_min_units_per_warehouse_when_three_or_more_nodes",
        ),
        description="Per-node monthly flow floor when three or more warehouses are active",
    )
    smart_network_max_warehouses: int = Field(
        6,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MAX_WAREHOUSES",
            "smart_network_max_warehouses",
        ),
        description="Hard cap on auto-expanded warehouse count (US regional archetypes)",
    )
    smart_network_monthly_orders_per_additional_warehouse: float = Field(
        1000.0,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MONTHLY_ORDERS_PER_ADDITIONAL_WAREHOUSE",
            "smart_network_monthly_orders_per_additional_warehouse",
        ),
        ge=1.0,
        description=(
            "Multi-DC target count scales as min(max_warehouses, base_multi + floor(monthly_units / this)). "
            "Example: 72/mo → 2 DCs; 1000/mo → 3 DCs."
        ),
    )
    smart_network_min_multi_dc_warehouse_count: int = Field(
        2,
        validation_alias=AliasChoices(
            "SMART_NETWORK_MIN_MULTI_DC_WAREHOUSE_COUNT",
            "smart_network_min_multi_dc_warehouse_count",
        ),
        ge=2,
        le=6,
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
        6,
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
        description="Bearer for NVIDIA managed cuOpt cloud (optimize.api.nvidia.com) when used; not used for LLM chat.",
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
        False,
        validation_alias=AliasChoices(
            "CUOPT_INFORM_ALLOCATION_WEIGHTS",
            "cuopt_inform_allocation_weights",
        ),
        description=(
            "When true, after PRO tri-modal cuOpt completes, compute a counterfactual allocation from nudged "
            "target_share_pct (visit-order heuristic) and attach allocation_cuopt_counterfactual."
        ),
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
    cuopt_api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("CUOPT_API_KEY", "cuopt_api_key"),
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

    @field_validator(
        "shippo_mock_mode",
        "geocoding_nominatim",
        "network_intelligence_enabled",
        "audit_complementary_network_enabled",
        "tms_cuopt_sequencing",
        "tms_nvidia_cuopt_cloud_enabled",
        "multi_dc_cuopt_cloud_enabled",
        "eia_enabled",
        "nim_csv_mapping_enabled",
        "ai_observability_enabled",
        "semantic_memory_enabled",
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
            (self.semantic_database_url and str(self.semantic_database_url).strip())
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
