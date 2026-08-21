//! Generated from contracts/native_event_product_registry.json; do not edit.
#![allow(dead_code)]

pub const PRODUCT_CONTRACT_REGISTRY_FINGERPRINT: &str =
    "8f56961b5ee41929d79f331bd0694d364770bb7f49aeb80d1c84deebd1bc774b";
pub const LIFECYCLE_REGISTRY_FINGERPRINT: &str =
    "601d639f1c398ac81f3c8231c30d067372c80e71ae4e5f097182f00c5c91f05d";
pub const CORE_PACKAGE_VERSION: &str = "1.0.9";
pub const NATIVE_PACKAGE_VERSION: &str = "0.4.0";
pub const NATIVE_API_VERSION: &str = "0.4";
pub const SEMANTIC_DESCRIPTOR_VERSION: &str = "native-event-semantics-v1";
pub const CORE_PROTOCOL_MIN: i64 = 1;
pub const CORE_PROTOCOL_MAX: i64 = 1;
pub const COMMAND_ABI_VERSION: &str = "full-command-v1";
pub const RESULT_ABI_VERSION: &str = "native-event-result-v1";
pub const TRACE_SCHEMA_VERSION: &str = "canonical-execution-trace-v1";
pub const STRATEGY_IR_VERSION: &str = "native-strategy-ir-v1";
pub const PROMOTION_POLICY_TABLE_VERSION: &str = "native-event-promotion-v2";
pub const PROMOTION_POLICY_DEFAULT_STAGE: &str = "static_ir";
pub const PROMOTION_POLICY_DEFAULT_BACKEND_POLICY: &str = "certified_only";

pub const NATIVE_EXTENSION_CAPABILITIES: &[&str] = &[
    "r0_import_smoke",
    "reactive_session",
    "r1_single_symbol",
    "r1_place_cancel_market_limit_gtc",
    "r2_stop_amend_replace_reduce_only_constraints",
    "prepared_market_core",
    "rust_batched_tape",
    "rust_batched_tape_score",
    "rust_batched_tape_audit",
    "rust_batched_tape_sparse",
    "native_event_v2_full_contract",
    "native_event_v2_multisymbol",
    "native_event_v2_funding",
    "native_event_v2_liquidation",
    "native_event_v2_cancel_all_oco",
    "native_event_v2_tif_expiry",
    "native_event_v2_relationships",
    "native_event_v2_quantity_preflight",
    "event_contract_registry_v1",
    "event_lifecycle_v2_next_bar_close",
    "event_lifecycle_v3_next_open",
    "bar_fill_reason_v1",
    "lifecycle_transition_schema_v1",
    "semantic_descriptor_v1",
    "deterministic_quantization_v1",
    "core_abi_0_5",
    "generation_safe_order_arena",
    "flat_static_tape_output",
    "static_tape_compact",
    "native_strategy_ir_v1",
    "native_strategy_ir_signal_target",
    "native_strategy_ir_grid_level",
    "native_strategy_ir_dca_periodic",
    "native_strategy_ir_fixed_bracket",
    "native_strategy_ir_batch_v1",
    "native_portfolio_target_preflight_v1",
    "native_package_transaction_preflight_v1",
    "native_portfolio_target_market_v1",
    "native_package_atomic_market_v1",
];

pub const RUNTIME_CONTRACT_IDS: &[&str] = &[
    "event_lifecycle_v2_next_bar_close",
    "event_lifecycle_v3_next_open",
];

pub const RUNTIME_ORDER_TYPES: &[&str] = &["market", "limit", "stop_market", "stop_limit"];

pub const RUNTIME_GAP_POLICIES: &[&str] = &["legacy_trigger", "open_worse_than_trigger"];

pub const RUNTIME_PNL_MODELS: &[&str] = &["linear_quote_settled"];

pub const RUNTIME_MARGIN_MODELS: &[&str] = &["gross_cross"];

pub const RUNTIME_LIQUIDATION_MODELS: &[&str] = &["zero_equity_legacy"];

pub const RUNTIME_PARTIAL_FILL: bool = false;
pub const RUNTIME_VOLUME_MODEL: &str = "infinite_bar_liquidity";
pub const RUNTIME_PORTFOLIO_TARGET_EXECUTION: &str = "target_units_market_v1_all_or_none_v2";
pub const RUNTIME_PACKAGE_ATOMICITY: &str = "bar_transaction_atomic_market_v1";
