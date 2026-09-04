//! Whole-run Rust FillReplay V2.
//!
//! Fill replay deliberately removes matching ambiguity: explicit fill and
//! funding rows exercise the canonical linear account authority directly. It
//! is the A2 accounting reference before lifecycle/target/portfolio routes
//! migrate to the same state transition owner.

use std::collections::BTreeSet;

use quantbt_domain::ids::{AccountId, BarIndex, SymbolId, TimestampNs};
use quantbt_domain::trace_v2::{
    CanonicalEventKindV2, CanonicalTraceRowV2, TraceHashV2, TraceToleranceV2,
    canonical_trace_hash_v2,
};

use crate::account::{
    AccountDeltaV1, AccountFingerprintV1, AccountingRejectCodeV1, CandidateFillV1, FundingDeltaV1,
    LinearAccountConfigV1, LinearAccountSnapshotV1, LinearAccountTransactionV1,
    LinearGrossCrossAccountV1, LiquidationTransitionV1, ScheduledFundingEventV1,
};

const EPSILON: f64 = 1e-12;

/// Funding position phase for an explicit close-timestamp replay tape.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum FundingPhaseV1 {
    BeforeFillsAtClose = 0,
    AfterFillsAtClose = 1,
}

impl TryFrom<u8> for FundingPhaseV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::BeforeFillsAtClose),
            1 => Ok(Self::AfterFillsAtClose),
            _ => Err("unsupported fill replay funding phase".to_owned()),
        }
    }
}

impl FundingPhaseV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::BeforeFillsAtClose => "before_fills_at_close",
            Self::AfterFillsAtClose => "after_fills_at_close",
        }
    }
}

/// The requested retained artifact level. Accounting always executes through
/// the same authority; this only controls result retention.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum FillReplayOutputProfileV2 {
    Score = 0,
    Compact = 1,
    Audit = 2,
}

impl TryFrom<u8> for FillReplayOutputProfileV2 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Score),
            1 => Ok(Self::Compact),
            2 => Ok(Self::Audit),
            _ => Err("unsupported fill replay output profile".to_owned()),
        }
    }
}

/// Immutable account/replay model. Fees are supplied explicitly by every fill.
#[derive(Clone, Debug, PartialEq)]
pub struct FillReplayConfigV2 {
    pub initial_capital: f64,
    pub maintenance_ratio: f64,
    pub contract_sizes: Box<[f64]>,
    pub leverages: Box<[f64]>,
    pub liquidation_fee_rate: f64,
    pub funding_phase: FundingPhaseV1,
    /// Enables post-transition invariant scans for certification/audit runs.
    /// Score paths can disable it without selecting another account authority.
    pub invariant_checks: bool,
}

impl FillReplayConfigV2 {
    pub fn new(
        initial_capital: f64,
        maintenance_ratio: f64,
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
        liquidation_fee_rate: f64,
        funding_phase: FundingPhaseV1,
    ) -> Result<Self, AccountingRejectCodeV1> {
        LinearAccountConfigV1::new(
            initial_capital,
            maintenance_ratio,
            contract_sizes.clone(),
            leverages.clone(),
        )?;
        if !liquidation_fee_rate.is_finite() || liquidation_fee_rate < 0.0 {
            return Err(AccountingRejectCodeV1::InvalidFee);
        }
        Ok(Self {
            initial_capital,
            maintenance_ratio,
            contract_sizes: contract_sizes.into_boxed_slice(),
            leverages: leverages.into_boxed_slice(),
            liquidation_fee_rate,
            funding_phase,
            invariant_checks: cfg!(debug_assertions),
        })
    }

    #[must_use]
    pub const fn with_invariant_checks(mut self, enabled: bool) -> Self {
        self.invariant_checks = enabled;
        self
    }

    fn account_config(&self) -> Result<LinearAccountConfigV1, AccountingRejectCodeV1> {
        LinearAccountConfigV1::new(
            self.initial_capital,
            self.maintenance_ratio,
            self.contract_sizes.to_vec(),
            self.leverages.to_vec(),
        )
        .map(|config| config.with_invariant_checks(self.invariant_checks))
    }

