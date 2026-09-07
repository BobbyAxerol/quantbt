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

/// Stable schema marker for the typed ABI-0.5 execution result family.
///
/// The profile controls retention only. It never changes lifecycle, matching,
/// accounting, or the authoritative session state used to produce a result.
pub const NATIVE_EXECUTION_OUTPUT_VERSION_V1: u16 = 1;

/// Default upper bound for audit fill/event rows retained by one native run.
///
/// The accounting session still processes every lifecycle event. This limit
/// applies only to the optional diagnostic sink so a long audit cannot retain
/// an unbounded Python-facing trace by accident. Callers that need a complete
/// history can partition the tape into certified windows or use a future
/// chunked sink; the native result always reports whether any detail was
/// omitted.
pub const DEFAULT_AUDIT_DETAIL_ROW_LIMIT_V1: usize = 250_000;

/// Output retention is resolved once before a typed tape enters the hot loop.
/// This avoids scattered booleans accidentally materializing paths or audit
/// columns during score-only optimization workloads.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OutputRequirementsV1 {
    pub profile: StaticOutputProfile,
    pub retain_paths: bool,
    pub retain_detail: bool,
    /// Combined fill + lifecycle-event row cap. `None` means the profile does
    /// not retain audit detail at all; it never means unbounded retention.
    pub detail_row_limit: Option<usize>,
}

impl OutputRequirementsV1 {
    #[must_use]
    pub const fn resolve(profile: StaticOutputProfile) -> Self {
        Self {
            profile,
            retain_paths: profile.retains_paths(),
            retain_detail: profile.retains_detail(),
            detail_row_limit: if profile.retains_detail() {
                Some(DEFAULT_AUDIT_DETAIL_ROW_LIMIT_V1)
            } else {
                None
            },
        }
    }

    /// Construct a bounded audit requirement explicitly. This changes only
    /// output retention, never execution/accounting semantics.
    #[must_use]
    pub const fn audit_with_detail_limit(detail_row_limit: usize) -> Self {
        Self {
            profile: StaticOutputProfile::Audit,
            retain_paths: true,
            retain_detail: true,
            detail_row_limit: Some(detail_row_limit),
        }
    }

    /// Reject internally inconsistent retention plans before any lifecycle
    /// work begins. The public request builders always create valid plans, but
    /// this guard keeps direct Rust callers from silently turning a score run
    /// into a detail-retaining run (or vice versa).
    pub fn validate(self) -> Result<(), String> {
        let expected_paths = self.profile.retains_paths();
        let expected_detail = self.profile.retains_detail();
        if self.retain_paths != expected_paths || self.retain_detail != expected_detail {
            return Err("native output requirements conflict with their profile".to_owned());
        }
        match (self.retain_detail, self.detail_row_limit) {
            (true, Some(_)) | (false, None) => Ok(()),
            (true, None) => Err("audit output requires a bounded detail row limit".to_owned()),
            (false, Some(_)) => Err("non-audit output cannot retain detail rows".to_owned()),
        }
    }
}

/// Retention accounting for the optional audit SoA sink. Each fill and each
/// lifecycle event consumes one row from the same budget, preserving a strict
/// bounded-memory contract across both detail families.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuditRetentionV1 {
    pub row_limit: usize,
    pub retained_rows: usize,
    pub dropped_rows: usize,
}

impl AuditRetentionV1 {
    #[must_use]
    pub const fn new(row_limit: usize) -> Self {
        Self {
            row_limit,
            retained_rows: 0,
            dropped_rows: 0,
        }
    }

    /// Returns whether the next row may enter the retained SoA columns.
    /// Overflow is accounted as a dropped row rather than silently ignored.
    pub fn retain_next(&mut self) -> bool {
        if self.retained_rows < self.row_limit {
            self.retained_rows += 1;
            true
        } else {
            self.dropped_rows = self.dropped_rows.saturating_add(1);
            false
        }
    }

    #[must_use]
    pub const fn truncated(self) -> bool {
        self.dropped_rows > 0
    }
}

impl Default for AuditRetentionV1 {
    fn default() -> Self {
        Self::new(0)
    }
}

