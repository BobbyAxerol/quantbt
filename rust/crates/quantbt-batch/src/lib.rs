//! Deterministic scenario-batch boundary.
//!
//! Phase 53A freezes scalar result ownership and scenario identity. Parallel
//! scheduling, WFO reuse, and native IR execution arrive in Phase 53B.

use quantbt_domain::ids::SymbolId;

#[repr(transparent)]
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Ord, PartialOrd)]
pub struct ScenarioId(pub u32);

/// Stable scalar row retained for every optimization scenario. Audit detail is
/// intentionally excluded and must be rerun only for selected candidates.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScenarioScore {
    pub scenario: ScenarioId,
    pub final_equity: f64,
    pub total_fee: f64,
    pub total_funding: f64,
    pub turnover: f64,
    pub fill_count: u64,
    pub rejected_count: u64,
    pub liquidated: bool,
}

/// Explicit shared-market identity used by a later runner to prevent accidental
/// per-scenario market copies.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct SharedMarketKey {
    pub symbol: SymbolId,
    pub market_fingerprint: u64,
}