    #[must_use]
    pub fn n_symbols(&self) -> usize {
        self.contract_sizes.len()
    }
}

/// One explicit committed-candidate fill. Input is ordered by `(bar, sequence)`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FillReplayFillV2 {
    pub bar_index: usize,
    pub sequence: u64,
    pub event_id: u64,
    pub symbol: SymbolId,
    pub signed_qty: f64,
    pub price: f64,
    pub fee: f64,
}

/// One scheduled funding row. It is intentionally separate from fills.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FillReplayFundingV2 {
    pub bar_index: usize,
    pub sequence: u64,
    pub event_id: u64,
    pub symbol: SymbolId,
    pub rate: f64,
}

/// Scalar terminal result common to all retained profiles.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FillReplayScoreV2 {
    pub final_cash: f64,
    pub final_equity: f64,
    pub total_realized_pnl: f64,
    pub total_fees: f64,
    pub total_funding: f64,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub available_equity: f64,
    pub liquidated: bool,
    pub liquidation_state: i32,
    pub accepted_fill_count: usize,
    pub rejected_fill_count: usize,
    pub accepted_funding_count: usize,
    pub rejected_funding_count: usize,
    pub account_fingerprint: AccountFingerprintV1,
    pub trace_fingerprint: TraceHashV2,
}

/// Bar-major accounting paths retained by compact and audit modes.
#[derive(Clone, Debug, PartialEq)]
pub struct FillReplayCompactV2 {
    pub score: FillReplayScoreV2,
    pub equity: Vec<f64>,
    pub cash: Vec<f64>,
    pub fees_paid: Vec<f64>,
    pub funding_paid: Vec<f64>,
    pub initial_margin: Vec<f64>,
    pub maintenance_margin: Vec<f64>,
    pub available_equity: Vec<f64>,
    pub liquidation_state: Vec<i32>,
    pub positions: Vec<f64>,
    pub average_entries: Vec<f64>,
    pub n_bars: usize,
    pub n_symbols: usize,
}