/// Scalar-only result for native score workloads. It deliberately owns no
/// equity path, fill/event detail, nested rows, Python dictionary, or report
/// object. Final positions are copied once after the final bar, never once per
/// bar.
#[derive(Clone, Debug, PartialEq)]
pub struct NativeScoreOutputV1 {
    pub output_version: u16,
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
    /// Policy and standard scalar metrics emitted by the same native pass.
    /// Paths/fills remain retention-profile-specific payloads below.
    pub metric_contract: MetricContractV2,
    pub metrics_v2: Box<NativeMetricSnapshotV2>,
}

impl NativeScoreOutputV1 {
    #[must_use]
    pub(crate) fn new(initial_equity: f64) -> Self {
        Self {
            output_version: NATIVE_EXECUTION_OUTPUT_VERSION_V1,
            final_equity: initial_equity,
            final_positions: Vec::new(),
            total_fee: 0.0,
            total_turnover: 0.0,
            total_funding: 0.0,
            fill_count: 0,
            event_count: 0,
            rejected_count: 0,
            canceled_count: 0,
            max_initial_margin: 0.0,
            max_maintenance_margin: 0.0,
            liquidated: false,
            liquidation_bar: -1,
            liquidation_reason: 0,
            metric_contract: MetricContractV2::default(),
            metrics_v2: Box::new(NativeMetricSnapshotV2 {
                metric_contract_version: crate::metrics_v2::METRIC_CONTRACT_VERSION_V2,
                final_equity: initial_equity,
                ..NativeMetricSnapshotV2::default()
            }),
        }
    }
}

impl Default for NativeScoreOutputV1 {
    fn default() -> Self {
        Self::new(0.0)
    }
}

/// Dense bar-major columns retained only by compact/audit profiles. Position
/// data stays flat (`bars * symbols`), never a nested vector of rows.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct NativePathOutputV1 {
    pub equity: Vec<f64>,
    pub positions: Vec<f64>,
    pub fees: Vec<f64>,
    pub turnover: Vec<f64>,
    pub funding: Vec<f64>,
    pub initial_margin: Vec<f64>,
    pub maintenance_margin: Vec<f64>,
}

impl NativePathOutputV1 {
    #[must_use]
    pub fn with_capacity(n_bars: usize, n_symbols: usize) -> Self {
        Self {
            equity: Vec::with_capacity(n_bars),
            positions: Vec::with_capacity(n_bars.saturating_mul(n_symbols)),
            fees: Vec::with_capacity(n_bars),
            turnover: Vec::with_capacity(n_bars),
            funding: Vec::with_capacity(n_bars),
            initial_margin: Vec::with_capacity(n_bars),
            maintenance_margin: Vec::with_capacity(n_bars),
        }
    }
}

/// Typed fill columns. Integer identifiers remain integer columns all the way
/// to the PyO3 cold-path adapter; they are never cast to `f64`.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct NativeFillOutputV1 {
    pub bar: Vec<i64>,
    pub order_id: Vec<i64>,
    pub symbol: Vec<i64>,
    pub side: Vec<i64>,
    pub qty: Vec<f64>,
    pub price: Vec<f64>,
    pub fee: Vec<f64>,
    pub reason: Vec<i64>,
    pub ambiguity: Vec<i64>,
}

/// Typed lifecycle-event columns retained only by audit profile.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct NativeEventOutputV1 {
    pub bar: Vec<i64>,
    pub kind: Vec<i64>,
    pub status: Vec<i64>,
    pub order_id: Vec<i64>,
    pub target_id: Vec<i64>,
    pub symbol: Vec<i64>,
    pub reject_code: Vec<i64>,
}

/// Compact typed result: scalar score plus dense account columns, without
/// fills/events. This is the report/plot input after an explicit cold-path
/// adaptation.
#[derive(Clone, Debug, PartialEq)]
pub struct NativeCompactOutputV1 {
    pub score: NativeScoreOutputV1,
    pub paths: NativePathOutputV1,
}

/// Audit typed result: compact output plus flat typed fill/event columns.
/// It is the authoritative native trace artifact; Python does not replay the
/// execution to reconstruct it.
#[derive(Clone, Debug, PartialEq)]
pub struct NativeAuditOutputV1 {
    pub compact: NativeCompactOutputV1,
    pub fills: NativeFillOutputV1,
    pub events: NativeEventOutputV1,
    pub detail_retention: AuditRetentionV1,
}

