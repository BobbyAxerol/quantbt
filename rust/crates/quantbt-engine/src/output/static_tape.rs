/// Retention contract resolved before a static command tape enters the engine.
/// It changes only materialization, never matching/accounting/lifecycle rules.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StaticOutputProfile {
    Score,
    Compact,
    Audit,
}

impl StaticOutputProfile {
    #[must_use]
    pub const fn retains_paths(self) -> bool {
        !matches!(self, Self::Score)
    }

    #[must_use]
    pub const fn retains_detail(self) -> bool {
        matches!(self, Self::Audit)
    }
}

/// Flat output produced by a full native static command tape. It intentionally
/// stores positions as one bar-major `Vec<f64>` rather than `Vec<Vec<f64>>` so
/// the PyO3 adapter can create one contiguous array without nested materialization.
#[derive(Clone, Debug, Default)]
pub struct StaticTapeOutput {
    pub equity: Vec<f64>,
    pub positions: Vec<f64>,
    pub fees: Vec<f64>,
    pub turnover: Vec<f64>,
    pub funding: Vec<f64>,
    pub initial_margin: Vec<f64>,
    pub maintenance_margin: Vec<f64>,
    pub fill_bar: Vec<i64>,
    pub fill_order_id: Vec<i64>,
    pub fill_symbol: Vec<i64>,
    pub fill_side: Vec<i64>,
    pub fill_qty: Vec<f64>,
    pub fill_price: Vec<f64>,
    pub fill_fee: Vec<f64>,
    pub fill_reason: Vec<i64>,
    pub fill_ambiguity: Vec<i64>,
    pub event_bar: Vec<i64>,
    pub event_kind: Vec<i64>,
    pub event_status: Vec<i64>,
    pub event_order_id: Vec<i64>,
    pub event_target_id: Vec<i64>,
    pub event_symbol: Vec<i64>,
    pub event_reject_code: Vec<i64>,
    pub final_equity: f64,
    pub final_positions: Vec<f64>,
    pub total_fee: f64,
    pub total_turnover: f64,
    pub total_funding: f64,
    pub fill_count: i64,
    pub event_count: i64,
    pub rejected_count: i64,
    pub canceled_count: i64,
    pub max_initial_margin: f64,
    pub max_maintenance_margin: f64,
    pub liquidated: bool,
    pub liquidation_bar: i64,
    pub liquidation_reason: i64,
}