/// Audit adds the canonical account trace; no alternate accounting replay is
/// constructed at the Python boundary.
#[derive(Clone, Debug, PartialEq)]
pub struct FillReplayAuditV2 {
    pub compact: FillReplayCompactV2,
    pub trace: Vec<CanonicalTraceRowV2>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum FillReplayResultV2 {
    Score(FillReplayScoreV2),
    Compact(FillReplayCompactV2),
    Audit(FillReplayAuditV2),
}

impl FillReplayResultV2 {
    #[must_use]
    pub fn score(&self) -> FillReplayScoreV2 {
        match self {
            Self::Score(value) => *value,
            Self::Compact(value) => value.score,
            Self::Audit(value) => value.compact.score,
        }
    }
}

/// Execute a whole explicit replay tape through the common linear account.
#[allow(clippy::too_many_arguments)]
pub fn run_fill_replay_v2(
    timestamps_ns: &[i64],
    marks: &[f64],
    n_symbols: usize,
    fills: &[FillReplayFillV2],
    funding: &[FillReplayFundingV2],
    config: FillReplayConfigV2,
    profile: FillReplayOutputProfileV2,
) -> Result<FillReplayResultV2, String> {
    validate_input(timestamps_ns, marks, n_symbols, fills, funding, &config)?;
    let n_bars = timestamps_ns.len();
    let mut account =
        LinearGrossCrossAccountV1::new(config.account_config().map_err(reject_message)?);
    let mut fill_cursor = 0usize;
    let mut funding_cursor = 0usize;
    let mut trace = Vec::new();
    let mut trace_sequence = 0u64;
    let mut accepted_fills = 0usize;
    let mut rejected_fills = 0usize;
    let mut accepted_funding = 0usize;
    let mut rejected_funding = 0usize;
    let mut equity = Vec::with_capacity(n_bars);
    let mut cash = Vec::with_capacity(n_bars);
    let mut fees_paid = Vec::with_capacity(n_bars);
    let mut funding_paid = Vec::with_capacity(n_bars);
    let mut initial_margin = Vec::with_capacity(n_bars);
    let mut maintenance_margin = Vec::with_capacity(n_bars);
    let mut available_equity = Vec::with_capacity(n_bars);
    let mut liquidation_state = Vec::with_capacity(n_bars);
    let mut positions = Vec::with_capacity(n_bars * n_symbols);
    let mut average_entries = Vec::with_capacity(n_bars * n_symbols);

    for bar in 0..n_bars {
        let timestamp = timestamps_ns[bar];
        let before_mark = account.snapshot();
        account
            .observe_marks(&marks[bar * n_symbols..(bar + 1) * n_symbols])
            .map_err(reject_message)?;
        let after_mark = account.snapshot();
        push_trace(
            &mut trace,
            &mut trace_sequence,
            bar,
            timestamp,
            CanonicalEventKindV2::MarketObserved,
            None,
            0.0,
            f64::NAN,
            0.0,
            &before_mark,
            &after_mark,
            0,
        );

        if config.funding_phase == FundingPhaseV1::BeforeFillsAtClose {
            process_funding_at_bar(
                bar,
                timestamp,
                funding,
                &mut funding_cursor,
                &mut account,
                &mut trace,
                &mut trace_sequence,
                &mut accepted_funding,
                &mut rejected_funding,
            );
        }
        process_liquidation(
            bar,
            timestamp,
            config.liquidation_fee_rate,
            &mut account,
            &mut trace,
            &mut trace_sequence,
        )?;
        process_fills_at_bar(
            bar,
            timestamp,
            &marks[bar * n_symbols..(bar + 1) * n_symbols],
            fills,
            &mut fill_cursor,
            &mut account,
            &mut trace,
            &mut trace_sequence,
            &mut accepted_fills,
            &mut rejected_fills,
        );
        if config.funding_phase == FundingPhaseV1::AfterFillsAtClose {
            process_funding_at_bar(
                bar,
                timestamp,
                funding,
                &mut funding_cursor,
                &mut account,
                &mut trace,
                &mut trace_sequence,
                &mut accepted_funding,
                &mut rejected_funding,
            );
        }
        process_liquidation(
            bar,
            timestamp,
            config.liquidation_fee_rate,
            &mut account,
            &mut trace,
            &mut trace_sequence,
        )?;
        if config.invariant_checks {
            account.assert_invariants().map_err(reject_message)?;
        }
        let snapshot = account.snapshot();
        push_trace(
            &mut trace,
            &mut trace_sequence,
            bar,
            timestamp,
            CanonicalEventKindV2::AccountSnapshot,
            None,
            0.0,
            f64::NAN,
            0.0,
            &snapshot,
            &snapshot,
            0,
        );
        equity.push(snapshot.equity);
        cash.push(snapshot.cash);
        fees_paid.push(snapshot.fees_paid);
        funding_paid.push(snapshot.funding_paid);
        initial_margin.push(snapshot.initial_margin);
        maintenance_margin.push(snapshot.maintenance_margin);
        available_equity.push(snapshot.available_equity);
        liquidation_state.push(snapshot.liquidation_state as i32);
        positions.extend_from_slice(&snapshot.qty);
        average_entries.extend_from_slice(&snapshot.average_entry);
    }
    if fill_cursor != fills.len() || funding_cursor != funding.len() {
        return Err("fill replay cursor did not consume every row".to_owned());
    }
    let trace_fingerprint = canonical_trace_hash_v2(&trace, TraceToleranceV2::default());
    let score = FillReplayScoreV2 {
        final_cash: account.cash,
        final_equity: account.equity,
        total_realized_pnl: account.realized_pnl,
        total_fees: account.fees_paid,
        total_funding: account.funding_paid,
        initial_margin: account.initial_margin,
        maintenance_margin: account.maintenance_margin,
        available_equity: account.available_equity,
        liquidated: account.liquidation_state.is_terminal(),
        liquidation_state: account.liquidation_state as i32,
        accepted_fill_count: accepted_fills,
        rejected_fill_count: rejected_fills,
        accepted_funding_count: accepted_funding,
        rejected_funding_count: rejected_funding,
        account_fingerprint: account.fingerprint(),
        trace_fingerprint,
    };
    let compact = FillReplayCompactV2 {
        score,
        equity,
        cash,
        fees_paid,
        funding_paid,
        initial_margin,
        maintenance_margin,
        available_equity,
        liquidation_state,
        positions,
        average_entries,
        n_bars,
        n_symbols,
    };
    match profile {
        FillReplayOutputProfileV2::Score => Ok(FillReplayResultV2::Score(score)),
        FillReplayOutputProfileV2::Compact => Ok(FillReplayResultV2::Compact(compact)),
        FillReplayOutputProfileV2::Audit => Ok(FillReplayResultV2::Audit(FillReplayAuditV2 {
            compact,
            trace,
        })),
    }
}

#[allow(clippy::too_many_arguments)]
fn process_fills_at_bar(
    bar: usize,
    timestamp: i64,
    marks: &[f64],
    fills: &[FillReplayFillV2],
    cursor: &mut usize,
    account: &mut LinearGrossCrossAccountV1,
    trace: &mut Vec<CanonicalTraceRowV2>,
    trace_sequence: &mut u64,
    accepted: &mut usize,
    rejected: &mut usize,
) {
    while *cursor < fills.len() && fills[*cursor].bar_index == bar {
        let row = fills[*cursor];
        let symbol_index = row.symbol.0 as usize;
        let mark_price = marks[symbol_index];
        let candidate = CandidateFillV1 {
            event_id: row.event_id,
            symbol: row.symbol,
            signed_qty: row.signed_qty,
            price: row.price,
            fee: row.fee,
            mark_price,
        };
        match account.commit_fill(None, &candidate) {
            Ok(delta) => {
                *accepted += 1;
                push_fill_trace(
                    trace,
                    trace_sequence,
                    bar,
                    timestamp,
                    CanonicalEventKindV2::FillCommitted,
                    &delta,
                );
            }
            Err(code) => {
                *rejected += 1;
                let snapshot = account.snapshot();
                push_trace(
                    trace,
                    trace_sequence,
                    bar,
                    timestamp,
                    CanonicalEventKindV2::CommandRejected,
                    Some(row.symbol),
                    row.signed_qty,
                    row.price,
                    row.fee,
                    &snapshot,
                    &snapshot,
                    code as i32,
                );
            }
        }
        *cursor += 1;
    }
}

#[allow(clippy::too_many_arguments)]
fn process_funding_at_bar(
    bar: usize,
    timestamp: i64,
    funding: &[FillReplayFundingV2],
    cursor: &mut usize,
    account: &mut LinearGrossCrossAccountV1,
    trace: &mut Vec<CanonicalTraceRowV2>,
    trace_sequence: &mut u64,
    accepted: &mut usize,
    rejected: &mut usize,
) {
    while *cursor < funding.len() && funding[*cursor].bar_index == bar {
        let row = funding[*cursor];
        match account.apply_funding_once(ScheduledFundingEventV1 {
            event_id: row.event_id,
            symbol: row.symbol,
            rate: row.rate,
        }) {
            Ok(delta) => {
                *accepted += 1;
                push_funding_trace(trace, trace_sequence, bar, timestamp, &delta);
            }
            Err(code) => {
                *rejected += 1;
                let snapshot = account.snapshot();
                push_trace(
                    trace,
                    trace_sequence,
                    bar,
                    timestamp,
                    CanonicalEventKindV2::CommandRejected,
                    Some(row.symbol),
                    0.0,
                    account.positions.mark[row.symbol.0 as usize],
                    0.0,
                    &snapshot,
                    &snapshot,
                    code as i32,
                );
            }
        }
        *cursor += 1;
    }
}

fn process_liquidation(
    bar: usize,
    timestamp: i64,
    liquidation_fee_rate: f64,
    account: &mut LinearGrossCrossAccountV1,
    trace: &mut Vec<CanonicalTraceRowV2>,
    trace_sequence: &mut u64,
) -> Result<(), String> {
    let Some(transition) = account
        .liquidate_if_breached(liquidation_fee_rate)
        .map_err(reject_message)?
    else {
        return Ok(());
    };
    push_liquidation_trace(trace, trace_sequence, bar, timestamp, &transition);
    Ok(())
}

fn push_liquidation_trace(
    trace: &mut Vec<CanonicalTraceRowV2>,
    sequence: &mut u64,
    bar: usize,
    timestamp: i64,
    transition: &LiquidationTransitionV1,
) {
    push_trace(
        trace,
        sequence,
        bar,
        timestamp,
        CanonicalEventKindV2::LiquidationStarted,
        None,
        0.0,
        f64::NAN,
        0.0,
        &transition.before,
        &transition.before,
        transition.state_before as i32,
    );
    for delta in &transition.fills {
        push_fill_trace(
            trace,
            sequence,
            bar,
            timestamp,
            CanonicalEventKindV2::LiquidationFill,
            delta,
        );
    }
    push_trace(
        trace,
        sequence,
        bar,
        timestamp,
        CanonicalEventKindV2::LiquidationCompleted,
        None,
        0.0,
        f64::NAN,
        0.0,
        &transition.after,
        &transition.after,
        transition.state_after as i32,
    );
}

fn push_fill_trace(
    trace: &mut Vec<CanonicalTraceRowV2>,
    sequence: &mut u64,
    bar: usize,
    timestamp: i64,
    kind: CanonicalEventKindV2,
    delta: &AccountDeltaV1,
) {
    push_trace(
        trace,
        sequence,
        bar,
        timestamp,
        kind,
        Some(delta.symbol),
        delta.signed_qty,
        delta.price,
        delta.fee,
        &delta.before,
        &delta.after,
        0,
    );
}

fn push_funding_trace(
    trace: &mut Vec<CanonicalTraceRowV2>,
    sequence: &mut u64,
    bar: usize,
    timestamp: i64,
    delta: &FundingDeltaV1,
) {
    push_trace(
        trace,
        sequence,
        bar,
        timestamp,
        CanonicalEventKindV2::FundingApplied,
        Some(delta.symbol),
        0.0,
        delta.before.marks[delta.symbol.0 as usize],
        delta.charge.abs(),
        &delta.before,
        &delta.after,
        0,
    );
}

#[allow(clippy::too_many_arguments)]
fn push_trace(
    trace: &mut Vec<CanonicalTraceRowV2>,
    sequence: &mut u64,
    bar: usize,
    timestamp: i64,
    event_kind: CanonicalEventKindV2,
    symbol: Option<SymbolId>,
    quantity: f64,
    price: f64,
    fee: f64,
    before: &LinearAccountSnapshotV1,
    after: &LinearAccountSnapshotV1,
    reason_code: i32,
) {
    trace.push(CanonicalTraceRowV2 {
        sequence: *sequence,
        bar_index: BarIndex(bar as u32),
        event_timestamp_ns: TimestampNs(timestamp),
        effective_timestamp_ns: TimestampNs(timestamp),
        symbol_id: symbol,
        account_id: AccountId(0),
        package_id: None,
        order_id: None,
        event_kind,
        reason_code,
        order_status_code: -1,
        qty: quantity,
        price,
        fee,
        cash_before: before.cash,
        cash_after: after.cash,
        position_before: symbol.map_or(f64::NAN, |item| before.qty[item.0 as usize]),
        position_after: symbol.map_or(f64::NAN, |item| after.qty[item.0 as usize]),
        realized_pnl_before: before.realized_pnl,
        realized_pnl_after: after.realized_pnl,
        initial_margin_before: before.initial_margin,
        initial_margin_after: after.initial_margin,
        maintenance_margin_before: before.maintenance_margin,
        maintenance_margin_after: after.maintenance_margin,
        // Internal fingerprints retain raw IEEE-754 bits for transactional
        // staleness. Canonical traces use the normalized account hash so an
        // independent oracle can compare the declared numeric contract.
        state_hash_before: Some(before.canonical_state_hash),
        state_hash_after: Some(after.canonical_state_hash),
    });
    *sequence = sequence
        .checked_add(1)
        .expect("canonical trace sequence overflow");
}

fn validate_input(
    timestamps_ns: &[i64],
    marks: &[f64],
    n_symbols: usize,
    fills: &[FillReplayFillV2],
    funding: &[FillReplayFundingV2],
    config: &FillReplayConfigV2,
) -> Result<(), String> {
    if timestamps_ns.is_empty()
        || n_symbols == 0
        || marks.len()
            != timestamps_ns
                .len()
                .checked_mul(n_symbols)
                .ok_or("fill replay dimensions overflow")?
        || config.n_symbols() != n_symbols
        || marks
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        || timestamps_ns
            .windows(2)
            .any(|window| window[0] >= window[1])
        || timestamps_ns.len() > u32::MAX as usize
    {
        return Err("invalid FillReplay V2 market tape".to_owned());
    }
    let mut fill_ids = BTreeSet::new();
    validate_rows(
        fills.iter().map(|row| {
            (
                row.bar_index,
                row.sequence,
                row.event_id,
                row.symbol,
                row.signed_qty,
                row.price,
                row.fee,
            )
        }),
        timestamps_ns.len(),
        n_symbols,
        &mut fill_ids,
        true,
    )?;
    let mut previous: Option<(usize, u64)> = None;
    for row in funding {
        if row.bar_index >= timestamps_ns.len()
            || row.symbol.0 as usize >= n_symbols
            || !row.rate.is_finite()
        {
            return Err("invalid FillReplay V2 funding row".to_owned());
        }
        if let Some((previous_bar, previous_sequence)) = previous
            && (row.bar_index < previous_bar
                || (row.bar_index == previous_bar && row.sequence <= previous_sequence))
        {
            return Err(
                "FillReplay V2 funding rows must be strictly sorted by bar_index then sequence"
                    .to_owned(),
            );
        }
        previous = Some((row.bar_index, row.sequence));
    }
    Ok(())
}

fn validate_rows<I>(
    rows: I,
    n_bars: usize,
    n_symbols: usize,
    ids: &mut BTreeSet<u64>,
    require_nonzero_quantity: bool,
) -> Result<(), String>
where
    I: IntoIterator<Item = (usize, u64, u64, SymbolId, f64, f64, f64)>,
{
    let mut previous: Option<(usize, u64)> = None;
    for (bar, sequence, event_id, symbol, quantity, price, fee) in rows {
        if bar >= n_bars
            || symbol.0 as usize >= n_symbols
            || !quantity.is_finite()
            || (require_nonzero_quantity && quantity.abs() <= EPSILON)
            || !price.is_finite()
            || price <= 0.0
            || !fee.is_finite()
            || fee < 0.0
            || !ids.insert(event_id)
        {
            return Err("invalid FillReplay V2 fill row".to_owned());
        }
        if let Some((previous_bar, previous_sequence)) = previous
            && (bar < previous_bar || (bar == previous_bar && sequence <= previous_sequence))
        {
            return Err(
                "FillReplay V2 fill rows must be strictly sorted by bar_index then sequence"
                    .to_owned(),
            );
        }
        previous = Some((bar, sequence));
    }
    Ok(())
}

fn reject_message(code: AccountingRejectCodeV1) -> String {
    code.name().to_owned()
}

#[cfg(test)]
mod tests {
    use super::{
        FillReplayConfigV2, FillReplayFillV2, FillReplayFundingV2, FillReplayOutputProfileV2,
        FundingPhaseV1, run_fill_replay_v2,
    };
    use quantbt_domain::ids::SymbolId;