/// Versioned output family used by ABI-0.5 typed requests. The legacy static
/// result remains an adapter target only so API-0.4 callers continue to work.
#[derive(Clone, Debug, PartialEq)]
pub enum NativeExecutionOutputV1 {
    Score(NativeScoreOutputV1),
    Compact(Box<NativeCompactOutputV1>),
    Audit(Box<NativeAuditOutputV1>),
}

impl NativeExecutionOutputV1 {
    #[must_use]
    pub const fn profile(&self) -> StaticOutputProfile {
        match self {
            Self::Score(_) => StaticOutputProfile::Score,
            Self::Compact(_) => StaticOutputProfile::Compact,
            Self::Audit(_) => StaticOutputProfile::Audit,
        }
    }

    #[must_use]
    pub const fn score(&self) -> &NativeScoreOutputV1 {
        match self {
            Self::Score(output) => output,
            Self::Compact(output) => &output.score,
            Self::Audit(output) => &output.compact.score,
        }
    }

    #[must_use]
    pub const fn detail_retention(&self) -> AuditRetentionV1 {
        match self {
            Self::Score(_) | Self::Compact(_) => AuditRetentionV1::new(0),
            Self::Audit(output) => output.detail_retention,
        }
    }

    /// Move the typed columns into the frozen API-0.4 compatibility shape.
    /// No execution is replayed and no result vector is cloned by this adapter.
    #[must_use]
    pub fn into_legacy_static(self) -> StaticTapeOutput {
        self.into()
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

impl From<NativeExecutionOutputV1> for StaticTapeOutput {
    fn from(output: NativeExecutionOutputV1) -> Self {
        match output {
            NativeExecutionOutputV1::Score(score) => Self::from_typed_parts(
                score,
                NativePathOutputV1::default(),
                NativeFillOutputV1::default(),
                NativeEventOutputV1::default(),
            ),
            NativeExecutionOutputV1::Compact(compact) => {
                let NativeCompactOutputV1 { score, paths } = *compact;
                Self::from_typed_parts(
                    score,
                    paths,
                    NativeFillOutputV1::default(),
                    NativeEventOutputV1::default(),
                )
            }
            NativeExecutionOutputV1::Audit(audit) => {
                let NativeAuditOutputV1 {
                    compact,
                    fills,
                    events,
                    detail_retention: _,
                } = *audit;
                Self::from_typed_parts(compact.score, compact.paths, fills, events)
            }
        }
    }
}

impl StaticTapeOutput {
    fn from_typed_parts(
        score: NativeScoreOutputV1,
        paths: NativePathOutputV1,
        fills: NativeFillOutputV1,
        events: NativeEventOutputV1,
    ) -> Self {
        Self {
            equity: paths.equity,
            positions: paths.positions,
            fees: paths.fees,
            turnover: paths.turnover,
            funding: paths.funding,
            initial_margin: paths.initial_margin,
            maintenance_margin: paths.maintenance_margin,
            fill_bar: fills.bar,
            fill_order_id: fills.order_id,
            fill_symbol: fills.symbol,
            fill_side: fills.side,
            fill_qty: fills.qty,
            fill_price: fills.price,
            fill_fee: fills.fee,
            fill_reason: fills.reason,
            fill_ambiguity: fills.ambiguity,
            event_bar: events.bar,
            event_kind: events.kind,
            event_status: events.status,
            event_order_id: events.order_id,
            event_target_id: events.target_id,
            event_symbol: events.symbol,
            event_reject_code: events.reject_code,
            final_equity: score.final_equity,
            final_positions: score.final_positions,
            total_fee: score.total_fee,
            total_turnover: score.total_turnover,
            total_funding: score.total_funding,
            fill_count: score.fill_count,
            event_count: score.event_count,
            rejected_count: score.rejected_count,
            canceled_count: score.canceled_count,
            max_initial_margin: score.max_initial_margin,
            max_maintenance_margin: score.max_maintenance_margin,
            liquidated: score.liquidated,
            liquidation_bar: score.liquidation_bar,
            liquidation_reason: score.liquidation_reason,
        }
    }
}
use crate::metrics_v2::{MetricContractV2, NativeMetricSnapshotV2};
