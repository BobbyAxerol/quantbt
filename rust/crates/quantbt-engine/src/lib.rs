//! Pure Rust execution core for QuantBT native event execution.
//!
//! The API 0.4 PyO3 extension is deliberately an outer adapter. This crate
//! owns market/account state, lifecycle storage and result sinks without any
//! dependency on Python or NumPy. Typed command translation belongs to the
//! lower `quantbt-domain` boundary; the P0-compatible static reader remains
//! available while its complete ABI 0.5 execution migration is certified.

pub mod account;
pub mod execution_model;
pub mod fill_replay;
pub mod legacy;
pub mod market;
pub mod metrics_v2;
pub mod orders;
pub mod output;
pub mod session;

pub mod generated_contracts {
    pub use quantbt_domain::generated_contracts::*;
}

pub use execution_model::{
    BarTouchV1, CostModelV1, ExecutionClockStateV1, ExecutionFillV1, ExecutionModelPlanV1,
    ExecutionModelV1, FillCostInputV1, FillDecisionV1, LiquidityLedgerV1, MarketBarViewV1,
    OrderTouchViewV1,
};
pub use fill_replay::{
    FillReplayAuditV2, FillReplayCompactV2, FillReplayConfigV2, FillReplayFillV2,
    FillReplayFundingV2, FillReplayOutputProfileV2, FillReplayResultV2, FillReplayScoreV2,
    FundingPhaseV1, run_fill_replay_v2,
};
pub use metrics_v2::{
    MetricContractV2, MetricFinishInputV2, NativeMetricSnapshotV2, OnlineMetricReducerV2,
    ReturnFrequencyV2, ShortRunMetricPolicyV2, TradeCountDefinitionV2, ZeroVariancePolicyV2,
};
pub use output::{
    AuditRetentionV1, DEFAULT_AUDIT_DETAIL_ROW_LIMIT_V1, NATIVE_EXECUTION_OUTPUT_VERSION_V1,
    NativeAuditOutputV1, NativeCompactOutputV1, NativeEventOutputV1, NativeExecutionOutputV1,
    NativeFillOutputV1, NativePathOutputV1, NativeScoreOutputV1, OutputRequirementsV1,
    StaticOutputProfile, StaticTapeOutput,
};
// API 0.4 binding imports these public compatibility types while the internal
// implementation evolves behind ABI 0.5 structures. Keeping this re-export at
// the engine boundary avoids any execution logic in the PyO3 crate.
pub use session::*;