    fn config() -> FillReplayConfigV2 {
        FillReplayConfigV2::new(
            1_000.0,
            0.005,
            vec![1.0, 2.0],
            vec![5.0, 5.0],
            0.001,
            FundingPhaseV1::AfterFillsAtClose,
        )
        .unwrap()
    }

    #[test]
    fn fill_replay_handles_scale_reduce_reverse_funding_and_multi_symbol_margin() {
        let result = run_fill_replay_v2(
            &[1, 2, 3],
            &[100.0, 50.0, 110.0, 45.0, 90.0, 60.0],
            2,
            &[
                FillReplayFillV2 {
                    bar_index: 0,
                    sequence: 0,
                    event_id: 1,
                    symbol: SymbolId(0),
                    signed_qty: 2.0,
                    price: 100.0,
                    fee: 0.2,
                },
                FillReplayFillV2 {
                    bar_index: 1,
                    sequence: 0,
                    event_id: 2,
                    symbol: SymbolId(1),
                    signed_qty: -1.0,
                    price: 45.0,
                    fee: 0.09,
                },
                FillReplayFillV2 {
                    bar_index: 2,
                    sequence: 0,
                    event_id: 3,
                    symbol: SymbolId(0),
                    signed_qty: -3.0,
                    price: 90.0,
                    fee: 0.27,
                },
            ],
            &[FillReplayFundingV2 {
                bar_index: 1,
                sequence: 0,
                event_id: 8,
                symbol: SymbolId(0),
                rate: 0.001,
            }],
            config(),
            FillReplayOutputProfileV2::Audit,
        )
        .unwrap();
        let super::FillReplayResultV2::Audit(audit) = result else {
            panic!("expected audit");
        };
        assert_eq!(audit.compact.n_symbols, 2);
        assert_eq!(audit.compact.score.accepted_fill_count, 3);
        assert_eq!(audit.compact.score.accepted_funding_count, 1);
        assert!(audit.trace.iter().any(|row| row.event_kind as u16 == 2));
        assert_eq!(audit.compact.positions.len(), 6);
    }

    #[test]
    fn duplicate_funding_id_is_rejected_without_duplicate_cash_mutation() {
        let result = run_fill_replay_v2(
            &[1, 2],
            &[100.0, 100.0, 100.0, 100.0],
            2,
            &[FillReplayFillV2 {
                bar_index: 0,
                sequence: 0,
                event_id: 1,
                symbol: SymbolId(0),
                signed_qty: 1.0,
                price: 100.0,
                fee: 0.0,
            }],
            &[
                FillReplayFundingV2 {
                    bar_index: 1,
                    sequence: 0,
                    event_id: 2,
                    symbol: SymbolId(0),
                    rate: 0.001,
                },
                FillReplayFundingV2 {
                    bar_index: 1,
                    sequence: 1,
                    event_id: 2,
                    symbol: SymbolId(0),
                    rate: 0.001,
                },
            ],
            config(),
            FillReplayOutputProfileV2::Audit,
        )
        .unwrap();
        let super::FillReplayResultV2::Audit(audit) = result else {
            panic!("expected audit");
        };
        assert_eq!(audit.compact.score.accepted_funding_count, 1);
        assert_eq!(audit.compact.score.rejected_funding_count, 1);
        assert!((audit.compact.score.total_funding - 0.1).abs() <= 1e-12);
    }

    #[test]
    fn liquidation_is_an_executable_fill_sequence() {
        let result = run_fill_replay_v2(
            &[1, 2],
            &[100.0, 10.0, 1.0, 10.0],
            2,
            &[
                FillReplayFillV2 {
                    bar_index: 0,
                    sequence: 0,
                    event_id: 1,
                    symbol: SymbolId(0),
                    signed_qty: 20.0,
                    price: 100.0,
                    fee: 0.0,
                },
                FillReplayFillV2 {
                    bar_index: 0,
                    sequence: 1,
                    event_id: 2,
                    symbol: SymbolId(1),
                    signed_qty: 5.0,
                    price: 10.0,
                    fee: 0.0,
                },
            ],
            &[],
            config(),
            FillReplayOutputProfileV2::Audit,
        )
        .unwrap();
        let super::FillReplayResultV2::Audit(audit) = result else {
            panic!("expected audit");
        };
        assert!(audit.compact.score.liquidated);
        assert!(audit.trace.iter().any(|row| row.event_kind as u16 == 17));
    }
}
