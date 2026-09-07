//! Direct close-target execution for the Rust vectorized authority.
//!
//! This module deliberately does **not** lower a target matrix into
//! `OrderCommandV5`.  A static target rebalance is a different workload from
//! an order lifecycle: it resolves an effective target, calculates the delta
//! from the actual position, applies the frozen close-target accounting
//! contract, and records one compact/audit result in the same Rust pass.

use std::sync::Arc;

use quantbt_engine::{
    AuditRetentionV1, MetricContractV2, MetricFinishInputV2, NativeAuditOutputV1,
    NativeCompactOutputV1, NativeEventOutputV1, NativeExecutionOutputV1, NativeFillOutputV1,
    NativePathOutputV1, NativeScoreOutputV1, OnlineMetricReducerV2, OutputRequirementsV1,
    StaticOutputProfile,
};

use crate::{
    FingerprintWriter, NativeExecutionTemplateV1, NativeOutputProfileV1, hex_fingerprint,
    terminal_fingerprint_v2,
};

/// Immutable schema for direct target requests. It is separate from the
/// command-tape request ABI because a close-target run has no order arena.
pub const DIRECT_TARGET_REQUEST_VERSION_V1: u16 = 1;
pub const DIRECT_TARGET_REQUEST_SCHEMA_V1: &str = "native-direct-target-request-v1";

/// The frozen `close_target_v2` timing. The first bar is an account snapshot;
/// every later target is accepted/rejected and, if accepted, filled at that
/// bar's close. Next-open/next-close target timings intentionally reject here
/// until their independent contracts have an oracle and parity corpus.
pub const TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE: u8 = 0;

/// Target-input contracts must remain distinct. Their raw matrices are not
/// interchangeable even when a particular example happens to yield the same
/// units.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum DirectTargetKindV1 {
    Units = 0,
    Notional = 1,
    Weight = 2,
    EquityFraction = 3,
    /// Legacy ``%_equity`` is a transition-sized target contract, not a
    /// per-bar equity-fraction rebalance.  It recalculates units only when
    /// the processed raw signal changes and therefore retains the accepted
    /// quantity between transitions.
    PctEquityTransition = 4,
}

/// Shared-account admission policies for the portfolio direct-target route.
///
/// These policies deliberately live beside the close-target executor rather
/// than the Python portfolio planner: a planner may choose the target matrix,
/// but it must never own the resulting cash, margin, fee, or liquidation
/// state.  The numeric IDs are immutable request input and are included in
/// the request fingerprint.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum PortfolioAdmissionPolicyV1 {
    /// Compatibility ordering: apply each final target in normalized symbol
    /// order against the one shared account.
    SequentialLegacy = 0,
    /// Commit all valid reductions before considering any risk-increasing
    /// transition.  A later increase can never block an earlier reduction.
    ReduceFirstThenIncrease = 1,
    /// Commit reductions, then scale only the remaining risk increases to
    /// available margin.  Lot residual allocation is stable by symbol order.
    ProRataToAvailableMargin = 2,
    /// Preview the complete rebalance on a cloned shared account and commit
    /// every leg only when the whole transaction is admissible.
    AllOrNoneRebalance = 3,
}

impl TryFrom<u8> for PortfolioAdmissionPolicyV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::SequentialLegacy),
            1 => Ok(Self::ReduceFirstThenIncrease),
            2 => Ok(Self::ProRataToAvailableMargin),
            3 => Ok(Self::AllOrNoneRebalance),
            _ => Err("unsupported shared portfolio admission policy".to_owned()),
        }
    }
}

impl PortfolioAdmissionPolicyV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::SequentialLegacy => "sequential_legacy",
            Self::ReduceFirstThenIncrease => "reduce_first_then_increase",
            Self::ProRataToAvailableMargin => "pro_rata_to_available_margin",
            Self::AllOrNoneRebalance => "all_or_none_rebalance",
        }
    }
}

impl TryFrom<u8> for DirectTargetKindV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Units),
            1 => Ok(Self::Notional),
            2 => Ok(Self::Weight),
            3 => Ok(Self::EquityFraction),
            4 => Ok(Self::PctEquityTransition),
            _ => Err("unsupported native direct target kind".to_owned()),
        }
    }
}

impl DirectTargetKindV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Units => "target_units_v1",
            Self::Notional => "target_notional_v1",
            Self::Weight => "target_weight_v1",
            Self::EquityFraction => "equity_fraction_v1",
            Self::PctEquityTransition => "pct_equity_transition_v1",
        }
    }
}

/// Explicit handling for an invalid target value. The certified default is
/// fail-closed at request construction; compatibility policies remain explicit
/// and are part of the immutable request fingerprint.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum InvalidTargetPolicyV1 {
    RejectRun = 0,
    HoldPrior = 1,
    Flatten = 2,
    SkipBar = 3,
}

impl TryFrom<u8> for InvalidTargetPolicyV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::RejectRun),
            1 => Ok(Self::HoldPrior),
            2 => Ok(Self::Flatten),
            3 => Ok(Self::SkipBar),
            _ => Err("unsupported invalid target policy".to_owned()),
        }
    }
}

impl InvalidTargetPolicyV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::RejectRun => "reject_run",
            Self::HoldPrior => "hold_prior",
            Self::Flatten => "flatten",
            Self::SkipBar => "skip_bar",
        }
    }
}

/// Stable direct-target rejection codes. `1` intentionally preserves the
/// legacy Numba insufficient-margin diagnostic code for valid close-target
/// inputs. The additive codes explain newly explicit preflight constraints.
pub const TARGET_REJECT_NONE: i64 = 0;
pub const TARGET_REJECT_INSUFFICIENT_MARGIN: i64 = 1;
pub const TARGET_REJECT_INVALID_TARGET: i64 = 2;
pub const TARGET_REJECT_NON_TRADABLE: i64 = 3;
pub const TARGET_REJECT_STALE_PRICE: i64 = 4;
/// The requested portfolio rebalance was intentionally left untouched because
/// one or more legs failed the atomic preview.  This is distinct from a
/// per-symbol insufficient-margin rejection.
pub const TARGET_REJECT_ATOMIC_ROLLBACK: i64 = 5;
/// A valid target was resized under the explicit pro-rata policy.  It remains
/// an accepted target (not a rejected order); audit consumers can distinguish
/// it from an exact full-target fill without inferring from quantities.
pub const TARGET_ADJUSTED_PRO_RATA: i64 = 6;

pub const TARGET_LIQ_NONE: i64 = 0;
pub const TARGET_LIQ_INTRABAR: i64 = 1;
pub const TARGET_LIQ_AFTER_FUNDING: i64 = 2;
pub const TARGET_LIQ_AFTER_REBALANCE: i64 = 3;

const EVENT_FILL: i64 = 6;
const EVENT_REJECT: i64 = 7;
const STATUS_FILLED: i64 = 4;
const STATUS_REJECTED: i64 = 7;
const FILL_REASON_CLOSE_TARGET_SAME_CLOSE: i64 = 20;

/// Bounded target-decision ledger. It is a diagnostic artifact, not a second
/// account ledger: fills, funding, margin and terminal state remain in the
/// common native output above it.
#[derive(Clone, Debug, Default)]
pub struct DirectTargetAuditV1 {
    pub bar: Vec<i64>,
    pub symbol: Vec<i64>,
    pub requested_units: Vec<f64>,
    pub accepted_units: Vec<f64>,
    pub rejection_code: Vec<i64>,
    pub decision_count: usize,
    pub rejected_decision_count: usize,
    pub detail_retention: AuditRetentionV1,
}

impl DirectTargetAuditV1 {
    fn with_detail_limit(detail_row_limit: usize) -> Self {
        Self {
            detail_retention: AuditRetentionV1::new(detail_row_limit),
            ..Self::default()
        }
    }

    fn record(
        &mut self,
        bar: usize,
        symbol: usize,
        requested_units: f64,
        accepted_units: f64,
        rejection_code: i64,
    ) {
        if !self.detail_retention.retain_next() {
            return;
        }
        self.bar.push(bar as i64);
        self.symbol.push(symbol as i64);
        self.requested_units.push(requested_units);
        self.accepted_units.push(accepted_units);
        self.rejection_code.push(rejection_code);
    }
}

/// Immutable input for one direct target pass over a prepared market/template.
/// All vectors are bar-major and owned by Rust after construction.
#[derive(Clone)]
pub struct DirectTargetRequestV1 {
    template: Arc<NativeExecutionTemplateV1>,
    targets: Box<[f64]>,
    kind: DirectTargetKindV1,
    timing: u8,
    invalid_target_policy: InvalidTargetPolicyV1,
    tradable: Box<[bool]>,
    stale: Box<[bool]>,
    qty_step: Box<[f64]>,
    min_qty: Box<[f64]>,
    min_notional: Box<[f64]>,
    equity_fraction: Box<[f64]>,
    output: NativeOutputProfileV1,
    audit_detail_row_limit: Option<usize>,
    fingerprint: [u8; 32],
}

impl DirectTargetRequestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_template(
        template: Arc<NativeExecutionTemplateV1>,
        targets: Vec<f64>,
        kind: DirectTargetKindV1,
        timing: u8,
        invalid_target_policy: InvalidTargetPolicyV1,
        tradable: Vec<bool>,
        stale: Vec<bool>,
        qty_step: Vec<f64>,
        min_qty: Vec<f64>,
        min_notional: Vec<f64>,
        equity_fraction: Vec<f64>,
        output: NativeOutputProfileV1,
    ) -> Result<Self, String> {
        if timing != TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE {
            return Err(
                "native direct target currently certifies only close_target_v2_same_close"
                    .to_owned(),
            );
        }
        let width = template
            .bar_count()
            .checked_mul(template.n_symbols())
            .ok_or_else(|| "native direct target dimensions overflow".to_owned())?;
        let symbols = template.n_symbols();
        if targets.len() != width
            || tradable.len() != width
            || stale.len() != width
            || qty_step.len() != symbols
            || min_qty.len() != symbols
            || min_notional.len() != symbols
            || equity_fraction.len() != symbols
        {
            return Err(
                "native direct target arrays do not match the prepared template".to_owned(),
            );
        }
        if qty_step
            .iter()
            .chain(min_qty.iter())
            .chain(min_notional.iter())
            .chain(equity_fraction.iter())
            .any(|value| !value.is_finite() || *value < 0.0)
        {
            return Err(
                "native direct target constraints must be finite and non-negative".to_owned(),
            );
        }
        if invalid_target_policy == InvalidTargetPolicyV1::RejectRun
            && targets.iter().any(|value| !value.is_finite())
        {
            return Err(
                "native direct target contains a non-finite value under reject_run policy"
                    .to_owned(),
            );
        }
        let audit_detail_row_limit =
            OutputRequirementsV1::resolve(static_profile(output)).detail_row_limit;
        let mut request = Self {
            template,
            targets: targets.into_boxed_slice(),
            kind,
            timing,
            invalid_target_policy,
            tradable: tradable.into_boxed_slice(),
            stale: stale.into_boxed_slice(),
            qty_step: qty_step.into_boxed_slice(),
            min_qty: min_qty.into_boxed_slice(),
            min_notional: min_notional.into_boxed_slice(),
            equity_fraction: equity_fraction.into_boxed_slice(),
            output,
            audit_detail_row_limit,
            fingerprint: [0; 32],
        };
        request.fingerprint = request.compute_fingerprint();
        Ok(request)
    }

    pub fn with_audit_detail_limit(mut self, detail_row_limit: usize) -> Result<Self, String> {
        if self.output != NativeOutputProfileV1::Audit {
            return Err(
                "audit detail limit is valid only for audit direct-target output".to_owned(),
            );
        }
        self.audit_detail_row_limit = Some(detail_row_limit);
        self.fingerprint = self.compute_fingerprint();
        Ok(self)
    }

    #[must_use]
    pub const fn output_profile(&self) -> NativeOutputProfileV1 {
        self.output
    }

    #[must_use]
    pub const fn kind(&self) -> DirectTargetKindV1 {
        self.kind
    }

    #[must_use]
    pub const fn timing(&self) -> u8 {
        self.timing
    }

    #[must_use]
    pub const fn invalid_target_policy(&self) -> InvalidTargetPolicyV1 {
        self.invalid_target_policy
    }

    #[must_use]
    pub const fn audit_detail_row_limit(&self) -> Option<usize> {
        self.audit_detail_row_limit
    }

    #[must_use]
    pub fn template(&self) -> &Arc<NativeExecutionTemplateV1> {
        &self.template
    }

    #[must_use]
    pub const fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_fingerprint(self.fingerprint)
    }

    #[must_use]
    pub fn request_bytes(&self) -> usize {
        self.targets.len() * std::mem::size_of::<f64>()
            + self.tradable.len() * std::mem::size_of::<bool>()
            + self.stale.len() * std::mem::size_of::<bool>()
            + (self.qty_step.len()
                + self.min_qty.len()
                + self.min_notional.len()
                + self.equity_fraction.len())
                * std::mem::size_of::<f64>()
    }

    pub fn execute(&self) -> Result<DirectTargetExecutionResultV1, String> {
        execute_direct_target(self)
    }

    fn requirements(&self) -> OutputRequirementsV1 {
        match self.audit_detail_row_limit {
            Some(limit) => OutputRequirementsV1::audit_with_detail_limit(limit),
            None => OutputRequirementsV1::resolve(static_profile(self.output)),
        }
    }

    fn target_at(&self, bar: usize, symbol: usize) -> f64 {
        self.targets[bar * self.template.n_symbols() + symbol]
    }

    fn flag_at(flags: &[bool], n_symbols: usize, bar: usize, symbol: usize) -> bool {
        flags[bar * n_symbols + symbol]
    }

    fn compute_fingerprint(&self) -> [u8; 32] {
        let mut hash = FingerprintWriter::new();
        hash.bytes(DIRECT_TARGET_REQUEST_SCHEMA_V1.as_bytes());
        hash.u16(DIRECT_TARGET_REQUEST_VERSION_V1);
        hash.bytes(&self.template.fingerprint());
        hash.u8(self.kind as u8);
        hash.u8(self.timing);
        hash.u8(self.invalid_target_policy as u8);
        hash.u8(self.output as u8);
        match self.audit_detail_row_limit {
            Some(limit) => {
                hash.bool(true);
                hash.usize(limit);
            }
            None => hash.bool(false),
        }
        hash.usize(self.targets.len());
        for value in self.targets.iter().copied() {
            hash.f64(value);
        }
        for flags in [&self.tradable, &self.stale] {
            hash.usize(flags.len());
            for value in flags.iter().copied() {
                hash.bool(value);
            }
        }
        for values in [
            &self.qty_step,
            &self.min_qty,
            &self.min_notional,
            &self.equity_fraction,
        ] {
            hash.usize(values.len());
            for value in values.iter().copied() {
                hash.f64(value);
            }
        }
        hash.finish()
    }
}

/// Completed direct-target execution plus target-specific admission evidence.
/// The common score/compact/audit output remains the one authoritative account
/// result; these extra columns only explain target acceptance.
pub struct DirectTargetExecutionResultV1 {
    pub output: NativeExecutionOutputV1,
    pub target_audit: DirectTargetAuditV1,
    pub rejected_by_bar: Option<Vec<i64>>,
    pub reject_code_by_bar: Option<Vec<i64>>,
    pub request_fingerprint: [u8; 32],
    pub template_fingerprint: [u8; 32],
    pub target_kind: DirectTargetKindV1,
    pub timing: u8,
    pub invalid_target_policy: InvalidTargetPolicyV1,
    pub command_count: usize,
    /// Public report-compatible count of the retained position trace.
    ///
    /// QuantBT's established `num_trades` counts one initial observation per
    /// symbol plus each accepted position-state transition. It is deliberately
    /// distinct from `fill_count`: forced liquidation and other lifecycle
    /// transitions can change the target trace without an ordinary fill.
    pub report_trade_count: u64,
    pub bar_count: usize,
    pub symbol_count: usize,
    pub contract_bundle_hash: u128,
    pub terminal_fingerprint: [u8; 32],
}

impl DirectTargetExecutionResultV1 {
    #[must_use]
    pub fn request_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.request_fingerprint)
    }

    #[must_use]
    pub fn template_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.template_fingerprint)
    }

    #[must_use]
    pub fn terminal_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.terminal_fingerprint)
    }

    #[must_use]
    pub fn contract_bundle_hash_hex(&self) -> String {
        format!("{:032x}", self.contract_bundle_hash)
    }
}

/// Immutable request for the Phase 67 shared-account portfolio route.
///
/// `DirectTargetRequestV1` remains the independently certified single/static
/// target contract.  This wrapper adds only portfolio admission semantics;
/// market, instrument, account, target resolution, and output retention stay
/// on the same canonical authority.  Keeping the legacy request untouched is
/// an intentional rollback and compatibility boundary.
#[derive(Clone)]
pub struct SharedPortfolioTargetRequestV1 {
    inner: DirectTargetRequestV1,
    admission_policy: PortfolioAdmissionPolicyV1,
    fingerprint: [u8; 32],
}

impl SharedPortfolioTargetRequestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_template(
        template: Arc<NativeExecutionTemplateV1>,
        targets: Vec<f64>,
        kind: DirectTargetKindV1,
        timing: u8,
        invalid_target_policy: InvalidTargetPolicyV1,
        tradable: Vec<bool>,
        stale: Vec<bool>,
        qty_step: Vec<f64>,
        min_qty: Vec<f64>,
        min_notional: Vec<f64>,
        equity_fraction: Vec<f64>,
        admission_policy: PortfolioAdmissionPolicyV1,
        output: NativeOutputProfileV1,
    ) -> Result<Self, String> {
        let inner = DirectTargetRequestV1::from_template(
            template,
            targets,
            kind,
            timing,
            invalid_target_policy,
            tradable,
            stale,
            qty_step,
            min_qty,
            min_notional,
            equity_fraction,
            output,
        )?;
        let mut request = Self {
            inner,
            admission_policy,
            fingerprint: [0; 32],
        };
        request.fingerprint = request.compute_fingerprint();
        Ok(request)
    }

    pub fn with_audit_detail_limit(mut self, detail_row_limit: usize) -> Result<Self, String> {
        self.inner = self.inner.with_audit_detail_limit(detail_row_limit)?;
        self.fingerprint = self.compute_fingerprint();
        Ok(self)
    }

    #[must_use]
    pub fn inner(&self) -> &DirectTargetRequestV1 {
        &self.inner
    }

    #[must_use]
    pub const fn admission_policy(&self) -> PortfolioAdmissionPolicyV1 {
        self.admission_policy
    }

    #[must_use]
    pub const fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_fingerprint(self.fingerprint)
    }

    #[must_use]
    pub fn request_bytes(&self) -> usize {
        self.inner.request_bytes()
    }

    pub fn execute(&self) -> Result<SharedPortfolioExecutionResultV1, String> {
        execute_shared_portfolio_target(self)
    }

    fn compute_fingerprint(&self) -> [u8; 32] {
        let mut hash = FingerprintWriter::new();
        hash.bytes(b"native-shared-portfolio-target-request-v1");
        hash.bytes(&self.inner.fingerprint());
        hash.u8(self.admission_policy as u8);
        hash.finish()
    }
}

/// Symbol-level attribution from the same single shared account run.
///
/// Fees, funding, turnover, and mark PnL are accumulated during the execution
/// pass. `realized_pnl + unrealized_pnl == mark_to_market_pnl` per symbol at
/// the terminal mark.  Execution costs remain separate so their sum, plus
/// mark PnL and initial capital, reconciles exactly to portfolio equity.
#[derive(Clone, Debug, Default)]
pub struct SharedPortfolioAttributionV1 {
    pub realized_pnl: Vec<f64>,
    pub unrealized_pnl: Vec<f64>,
    pub mark_to_market_pnl: Vec<f64>,
    pub fees: Vec<f64>,
    pub slippage: Vec<f64>,
    pub funding: Vec<f64>,
    /// Residual account write-down from the declared zero-equity liquidation
    /// contract.  It is allocated deterministically by close-mark exposure so
    /// per-symbol attribution still reconciles to forced terminal equity.
    pub liquidation_loss: Vec<f64>,
    pub turnover: Vec<f64>,
    pub final_exposure: Vec<f64>,
    pub final_initial_margin: Vec<f64>,
}

/// Completed shared-account portfolio execution.  The common execution output
/// is still the sole source of portfolio equity, fill, event, funding, margin,
/// and liquidation state; target audit and attribution only explain that run.
pub struct SharedPortfolioExecutionResultV1 {
    pub output: NativeExecutionOutputV1,
    pub target_audit: DirectTargetAuditV1,
    pub attribution: SharedPortfolioAttributionV1,
    pub rejected_by_bar: Option<Vec<i64>>,
    pub reject_code_by_bar: Option<Vec<i64>>,
    pub request_fingerprint: [u8; 32],
    pub template_fingerprint: [u8; 32],
    pub target_kind: DirectTargetKindV1,
    pub timing: u8,
    pub invalid_target_policy: InvalidTargetPolicyV1,
    pub admission_policy: PortfolioAdmissionPolicyV1,
    pub command_count: usize,
    pub bar_count: usize,
    pub symbol_count: usize,
    pub contract_bundle_hash: u128,
    pub terminal_fingerprint: [u8; 32],
}

impl SharedPortfolioExecutionResultV1 {
    #[must_use]
    pub fn request_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.request_fingerprint)
    }

    #[must_use]
    pub fn template_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.template_fingerprint)
    }

    #[must_use]
    pub fn terminal_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.terminal_fingerprint)
    }

    #[must_use]
    pub fn contract_bundle_hash_hex(&self) -> String {
        format!("{:032x}", self.contract_bundle_hash)
    }
}

enum TargetResolution {
    Value {
        requested_units: f64,
        target_units: f64,
    },
    Hold {
        rejection_code: i64,
    },
}

fn static_profile(output: NativeOutputProfileV1) -> StaticOutputProfile {
    match output {
        NativeOutputProfileV1::Score => StaticOutputProfile::Score,
        NativeOutputProfileV1::Compact => StaticOutputProfile::Compact,
        NativeOutputProfileV1::Audit => StaticOutputProfile::Audit,
    }
}

fn record_public_position_transitions(previous: &mut [f64], current: &[f64], count: &mut u64) {
    for (previous_value, current_value) in previous.iter_mut().zip(current.iter().copied()) {
        if *previous_value != current_value {
            *count = count.saturating_add(1);
            *previous_value = current_value;
        }
    }
}

/// Count the legacy public `%_equity` position trace.  Its historical result
/// surface exposes processed strategy weights, rather than accepted units, so
/// a rejected margin admission remains a visible signal transition.  Keep the
/// calculation separate from lifecycle/fill counters used by direct-target
/// accounting and audit output.
fn processed_signal_trade_count(
    request: &DirectTargetRequestV1,
    n_bars: usize,
    n_symbols: usize,
) -> u64 {
    let mut count = n_symbols as u64;
    for bar in 1..n_bars {
        for symbol in 0..n_symbols {
            if request.target_at(bar, symbol) != request.target_at(bar - 1, symbol) {
                count = count.saturating_add(1);
            }
        }
    }
    count
}

#[allow(clippy::too_many_lines)]
fn execute_direct_target(
    request: &DirectTargetRequestV1,
) -> Result<DirectTargetExecutionResultV1, String> {
    let requirements = request.requirements();
    requirements.validate()?;
    let template = request.template();
    let market = template.market();
    let account = template.account();
    let instruments = template.instruments();
    let n_bars = template.bar_count();
    let n_symbols = template.n_symbols();
    let market_start = template.market_range().0;
    let contract_sizes = instruments.contract_sizes();
    let leverages = instruments.leverages();
    let fee_rates = instruments.fee_rates();

    validate_market_slice(market, market_start, n_bars, n_symbols)?;

    let mut equity = account.initial_capital;
    let mut current_positions = vec![0.0; n_symbols];
    let metric_contract = MetricContractV2::default();
    let mut metric_reducer = OnlineMetricReducerV2::new(metric_contract, equity)?;
    let mut score = NativeScoreOutputV1 {
        final_equity: equity,
        metric_contract,
        ..NativeScoreOutputV1::default()
    };
    let mut paths = requirements
        .retain_paths
        .then(|| NativePathOutputV1::with_capacity(n_bars, n_symbols));
    let mut fills = requirements.retain_detail.then(NativeFillOutputV1::default);
    let mut events = requirements
        .retain_detail
        .then(NativeEventOutputV1::default);
    let mut execution_retention = requirements
        .retain_detail
        .then(|| AuditRetentionV1::new(requirements.detail_row_limit.unwrap_or(0)));
    let mut target_audit = if requirements.retain_detail {
        DirectTargetAuditV1::with_detail_limit(requirements.detail_row_limit.unwrap_or(0))
    } else {
        DirectTargetAuditV1::default()
    };
    let mut rejected_by_bar = requirements.retain_paths.then(|| vec![0_i64; n_bars]);
    let mut reject_code_by_bar = requirements.retain_paths.then(|| vec![0_i64; n_bars]);
    let mut liquidated = false;
    let mut liquidation_bar = -1_i64;
    let mut liquidation_reason = TARGET_LIQ_NONE;
    let mut command_count = 0_usize;
    let pct_equity_transition = request.kind == DirectTargetKindV1::PctEquityTransition;
    // Public `num_trades` includes the initial position snapshot for every
    // symbol, even when the first target is flat.
    let mut report_previous_positions = current_positions.clone();
    let mut report_trade_count = n_symbols as u64;

    // Bar zero is always a frozen account snapshot under close_target_v2.
    record_path(&mut paths, equity, &current_positions, 0.0, 0.0, 0.0, 0.0);
    metric_reducer.observe(market.timestamps_ns[market_start], equity, 0.0)?;

    for bar in 1..n_bars {
        let mut fee_bar = 0.0;
        let mut turnover_bar = 0.0;
        let mut funding_bar = 0.0;
        let source_bar = market_start + bar;

        if liquidated {
            record_public_position_transitions(
                &mut report_previous_positions,
                &current_positions,
                &mut report_trade_count,
            );
            record_path(&mut paths, 0.0, &current_positions, 0.0, 0.0, 0.0, 0.0);
            metric_reducer.observe(market.timestamps_ns[source_bar], 0.0, 0.0)?;
            continue;
        }

        // Mark carried positions close-to-close before any same-close target
        // is resolved. This ordering is the frozen Numba close_target_v2
        // contract, not an event-lifecycle clock.
        for symbol in 0..n_symbols {
            let position = current_positions[symbol];
            if position != 0.0 {
                equity += position
                    * (market_value(market, source_bar, n_symbols, symbol, 3)
                        - market_value(market, source_bar - 1, n_symbols, symbol, 3))
                    * contract_sizes[symbol];
            }
        }

        let mut worst_equity = equity;
        let mut worst_maintenance = 0.0;
        for symbol in 0..n_symbols {
            let position = current_positions[symbol];
            if position == 0.0 {
                continue;
            }
            let close = market_value(market, source_bar, n_symbols, symbol, 3);
            let worst = if position > 0.0 {
                market_value(market, source_bar, n_symbols, symbol, 2)
            } else {
                market_value(market, source_bar, n_symbols, symbol, 1)
            };
            worst_equity += position * (worst - close) * contract_sizes[symbol];
            worst_maintenance +=
                position.abs() * worst * contract_sizes[symbol] * account.maintenance_ratio;
        }
        if worst_maintenance > 0.0 && worst_equity <= worst_maintenance {
            liquidated = true;
            liquidation_bar = bar as i64;
            liquidation_reason = TARGET_LIQ_INTRABAR;
            equity = 0.0;
            current_positions.fill(0.0);
            record_public_position_transitions(
                &mut report_previous_positions,
                &current_positions,
                &mut report_trade_count,
            );
            record_path(
                &mut paths,
                equity,
                &current_positions,
                fee_bar,
                turnover_bar,
                funding_bar,
                0.0,
            );
            metric_reducer.observe(market.timestamps_ns[source_bar], equity, 0.0)?;
            continue;
        }

        if market.funding_mask[source_bar] && account.use_funding {
            for symbol in 0..n_symbols {
                let position = current_positions[symbol];
                if position != 0.0 {
                    let close = market_value(market, source_bar, n_symbols, symbol, 3);
                    let funding = market_value(market, source_bar, n_symbols, symbol, 6);
                    let cost = position * close * contract_sizes[symbol] * funding;
                    equity -= cost;
                    funding_bar += cost;
                }
            }
        }

        let close_maintenance_before = maintenance_margin(
            &current_positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            account.maintenance_ratio,
        );
        if close_maintenance_before > 0.0 && equity <= close_maintenance_before {
            liquidated = true;
            liquidation_bar = bar as i64;
            liquidation_reason = TARGET_LIQ_AFTER_FUNDING;
            equity = 0.0;
            current_positions.fill(0.0);
            record_public_position_transitions(
                &mut report_previous_positions,
                &current_positions,
                &mut report_trade_count,
            );
            record_path(
                &mut paths,
                equity,
                &current_positions,
                fee_bar,
                turnover_bar,
                funding_bar,
                0.0,
            );
            // Numba retains funding charged at this bar even when the
            // subsequent close-margin check liquidates the account.
            score.total_funding += funding_bar;
            metric_reducer.observe(market.timestamps_ns[source_bar], equity, 0.0)?;
            continue;
        }

        // Weight/equity-fraction inputs share this immutable pre-rebalance
        // close snapshot. Accepted fills later in the symbol loop cannot make
        // a target for another symbol depend on iteration order. The frozen
        // legacy pct-equity contract is intentionally different: it resolves
        // each raw-signal transition against the live account value after
        // earlier same-bar accepted transitions, matching _engine_pct_equity.
        let equity_snapshot = equity;
        let current_initial_margin = initial_margin(
            &current_positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            leverages,
        );
        let mut available = (equity - current_initial_margin).max(0.0);

        for symbol in 0..n_symbols {
            let close = market_value(market, source_bar, n_symbols, symbol, 3);
            let raw = request.target_at(bar, symbol);
            if pct_equity_transition && raw == request.target_at(bar - 1, symbol) {
                // `%_equity` is transition-sized. A rejected transition is
                // not retried while the raw processed signal stays unchanged.
                continue;
            }
            // A static units tape commonly holds the previous accepted target
            // for long stretches. With no quantity constraints, a finite raw
            // target exactly equal to the current position is an observable
            // no-op under the frozen contract: the reference path resolves it,
            // sees a zero delta, and records no decision, fill, rejection, or
            // audit row. Skip only that redundant target-resolution work.
            //
            // This never skips the surrounding bar-level MTM, funding, margin,
            // maintenance, or liquidation checks. Any constraint, alternate
            // target kind, non-finite input, or changed target remains on the
            // general authoritative path below.
            if request.kind == DirectTargetKindV1::Units
                && request.qty_step[symbol] == 0.0
                && request.min_qty[symbol] == 0.0
                && request.min_notional[symbol] == 0.0
                && raw.is_finite()
                && raw == current_positions[symbol]
            {
                continue;
            }
            let resolution = resolve_target(
                raw,
                request.kind,
                request.invalid_target_policy,
                close,
                contract_sizes[symbol],
                if pct_equity_transition {
                    equity
                } else {
                    equity_snapshot
                },
                request.equity_fraction[symbol],
                request.qty_step[symbol],
                request.min_qty[symbol],
                request.min_notional[symbol],
            )?;
            let (requested_units, target_units) = match resolution {
                TargetResolution::Value {
                    requested_units,
                    target_units,
                } => (requested_units, target_units),
                TargetResolution::Hold { rejection_code } => {
                    // A non-default invalid-target policy is observable and
                    // never silently converted into a valid no-op. It leaves
                    // the position unchanged but emits the same bounded
                    // admission evidence as another rejected target.
                    let order_id = direct_target_order_id(bar, symbol, n_symbols)?;
                    target_audit.decision_count = target_audit.decision_count.saturating_add(1);
                    target_audit.rejected_decision_count =
                        target_audit.rejected_decision_count.saturating_add(1);
                    score.rejected_count = score.rejected_count.saturating_add(1);
                    score.event_count = score.event_count.saturating_add(1);
                    if let Some(values) = rejected_by_bar.as_mut() {
                        values[bar] = values[bar].saturating_add(1);
                    }
                    if let Some(values) = reject_code_by_bar.as_mut() {
                        values[bar] = rejection_code;
                    }
                    append_rejection_event(
                        &mut events,
                        &mut execution_retention,
                        bar,
                        order_id,
                        symbol,
                        rejection_code,
                    );
                    if requirements.retain_detail {
                        target_audit.record(
                            bar,
                            symbol,
                            raw,
                            current_positions[symbol],
                            rejection_code,
                        );
                    }
                    continue;
                }
            };
            let delta = target_units - current_positions[symbol];
            if delta.abs() < 1.0e-12 {
                continue;
            }

            command_count = command_count.saturating_add(1);
            target_audit.decision_count = target_audit.decision_count.saturating_add(1);
            let mut rejection_code = TARGET_REJECT_NONE;
            if !DirectTargetRequestV1::flag_at(&request.tradable, n_symbols, bar, symbol) {
                rejection_code = TARGET_REJECT_NON_TRADABLE;
            } else if DirectTargetRequestV1::flag_at(&request.stale, n_symbols, bar, symbol) {
                rejection_code = TARGET_REJECT_STALE_PRICE;
            }

            let order_id = direct_target_order_id(bar, symbol, n_symbols)?;
            if rejection_code == TARGET_REJECT_NONE {
                let execution_price = if delta > 0.0 {
                    close * (1.0 + account.slippage_rate)
                } else {
                    close * (1.0 - account.slippage_rate)
                };
                let trade_notional = delta.abs() * execution_price * contract_sizes[symbol];
                let fee_cost = trade_notional * fee_rates[symbol];
                let slippage_cost =
                    delta.abs() * (execution_price - close).abs() * contract_sizes[symbol];
                let old_initial_margin =
                    current_positions[symbol].abs() * close * contract_sizes[symbol]
                        / leverages[symbol];
                let new_initial_margin =
                    target_units.abs() * execution_price * contract_sizes[symbol]
                        / leverages[symbol];
                let margin_delta = new_initial_margin - old_initial_margin;
                // Legacy `%_equity` lets a reduction release margin into the
                // same bar's availability without clipping it to zero. The
                // close-target direct contracts retain their existing
                // conservative increase-only admission rule.
                let required = if pct_equity_transition {
                    fee_cost + slippage_cost + margin_delta
                } else {
                    fee_cost + slippage_cost + margin_delta.max(0.0)
                };
                if required > available {
                    rejection_code = TARGET_REJECT_INSUFFICIENT_MARGIN;
                } else {
                    equity -= fee_cost + slippage_cost;
                    current_positions[symbol] = target_units;
                    fee_bar += fee_cost;
                    turnover_bar += trade_notional;
                    available = if pct_equity_transition {
                        available - fee_cost - slippage_cost - margin_delta
                    } else {
                        (available - fee_cost - slippage_cost - margin_delta).max(0.0)
                    };
                    score.fill_count = score.fill_count.saturating_add(1);
                    score.event_count = score.event_count.saturating_add(1);
                    append_fill_and_event(
                        &mut fills,
                        &mut events,
                        &mut execution_retention,
                        bar,
                        order_id,
                        symbol,
                        delta,
                        execution_price,
                        fee_cost,
                    );
                }
            }

            if rejection_code != TARGET_REJECT_NONE {
                score.rejected_count = score.rejected_count.saturating_add(1);
                score.event_count = score.event_count.saturating_add(1);
                target_audit.rejected_decision_count =
                    target_audit.rejected_decision_count.saturating_add(1);
                if let Some(values) = rejected_by_bar.as_mut() {
                    values[bar] = values[bar].saturating_add(1);
                }
                if let Some(values) = reject_code_by_bar.as_mut() {
                    values[bar] = rejection_code;
                }
                append_rejection_event(
                    &mut events,
                    &mut execution_retention,
                    bar,
                    order_id,
                    symbol,
                    rejection_code,
                );
            }
            if requirements.retain_detail {
                target_audit.record(
                    bar,
                    symbol,
                    requested_units,
                    current_positions[symbol],
                    rejection_code,
                );
            }
        }

        let close_initial_margin = initial_margin(
            &current_positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            leverages,
        );
        let close_maintenance = maintenance_margin(
            &current_positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            account.maintenance_ratio,
        );
        if !pct_equity_transition && close_maintenance > 0.0 && equity <= close_maintenance {
            liquidated = true;
            liquidation_bar = bar as i64;
            liquidation_reason = TARGET_LIQ_AFTER_REBALANCE;
            equity = 0.0;
            current_positions.fill(0.0);
            record_public_position_transitions(
                &mut report_previous_positions,
                &current_positions,
                &mut report_trade_count,
            );
            record_path(
                &mut paths,
                equity,
                &current_positions,
                fee_bar,
                turnover_bar,
                funding_bar,
                0.0,
            );
            // Costs/funding committed before the post-rebalance liquidation
            // remain part of the canonical per-bar accounting arrays.
            score.total_fee += fee_bar;
            score.total_turnover += turnover_bar;
            score.total_funding += funding_bar;
            metric_reducer.observe(market.timestamps_ns[source_bar], equity, 0.0)?;
            continue;
        }

        record_public_position_transitions(
            &mut report_previous_positions,
            &current_positions,
            &mut report_trade_count,
        );
        record_path(
            &mut paths,
            equity,
            &current_positions,
            fee_bar,
            turnover_bar,
            funding_bar,
            close_initial_margin,
        );
        // `record_path` receives initial margin; append the exact maintenance
        // value after its shared path allocation has been made.
        if let Some(paths) = paths.as_mut()
            && let Some(last) = paths.maintenance_margin.last_mut()
        {
            *last = close_maintenance;
        }
        score.total_fee += fee_bar;
        score.total_turnover += turnover_bar;
        score.total_funding += funding_bar;
        score.max_initial_margin = score.max_initial_margin.max(close_initial_margin);
        score.max_maintenance_margin = score.max_maintenance_margin.max(close_maintenance);
        let gross_exposure = gross_exposure(
            &current_positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            equity,
        );
        metric_reducer.observe(market.timestamps_ns[source_bar], equity, gross_exposure)?;
    }

    if pct_equity_transition {
        // Public legacy reports count processed signal transitions, not
        // accepted fills or forced liquidations. This preserves minimum-trade
        // penalties and report metadata without changing the Rust account
        // trace retained for audit.
        report_trade_count = processed_signal_trade_count(request, n_bars, n_symbols);
    }

    score.final_equity = equity;
    score.final_positions = current_positions;
    score.liquidated = liquidated;
    score.liquidation_bar = liquidation_bar;
    score.liquidation_reason = liquidation_reason;
    score.metrics_v2 = Box::new(metric_reducer.finish(MetricFinishInputV2 {
        final_equity: score.final_equity,
        turnover: score.total_turnover,
        total_fee: score.total_fee,
        total_funding: score.total_funding,
        fill_count: score.fill_count,
        event_count: score.event_count,
        rejected_count: score.rejected_count,
        canceled_count: score.canceled_count,
        liquidated: score.liquidated,
    }));

    let output = match requirements.profile {
        StaticOutputProfile::Score => NativeExecutionOutputV1::Score(score),
        StaticOutputProfile::Compact => {
            NativeExecutionOutputV1::Compact(Box::new(NativeCompactOutputV1 {
                score,
                paths: paths.expect("compact direct target output requires paths"),
            }))
        }
        StaticOutputProfile::Audit => {
            NativeExecutionOutputV1::Audit(Box::new(NativeAuditOutputV1 {
                compact: NativeCompactOutputV1 {
                    score,
                    paths: paths.expect("audit direct target output requires paths"),
                },
                fills: fills.expect("audit direct target output requires fills"),
                events: events.expect("audit direct target output requires events"),
                detail_retention: execution_retention
                    .expect("audit direct target output requires retention"),
            }))
        }
    };
    let terminal_fingerprint = terminal_fingerprint_v2(&output);
    let contract_bundle_hash = direct_target_contract_bundle_hash(request);
    Ok(DirectTargetExecutionResultV1 {
        output,
        target_audit,
        rejected_by_bar,
        reject_code_by_bar,
        request_fingerprint: request.fingerprint(),
        template_fingerprint: request.template().fingerprint(),
        target_kind: request.kind(),
        timing: request.timing(),
        invalid_target_policy: request.invalid_target_policy(),
        command_count,
        report_trade_count,
        bar_count: n_bars,
        symbol_count: n_symbols,
        contract_bundle_hash,
        terminal_fingerprint,
    })
}

#[derive(Clone, Copy, Debug)]
struct SharedPortfolioCandidateV1 {
    symbol: usize,
    requested_units: f64,
    target_units: f64,
    preflight_rejection: i64,
}

#[derive(Clone, Copy, Debug)]
struct SharedPortfolioFillV1 {
    symbol: usize,
    delta: f64,
    price: f64,
    fee: f64,
    turnover: f64,
}

/// Mutable accounting state for one shared linear portfolio account.  This is
/// intentionally private to the direct-target executor: no per-symbol cash or
/// margin account exists, and every admission decision reads this one state.
#[derive(Clone, Debug)]
struct SharedPortfolioStateV1 {
    equity: f64,
    positions: Vec<f64>,
    /// Close-mark cost basis used only to split the already authoritative mark
    /// PnL into realized/unrealized attribution.  Slippage remains a separate
    /// execution cost, matching the frozen direct-target equity contract.
    basis_close: Vec<f64>,
    realized_pnl: Vec<f64>,
    mark_to_market_pnl: Vec<f64>,
    fees: Vec<f64>,
    slippage: Vec<f64>,
    funding: Vec<f64>,
    liquidation_loss: Vec<f64>,
    turnover: Vec<f64>,
}

impl SharedPortfolioStateV1 {
    fn new(initial_capital: f64, n_symbols: usize) -> Self {
        Self {
            equity: initial_capital,
            positions: vec![0.0; n_symbols],
            basis_close: vec![0.0; n_symbols],
            realized_pnl: vec![0.0; n_symbols],
            mark_to_market_pnl: vec![0.0; n_symbols],
            fees: vec![0.0; n_symbols],
            slippage: vec![0.0; n_symbols],
            funding: vec![0.0; n_symbols],
            liquidation_loss: vec![0.0; n_symbols],
            turnover: vec![0.0; n_symbols],
        }
    }

    fn mark_to_close(
        &mut self,
        market: &quantbt_engine::FullMarketData,
        source_bar: usize,
        n_symbols: usize,
        contract_sizes: &[f64],
    ) {
        for (symbol, contract_size) in contract_sizes.iter().copied().enumerate().take(n_symbols) {
            let position = self.positions[symbol];
            if position == 0.0 {
                continue;
            }
            let pnl = position
                * (market_value(market, source_bar, n_symbols, symbol, 3)
                    - market_value(market, source_bar - 1, n_symbols, symbol, 3))
                * contract_size;
            self.equity += pnl;
            self.mark_to_market_pnl[symbol] += pnl;
        }
    }

    fn apply_funding(
        &mut self,
        market: &quantbt_engine::FullMarketData,
        source_bar: usize,
        n_symbols: usize,
        contract_sizes: &[f64],
    ) -> f64 {
        let mut funding_bar = 0.0;
        for (symbol, contract_size) in contract_sizes.iter().copied().enumerate().take(n_symbols) {
            let position = self.positions[symbol];
            if position == 0.0 {
                continue;
            }
            let cost = position
                * market_value(market, source_bar, n_symbols, symbol, 3)
                * contract_size
                * market_value(market, source_bar, n_symbols, symbol, 6);
            self.equity -= cost;
            self.funding[symbol] += cost;
            funding_bar += cost;
        }
        funding_bar
    }

    #[allow(clippy::too_many_arguments)]
    fn apply_target(
        &mut self,
        symbol: usize,
        target_units: f64,
        market: &quantbt_engine::FullMarketData,
        source_bar: usize,
        n_symbols: usize,
        contract_sizes: &[f64],
        leverages: &[f64],
        fee_rates: &[f64],
        slippage_rate: f64,
        allow_margin_relief: bool,
    ) -> Result<Option<SharedPortfolioFillV1>, i64> {
        let current = self.positions[symbol];
        let delta = target_units - current;
        if delta.abs() < 1.0e-12 {
            return Ok(None);
        }
        let close = market_value(market, source_bar, n_symbols, symbol, 3);
        let price = if delta > 0.0 {
            close * (1.0 + slippage_rate)
        } else {
            close * (1.0 - slippage_rate)
        };
        let turnover = delta.abs() * price * contract_sizes[symbol];
        let fee = turnover * fee_rates[symbol];
        let slippage = delta.abs() * (price - close).abs() * contract_sizes[symbol];
        let old_initial = current.abs() * close * contract_sizes[symbol] / leverages[symbol];
        let new_initial = target_units.abs() * price * contract_sizes[symbol] / leverages[symbol];
        let margin_delta = new_initial - old_initial;
        let available = (self.equity
            - initial_margin(
                &self.positions,
                market,
                source_bar,
                n_symbols,
                contract_sizes,
                leverages,
            ))
        .max(0.0);
        let required = fee + slippage + margin_delta.max(0.0);
        if !allow_margin_relief && required > available + 1.0e-12 {
            return Err(TARGET_REJECT_INSUFFICIENT_MARGIN);
        }

        // The cost basis is a reporting decomposition only. It deliberately
        // uses the close mark, because the authoritative account separately
        // debits slippage instead of embedding it into position PnL.
        let current_sign = current.signum();
        let target_sign = target_units.signum();
        if current == 0.0 || current_sign != target_sign {
            if current != 0.0 {
                self.realized_pnl[symbol] += current.abs()
                    * (close - self.basis_close[symbol])
                    * current_sign
                    * contract_sizes[symbol];
            }
            self.basis_close[symbol] = if target_units == 0.0 { 0.0 } else { close };
        } else if target_units.abs() > current.abs() {
            let added = target_units.abs() - current.abs();
            self.basis_close[symbol] =
                (current.abs() * self.basis_close[symbol] + added * close) / target_units.abs();
        } else if target_units.abs() < current.abs() {
            let reduced = current.abs() - target_units.abs();
            self.realized_pnl[symbol] += reduced
                * (close - self.basis_close[symbol])
                * current_sign
                * contract_sizes[symbol];
            if target_units == 0.0 {
                self.basis_close[symbol] = 0.0;
            }
        }

        self.equity -= fee + slippage;
        self.positions[symbol] = target_units;
        self.fees[symbol] += fee;
        self.slippage[symbol] += slippage;
        self.turnover[symbol] += turnover;
        Ok(Some(SharedPortfolioFillV1 {
            symbol,
            delta,
            price,
            fee,
            turnover,
        }))
    }

    fn realize_and_clear_positions(
        &mut self,
        market: &quantbt_engine::FullMarketData,
        source_bar: usize,
        n_symbols: usize,
        contract_sizes: &[f64],
    ) {
        for (symbol, contract_size) in contract_sizes.iter().copied().enumerate().take(n_symbols) {
            let position = self.positions[symbol];
            if position != 0.0 {
                self.realized_pnl[symbol] += position.abs()
                    * (market_value(market, source_bar, n_symbols, symbol, 3)
                        - self.basis_close[symbol])
                    * position.signum()
                    * contract_size;
            }
        }
        self.positions.fill(0.0);
        self.basis_close.fill(0.0);
    }

    fn allocate_liquidation_loss(
        &mut self,
        market: &quantbt_engine::FullMarketData,
        source_bar: usize,
        n_symbols: usize,
        contract_sizes: &[f64],
    ) {
        let write_down = self.equity;
        if write_down == 0.0 {
            return;
        }
        let gross = self
            .positions
            .iter()
            .enumerate()
            .map(|(symbol, position)| {
                position.abs()
                    * market_value(market, source_bar, n_symbols, symbol, 3)
                    * contract_sizes[symbol]
            })
            .sum::<f64>();
        if gross <= 0.0 {
            // This is only reachable for a pathological post-cost account
            // breach with no remaining position.  Assign the deterministic
            // residual to symbol zero rather than silently dropping it.
            if let Some(first) = self.liquidation_loss.first_mut() {
                *first += write_down;
            }
            return;
        }
        for (symbol, position) in self.positions.iter().enumerate() {
            let exposure = position.abs()
                * market_value(market, source_bar, n_symbols, symbol, 3)
                * contract_sizes[symbol];
            self.liquidation_loss[symbol] += write_down * exposure / gross;
        }
    }
}

fn reduction_target(current: f64, target: f64) -> Option<f64> {
    if current.abs() < 1.0e-12 {
        None
    } else if target.abs() + 1.0e-12 < current.abs()
        || (target != 0.0 && current.signum() != target.signum())
    {
        Some(if target != 0.0 && current.signum() != target.signum() {
            0.0
        } else {
            target
        })
    } else {
        None
    }
}

fn shared_target_order_id(
    bar: usize,
    symbol: usize,
    phase: usize,
    n_symbols: usize,
) -> Result<i64, String> {
    let slot = bar
        .checked_mul(n_symbols)
        .and_then(|value| value.checked_add(symbol))
        .and_then(|value| value.checked_mul(2))
        .and_then(|value| value.checked_add(phase))
        .and_then(|value| value.checked_add(1))
        .ok_or_else(|| "shared portfolio target order id overflow".to_owned())?;
    i64::try_from(slot).map_err(|_| "shared portfolio target order id exceeds i64".to_owned())
}

#[allow(clippy::too_many_arguments)]
fn append_shared_fill(
    fill: SharedPortfolioFillV1,
    bar: usize,
    phase: usize,
    n_symbols: usize,
    fills: &mut Option<NativeFillOutputV1>,
    events: &mut Option<NativeEventOutputV1>,
    retention: &mut Option<AuditRetentionV1>,
    score: &mut NativeScoreOutputV1,
    fee_bar: &mut f64,
    turnover_bar: &mut f64,
) -> Result<(), String> {
    let order_id = shared_target_order_id(bar, fill.symbol, phase, n_symbols)?;
    *fee_bar += fill.fee;
    *turnover_bar += fill.turnover;
    score.fill_count = score.fill_count.saturating_add(1);
    score.event_count = score.event_count.saturating_add(1);
    append_fill_and_event(
        fills,
        events,
        retention,
        bar,
        order_id,
        fill.symbol,
        fill.delta,
        fill.price,
        fill.fee,
    );
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn append_shared_rejection(
    bar: usize,
    symbol: usize,
    n_symbols: usize,
    code: i64,
    phase: usize,
    events: &mut Option<NativeEventOutputV1>,
    retention: &mut Option<AuditRetentionV1>,
    score: &mut NativeScoreOutputV1,
    rejected_by_bar: &mut Option<Vec<i64>>,
    reject_code_by_bar: &mut Option<Vec<i64>>,
) -> Result<(), String> {
    score.rejected_count = score.rejected_count.saturating_add(1);
    score.event_count = score.event_count.saturating_add(1);
    if let Some(values) = rejected_by_bar.as_mut() {
        values[bar] = values[bar].saturating_add(1);
    }
    if let Some(values) = reject_code_by_bar.as_mut() {
        values[bar] = code;
    }
    append_rejection_event(
        events,
        retention,
        bar,
        shared_target_order_id(bar, symbol, phase, n_symbols)?,
        symbol,
        code,
    );
    Ok(())
}

#[allow(clippy::too_many_lines, clippy::too_many_arguments)]
fn execute_shared_portfolio_target(
    request: &SharedPortfolioTargetRequestV1,
) -> Result<SharedPortfolioExecutionResultV1, String> {
    let direct = request.inner();
    let requirements = direct.requirements();
    requirements.validate()?;
    let template = direct.template();
    let market = template.market();
    let account = template.account();
    let instruments = template.instruments();
    let n_bars = template.bar_count();
    let n_symbols = template.n_symbols();
    let market_start = template.market_range().0;
    let contract_sizes = instruments.contract_sizes();
    let leverages = instruments.leverages();
    let fee_rates = instruments.fee_rates();

    validate_market_slice(market, market_start, n_bars, n_symbols)?;
    let mut state = SharedPortfolioStateV1::new(account.initial_capital, n_symbols);
    let metric_contract = MetricContractV2::default();
    let mut metric_reducer = OnlineMetricReducerV2::new(metric_contract, state.equity)?;
    let mut score = NativeScoreOutputV1 {
        final_equity: state.equity,
        metric_contract,
        ..NativeScoreOutputV1::default()
    };
    let mut paths = requirements
        .retain_paths
        .then(|| NativePathOutputV1::with_capacity(n_bars, n_symbols));
    let mut fills = requirements.retain_detail.then(NativeFillOutputV1::default);
    let mut events = requirements
        .retain_detail
        .then(NativeEventOutputV1::default);
    let mut execution_retention = requirements
        .retain_detail
        .then(|| AuditRetentionV1::new(requirements.detail_row_limit.unwrap_or(0)));
    let mut target_audit = if requirements.retain_detail {
        DirectTargetAuditV1::with_detail_limit(requirements.detail_row_limit.unwrap_or(0))
    } else {
        DirectTargetAuditV1::default()
    };
    let mut rejected_by_bar = requirements.retain_paths.then(|| vec![0_i64; n_bars]);
    let mut reject_code_by_bar = requirements.retain_paths.then(|| vec![0_i64; n_bars]);
    let mut liquidated = false;
    let mut liquidation_bar = -1_i64;
    let mut liquidation_reason = TARGET_LIQ_NONE;
    let mut command_count = 0_usize;

    record_path(
        &mut paths,
        state.equity,
        &state.positions,
        0.0,
        0.0,
        0.0,
        0.0,
    );
    metric_reducer.observe(market.timestamps_ns[market_start], state.equity, 0.0)?;

    for bar in 1..n_bars {
        let source_bar = market_start + bar;
        let mut fee_bar = 0.0;
        let mut turnover_bar = 0.0;
        let mut funding_bar = 0.0;
        if liquidated {
            record_path(&mut paths, 0.0, &state.positions, 0.0, 0.0, 0.0, 0.0);
            metric_reducer.observe(market.timestamps_ns[source_bar], 0.0, 0.0)?;
            continue;
        }

        state.mark_to_close(market, source_bar, n_symbols, contract_sizes);
        let mut worst_equity = state.equity;
        let mut worst_maintenance = 0.0;
        for (symbol, contract_size) in contract_sizes.iter().copied().enumerate().take(n_symbols) {
            let position = state.positions[symbol];
            if position == 0.0 {
                continue;
            }
            let close = market_value(market, source_bar, n_symbols, symbol, 3);
            let worst = if position > 0.0 {
                market_value(market, source_bar, n_symbols, symbol, 2)
            } else {
                market_value(market, source_bar, n_symbols, symbol, 1)
            };
            worst_equity += position * (worst - close) * contract_size;
            worst_maintenance += position.abs() * worst * contract_size * account.maintenance_ratio;
        }
        if worst_maintenance > 0.0 && worst_equity <= worst_maintenance {
            liquidated = true;
            liquidation_bar = bar as i64;
            liquidation_reason = TARGET_LIQ_INTRABAR;
            state.allocate_liquidation_loss(market, source_bar, n_symbols, contract_sizes);
            state.realize_and_clear_positions(market, source_bar, n_symbols, contract_sizes);
            state.equity = 0.0;
            record_path(
                &mut paths,
                0.0,
                &state.positions,
                fee_bar,
                turnover_bar,
                funding_bar,
                0.0,
            );
            metric_reducer.observe(market.timestamps_ns[source_bar], 0.0, 0.0)?;
            continue;
        }

        if market.funding_mask[source_bar] && account.use_funding {
            funding_bar = state.apply_funding(market, source_bar, n_symbols, contract_sizes);
        }
        let close_maintenance_before = maintenance_margin(
            &state.positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            account.maintenance_ratio,
        );
        if close_maintenance_before > 0.0 && state.equity <= close_maintenance_before {
            liquidated = true;
            liquidation_bar = bar as i64;
            liquidation_reason = TARGET_LIQ_AFTER_FUNDING;
            state.allocate_liquidation_loss(market, source_bar, n_symbols, contract_sizes);
            state.realize_and_clear_positions(market, source_bar, n_symbols, contract_sizes);
            state.equity = 0.0;
            record_path(
                &mut paths,
                0.0,
                &state.positions,
                fee_bar,
                turnover_bar,
                funding_bar,
                0.0,
            );
            score.total_funding += funding_bar;
            metric_reducer.observe(market.timestamps_ns[source_bar], 0.0, 0.0)?;
            continue;
        }

        let equity_snapshot = state.equity;
        let mut candidates = Vec::with_capacity(n_symbols);
        for (symbol, contract_size) in contract_sizes.iter().copied().enumerate().take(n_symbols) {
            let close = market_value(market, source_bar, n_symbols, symbol, 3);
            let raw = direct.target_at(bar, symbol);
            match resolve_target(
                raw,
                direct.kind,
                direct.invalid_target_policy,
                close,
                contract_size,
                equity_snapshot,
                direct.equity_fraction[symbol],
                direct.qty_step[symbol],
                direct.min_qty[symbol],
                direct.min_notional[symbol],
            )? {
                TargetResolution::Value {
                    requested_units,
                    target_units,
                } if (target_units - state.positions[symbol]).abs() >= 1.0e-12 => {
                    let preflight_rejection = if !DirectTargetRequestV1::flag_at(
                        &direct.tradable,
                        n_symbols,
                        bar,
                        symbol,
                    ) {
                        TARGET_REJECT_NON_TRADABLE
                    } else if DirectTargetRequestV1::flag_at(&direct.stale, n_symbols, bar, symbol)
                    {
                        TARGET_REJECT_STALE_PRICE
                    } else {
                        TARGET_REJECT_NONE
                    };
                    candidates.push(SharedPortfolioCandidateV1 {
                        symbol,
                        requested_units,
                        target_units,
                        preflight_rejection,
                    });
                }
                TargetResolution::Value { .. } => {}
                TargetResolution::Hold { rejection_code } => {
                    candidates.push(SharedPortfolioCandidateV1 {
                        symbol,
                        requested_units: raw,
                        target_units: state.positions[symbol],
                        preflight_rejection: rejection_code,
                    })
                }
            }
        }

        let mut outcome_codes = vec![TARGET_REJECT_NONE; n_symbols];
        let mut adjusted = vec![false; n_symbols];
        let mut committed = Vec::<(SharedPortfolioFillV1, usize)>::new();
        if request.admission_policy() == PortfolioAdmissionPolicyV1::AllOrNoneRebalance
            && candidates
                .iter()
                .any(|candidate| candidate.preflight_rejection != TARGET_REJECT_NONE)
        {
            for candidate in &candidates {
                outcome_codes[candidate.symbol] = TARGET_REJECT_ATOMIC_ROLLBACK;
            }
        } else {
            match request.admission_policy() {
                PortfolioAdmissionPolicyV1::SequentialLegacy => {
                    for candidate in &candidates {
                        if candidate.preflight_rejection != TARGET_REJECT_NONE {
                            outcome_codes[candidate.symbol] = candidate.preflight_rejection;
                            continue;
                        }
                        match state.apply_target(
                            candidate.symbol,
                            candidate.target_units,
                            market,
                            source_bar,
                            n_symbols,
                            contract_sizes,
                            leverages,
                            fee_rates,
                            account.slippage_rate,
                            false,
                        ) {
                            Ok(Some(fill)) => committed.push((fill, 0)),
                            Ok(None) => {}
                            Err(code) => outcome_codes[candidate.symbol] = code,
                        }
                    }
                }
                PortfolioAdmissionPolicyV1::ReduceFirstThenIncrease
                | PortfolioAdmissionPolicyV1::ProRataToAvailableMargin => {
                    for candidate in &candidates {
                        if candidate.preflight_rejection != TARGET_REJECT_NONE {
                            outcome_codes[candidate.symbol] = candidate.preflight_rejection;
                            continue;
                        }
                        if let Some(intermediate) = reduction_target(
                            state.positions[candidate.symbol],
                            candidate.target_units,
                        ) {
                            match state.apply_target(
                                candidate.symbol,
                                intermediate,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                                fee_rates,
                                account.slippage_rate,
                                true,
                            ) {
                                Ok(Some(fill)) => committed.push((fill, 0)),
                                Ok(None) => {}
                                Err(code) => outcome_codes[candidate.symbol] = code,
                            }
                        }
                    }

                    if request.admission_policy()
                        == PortfolioAdmissionPolicyV1::ReduceFirstThenIncrease
                    {
                        for candidate in &candidates {
                            if outcome_codes[candidate.symbol] != TARGET_REJECT_NONE
                                || candidate.preflight_rejection != TARGET_REJECT_NONE
                            {
                                continue;
                            }
                            match state.apply_target(
                                candidate.symbol,
                                candidate.target_units,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                                fee_rates,
                                account.slippage_rate,
                                false,
                            ) {
                                Ok(Some(fill)) => committed.push((fill, 1)),
                                Ok(None) => {}
                                Err(code) => outcome_codes[candidate.symbol] = code,
                            }
                        }
                    } else {
                        let available = (state.equity
                            - initial_margin(
                                &state.positions,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                            ))
                        .max(0.0);
                        let mut total_required = 0.0;
                        for candidate in &candidates {
                            if outcome_codes[candidate.symbol] != TARGET_REJECT_NONE
                                || candidate.preflight_rejection != TARGET_REJECT_NONE
                            {
                                continue;
                            }
                            let current = state.positions[candidate.symbol];
                            if (candidate.target_units - current).abs() < 1.0e-12 {
                                continue;
                            }
                            let close =
                                market_value(market, source_bar, n_symbols, candidate.symbol, 3);
                            let delta = candidate.target_units - current;
                            let price = if delta > 0.0 {
                                close * (1.0 + account.slippage_rate)
                            } else {
                                close * (1.0 - account.slippage_rate)
                            };
                            let turnover = delta.abs() * price * contract_sizes[candidate.symbol];
                            let fee = turnover * fee_rates[candidate.symbol];
                            let slippage = delta.abs()
                                * (price - close).abs()
                                * contract_sizes[candidate.symbol];
                            let old_initial =
                                current.abs() * close * contract_sizes[candidate.symbol]
                                    / leverages[candidate.symbol];
                            let new_initial = candidate.target_units.abs()
                                * price
                                * contract_sizes[candidate.symbol]
                                / leverages[candidate.symbol];
                            total_required += fee + slippage + (new_initial - old_initial).max(0.0);
                        }
                        let scale = if total_required > available && total_required > 0.0 {
                            (available / total_required).clamp(0.0, 1.0)
                        } else {
                            1.0
                        };
                        for candidate in &candidates {
                            if outcome_codes[candidate.symbol] != TARGET_REJECT_NONE
                                || candidate.preflight_rejection != TARGET_REJECT_NONE
                            {
                                continue;
                            }
                            let current = state.positions[candidate.symbol];
                            let close =
                                market_value(market, source_bar, n_symbols, candidate.symbol, 3);
                            let scaled = quantize_signed_quantity(
                                current + (candidate.target_units - current) * scale,
                                close,
                                contract_sizes[candidate.symbol],
                                direct.qty_step[candidate.symbol],
                                direct.min_qty[candidate.symbol],
                                direct.min_notional[candidate.symbol],
                            );
                            adjusted[candidate.symbol] =
                                (scaled - candidate.target_units).abs() >= 1.0e-12;
                            match state.apply_target(
                                candidate.symbol,
                                scaled,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                                fee_rates,
                                account.slippage_rate,
                                false,
                            ) {
                                Ok(Some(fill)) => committed.push((fill, 1)),
                                Ok(None) => {}
                                Err(code) => outcome_codes[candidate.symbol] = code,
                            }
                        }
                        // Quantization can leave less than one lot of budget per
                        // symbol. Allocate that bounded rounding residual once
                        // in normalized symbol order, without violating the
                        // proportional scale chosen above.
                        for candidate in &candidates {
                            if !adjusted[candidate.symbol]
                                || outcome_codes[candidate.symbol] != TARGET_REJECT_NONE
                            {
                                continue;
                            }
                            let step = direct.qty_step[candidate.symbol];
                            if step <= 0.0 {
                                continue;
                            }
                            let current = state.positions[candidate.symbol];
                            let remaining = candidate.target_units - current;
                            if remaining.abs() + 1.0e-12 < step {
                                continue;
                            }
                            let proposed = current + remaining.signum() * step;
                            let proposed = if remaining > 0.0 {
                                proposed.min(candidate.target_units)
                            } else {
                                proposed.max(candidate.target_units)
                            };
                            if let Ok(Some(fill)) = state.apply_target(
                                candidate.symbol,
                                proposed,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                                fee_rates,
                                account.slippage_rate,
                                false,
                            ) {
                                committed.push((fill, 1));
                            }
                            adjusted[candidate.symbol] =
                                (state.positions[candidate.symbol] - candidate.target_units).abs()
                                    >= 1.0e-12;
                        }
                    }
                }
                PortfolioAdmissionPolicyV1::AllOrNoneRebalance => {
                    let mut preview = state.clone();
                    let mut preview_fills = Vec::<(SharedPortfolioFillV1, usize)>::new();
                    let mut rejected = false;
                    for candidate in &candidates {
                        if candidate.preflight_rejection != TARGET_REJECT_NONE {
                            rejected = true;
                            break;
                        }
                        if let Some(intermediate) = reduction_target(
                            preview.positions[candidate.symbol],
                            candidate.target_units,
                        ) {
                            match preview.apply_target(
                                candidate.symbol,
                                intermediate,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                                fee_rates,
                                account.slippage_rate,
                                true,
                            ) {
                                Ok(Some(fill)) => preview_fills.push((fill, 0)),
                                Ok(None) => {}
                                Err(_) => {
                                    rejected = true;
                                    break;
                                }
                            }
                        }
                    }
                    if !rejected {
                        for candidate in &candidates {
                            match preview.apply_target(
                                candidate.symbol,
                                candidate.target_units,
                                market,
                                source_bar,
                                n_symbols,
                                contract_sizes,
                                leverages,
                                fee_rates,
                                account.slippage_rate,
                                false,
                            ) {
                                Ok(Some(fill)) => preview_fills.push((fill, 1)),
                                Ok(None) => {}
                                Err(_) => {
                                    rejected = true;
                                    break;
                                }
                            }
                        }
                    }
                    if rejected {
                        for candidate in &candidates {
                            outcome_codes[candidate.symbol] = TARGET_REJECT_ATOMIC_ROLLBACK;
                        }
                    } else {
                        state = preview;
                        committed = preview_fills;
                    }
                }
            }
        }

        for (fill, phase) in committed {
            append_shared_fill(
                fill,
                bar,
                phase,
                n_symbols,
                &mut fills,
                &mut events,
                &mut execution_retention,
                &mut score,
                &mut fee_bar,
                &mut turnover_bar,
            )?;
        }
        for candidate in &candidates {
            command_count = command_count.saturating_add(1);
            let mut code = outcome_codes[candidate.symbol];
            if code == TARGET_REJECT_NONE
                && request.admission_policy()
                    == PortfolioAdmissionPolicyV1::ProRataToAvailableMargin
                && adjusted[candidate.symbol]
            {
                code = TARGET_ADJUSTED_PRO_RATA;
            }
            if code != TARGET_REJECT_NONE && code != TARGET_ADJUSTED_PRO_RATA {
                append_shared_rejection(
                    bar,
                    candidate.symbol,
                    n_symbols,
                    code,
                    1,
                    &mut events,
                    &mut execution_retention,
                    &mut score,
                    &mut rejected_by_bar,
                    &mut reject_code_by_bar,
                )?;
                target_audit.rejected_decision_count =
                    target_audit.rejected_decision_count.saturating_add(1);
            }
            target_audit.decision_count = target_audit.decision_count.saturating_add(1);
            if requirements.retain_detail {
                target_audit.record(
                    bar,
                    candidate.symbol,
                    candidate.requested_units,
                    state.positions[candidate.symbol],
                    code,
                );
            }
        }

        let close_initial_margin = initial_margin(
            &state.positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            leverages,
        );
        let close_maintenance = maintenance_margin(
            &state.positions,
            market,
            source_bar,
            n_symbols,
            contract_sizes,
            account.maintenance_ratio,
        );
        if close_maintenance > 0.0 && state.equity <= close_maintenance {
            liquidated = true;
            liquidation_bar = bar as i64;
            liquidation_reason = TARGET_LIQ_AFTER_REBALANCE;
            state.allocate_liquidation_loss(market, source_bar, n_symbols, contract_sizes);
            state.realize_and_clear_positions(market, source_bar, n_symbols, contract_sizes);
            state.equity = 0.0;
            record_path(
                &mut paths,
                0.0,
                &state.positions,
                fee_bar,
                turnover_bar,
                funding_bar,
                0.0,
            );
            score.total_fee += fee_bar;
            score.total_turnover += turnover_bar;
            score.total_funding += funding_bar;
            metric_reducer.observe(market.timestamps_ns[source_bar], 0.0, 0.0)?;
            continue;
        }
        record_path(
            &mut paths,
            state.equity,
            &state.positions,
            fee_bar,
            turnover_bar,
            funding_bar,
            close_initial_margin,
        );
        if let Some(paths) = paths.as_mut()
            && let Some(last) = paths.maintenance_margin.last_mut()
        {
            *last = close_maintenance;
        }
        score.total_fee += fee_bar;
        score.total_turnover += turnover_bar;
        score.total_funding += funding_bar;
        score.max_initial_margin = score.max_initial_margin.max(close_initial_margin);
        score.max_maintenance_margin = score.max_maintenance_margin.max(close_maintenance);
        metric_reducer.observe(
            market.timestamps_ns[source_bar],
            state.equity,
            gross_exposure(
                &state.positions,
                market,
                source_bar,
                n_symbols,
                contract_sizes,
                state.equity,
            ),
        )?;
    }

    score.final_equity = state.equity;
    score.final_positions = state.positions.clone();
    score.liquidated = liquidated;
    score.liquidation_bar = liquidation_bar;
    score.liquidation_reason = liquidation_reason;
    score.metrics_v2 = Box::new(metric_reducer.finish(MetricFinishInputV2 {
        final_equity: score.final_equity,
        turnover: score.total_turnover,
        total_fee: score.total_fee,
        total_funding: score.total_funding,
        fill_count: score.fill_count,
        event_count: score.event_count,
        rejected_count: score.rejected_count,
        canceled_count: score.canceled_count,
        liquidated: score.liquidated,
    }));

    let terminal_bar = market_start + n_bars - 1;
    let mut attribution = SharedPortfolioAttributionV1 {
        realized_pnl: state.realized_pnl,
        unrealized_pnl: vec![0.0; n_symbols],
        mark_to_market_pnl: state.mark_to_market_pnl,
        fees: state.fees,
        slippage: state.slippage,
        funding: state.funding,
        liquidation_loss: state.liquidation_loss,
        turnover: state.turnover,
        final_exposure: vec![0.0; n_symbols],
        final_initial_margin: vec![0.0; n_symbols],
    };
    for symbol in 0..n_symbols {
        let close = market_value(market, terminal_bar, n_symbols, symbol, 3);
        let position = state.positions[symbol];
        attribution.unrealized_pnl[symbol] =
            position * (close - state.basis_close[symbol]) * contract_sizes[symbol];
        attribution.final_exposure[symbol] = position.abs() * close * contract_sizes[symbol];
        attribution.final_initial_margin[symbol] =
            attribution.final_exposure[symbol] / leverages[symbol];
    }

    let output = match requirements.profile {
        StaticOutputProfile::Score => NativeExecutionOutputV1::Score(score),
        StaticOutputProfile::Compact => {
            NativeExecutionOutputV1::Compact(Box::new(NativeCompactOutputV1 {
                score,
                paths: paths.expect("compact shared portfolio output requires paths"),
            }))
        }
        StaticOutputProfile::Audit => {
            NativeExecutionOutputV1::Audit(Box::new(NativeAuditOutputV1 {
                compact: NativeCompactOutputV1 {
                    score,
                    paths: paths.expect("audit shared portfolio output requires paths"),
                },
                fills: fills.expect("audit shared portfolio output requires fills"),
                events: events.expect("audit shared portfolio output requires events"),
                detail_retention: execution_retention
                    .expect("audit shared portfolio output requires retention"),
            }))
        }
    };
    let terminal_fingerprint = terminal_fingerprint_v2(&output);
    let mut hash = FingerprintWriter::new();
    hash.bytes(b"native-shared-portfolio-target-contract-bundle-v1");
    hash.bytes(&request.fingerprint());
    hash.bytes(&template.fingerprint());
    hash.u8(request.admission_policy() as u8);
    let bundle = hash.finish();
    let mut lower = [0_u8; 16];
    lower.copy_from_slice(&bundle[..16]);
    Ok(SharedPortfolioExecutionResultV1 {
        output,
        target_audit,
        attribution,
        rejected_by_bar,
        reject_code_by_bar,
        request_fingerprint: request.fingerprint(),
        template_fingerprint: template.fingerprint(),
        target_kind: direct.kind(),
        timing: direct.timing(),
        invalid_target_policy: direct.invalid_target_policy(),
        admission_policy: request.admission_policy(),
        command_count,
        bar_count: n_bars,
        symbol_count: n_symbols,
        contract_bundle_hash: u128::from_le_bytes(lower),
        terminal_fingerprint,
    })
}

fn validate_market_slice(
    market: &quantbt_engine::FullMarketData,
    start: usize,
    bars: usize,
    symbols: usize,
) -> Result<(), String> {
    for bar in start..start + bars {
        for symbol in 0..symbols {
            let offset = bar * symbols + symbol;
            let values = [
                market.highs[offset],
                market.lows[offset],
                market.closes[offset],
                market.funding[offset],
            ];
            if values.iter().any(|value| !value.is_finite()) || market.closes[offset] <= 0.0 {
                return Err("native direct target requires finite positive close and finite high/low/funding".to_owned());
            }
        }
    }
    Ok(())
}

fn market_value(
    market: &quantbt_engine::FullMarketData,
    source_bar: usize,
    n_symbols: usize,
    symbol: usize,
    field: u8,
) -> f64 {
    let offset = source_bar * n_symbols + symbol;
    match field {
        1 => market.highs[offset],
        2 => market.lows[offset],
        3 => market.closes[offset],
        6 => market.funding[offset],
        _ => unreachable!("unsupported direct target market field"),
    }
}

#[allow(clippy::too_many_arguments)]
fn resolve_target(
    raw: f64,
    kind: DirectTargetKindV1,
    invalid_policy: InvalidTargetPolicyV1,
    close: f64,
    contract_size: f64,
    equity_snapshot: f64,
    equity_fraction: f64,
    qty_step: f64,
    min_qty: f64,
    min_notional: f64,
) -> Result<TargetResolution, String> {
    if !raw.is_finite() {
        return match invalid_policy {
            InvalidTargetPolicyV1::RejectRun => Err(
                "native direct target received non-finite value under reject_run policy".to_owned(),
            ),
            InvalidTargetPolicyV1::Flatten => Ok(TargetResolution::Value {
                requested_units: 0.0,
                target_units: 0.0,
            }),
            InvalidTargetPolicyV1::HoldPrior | InvalidTargetPolicyV1::SkipBar => {
                Ok(TargetResolution::Hold {
                    rejection_code: TARGET_REJECT_INVALID_TARGET,
                })
            }
        };
    }
    let denominator = close * contract_size;
    if !denominator.is_finite() || denominator <= 0.0 || !equity_snapshot.is_finite() {
        return Err("native direct target has an invalid close/equity denominator".to_owned());
    }
    let requested_units = match kind {
        DirectTargetKindV1::Units => raw,
        DirectTargetKindV1::Notional => raw / denominator,
        DirectTargetKindV1::Weight => raw * equity_snapshot / denominator,
        // The fraction is a declared capital allocation multiplier. Leverage
        // affects buying power/margin only; it is never silently multiplied
        // into desired notional on this route.
        DirectTargetKindV1::EquityFraction | DirectTargetKindV1::PctEquityTransition => {
            raw * equity_fraction * equity_snapshot / denominator
        }
    };
    if !requested_units.is_finite() {
        return match invalid_policy {
            InvalidTargetPolicyV1::RejectRun => Err(
                "native direct target resolution became non-finite under reject_run policy"
                    .to_owned(),
            ),
            InvalidTargetPolicyV1::Flatten => Ok(TargetResolution::Value {
                requested_units: 0.0,
                target_units: 0.0,
            }),
            InvalidTargetPolicyV1::HoldPrior | InvalidTargetPolicyV1::SkipBar => {
                Ok(TargetResolution::Hold {
                    rejection_code: TARGET_REJECT_INVALID_TARGET,
                })
            }
        };
    }
    Ok(TargetResolution::Value {
        requested_units,
        target_units: quantize_signed_quantity(
            requested_units,
            close,
            contract_size,
            qty_step,
            min_qty,
            min_notional,
        ),
    })
}

fn quantize_signed_quantity(
    value: f64,
    price: f64,
    contract_size: f64,
    qty_step: f64,
    min_qty: f64,
    min_notional: f64,
) -> f64 {
    if value == 0.0 {
        return 0.0;
    }
    let sign = if value > 0.0 { 1.0 } else { -1.0 };
    let mut absolute = value.abs();
    if qty_step > 0.0 {
        absolute = (absolute / qty_step + 1.0e-12).floor() * qty_step;
    }
    if absolute <= 0.0
        || (min_qty > 0.0 && absolute + 1.0e-12 < min_qty)
        || (min_notional > 0.0 && absolute * price * contract_size + 1.0e-12 < min_notional)
    {
        return 0.0;
    }
    sign * absolute
}

fn initial_margin(
    positions: &[f64],
    market: &quantbt_engine::FullMarketData,
    source_bar: usize,
    n_symbols: usize,
    contract_sizes: &[f64],
    leverages: &[f64],
) -> f64 {
    positions
        .iter()
        .enumerate()
        .map(|(symbol, position)| {
            position.abs()
                * market_value(market, source_bar, n_symbols, symbol, 3)
                * contract_sizes[symbol]
                / leverages[symbol]
        })
        .sum()
}

fn maintenance_margin(
    positions: &[f64],
    market: &quantbt_engine::FullMarketData,
    source_bar: usize,
    n_symbols: usize,
    contract_sizes: &[f64],
    maintenance_ratio: f64,
) -> f64 {
    positions
        .iter()
        .enumerate()
        .map(|(symbol, position)| {
            position.abs()
                * market_value(market, source_bar, n_symbols, symbol, 3)
                * contract_sizes[symbol]
                * maintenance_ratio
        })
        .sum()
}

fn gross_exposure(
    positions: &[f64],
    market: &quantbt_engine::FullMarketData,
    source_bar: usize,
    n_symbols: usize,
    contract_sizes: &[f64],
    equity: f64,
) -> f64 {
    if equity <= 0.0 {
        return 0.0;
    }
    positions
        .iter()
        .enumerate()
        .map(|(symbol, position)| {
            position.abs()
                * market_value(market, source_bar, n_symbols, symbol, 3)
                * contract_sizes[symbol]
        })
        .sum::<f64>()
        / equity
}

fn record_path(
    paths: &mut Option<NativePathOutputV1>,
    equity: f64,
    positions: &[f64],
    fees: f64,
    turnover: f64,
    funding: f64,
    initial_margin: f64,
) {
    if let Some(paths) = paths.as_mut() {
        paths.equity.push(equity);
        paths.positions.extend_from_slice(positions);
        paths.fees.push(fees);
        paths.turnover.push(turnover);
        paths.funding.push(funding);
        paths.initial_margin.push(initial_margin);
        paths.maintenance_margin.push(initial_margin);
    }
}

#[allow(clippy::too_many_arguments)]
fn append_fill_and_event(
    fills: &mut Option<NativeFillOutputV1>,
    events: &mut Option<NativeEventOutputV1>,
    retention: &mut Option<AuditRetentionV1>,
    bar: usize,
    order_id: i64,
    symbol: usize,
    delta: f64,
    price: f64,
    fee: f64,
) {
    if let (Some(fills), Some(events), Some(retention)) =
        (fills.as_mut(), events.as_mut(), retention.as_mut())
    {
        if retention.retain_next() {
            fills.bar.push(bar as i64);
            fills.order_id.push(order_id);
            fills.symbol.push(symbol as i64);
            fills.side.push(if delta > 0.0 { 1 } else { -1 });
            fills.qty.push(delta.abs());
            fills.price.push(price);
            fills.fee.push(fee);
            fills.reason.push(FILL_REASON_CLOSE_TARGET_SAME_CLOSE);
            fills.ambiguity.push(0);
        }
        if retention.retain_next() {
            events.bar.push(bar as i64);
            events.kind.push(EVENT_FILL);
            events.status.push(STATUS_FILLED);
            events.order_id.push(order_id);
            events.target_id.push(-1);
            events.symbol.push(symbol as i64);
            events.reject_code.push(TARGET_REJECT_NONE);
        }
    }
}

fn append_rejection_event(
    events: &mut Option<NativeEventOutputV1>,
    retention: &mut Option<AuditRetentionV1>,
    bar: usize,
    order_id: i64,
    symbol: usize,
    rejection_code: i64,
) {
    if let (Some(events), Some(retention)) = (events.as_mut(), retention.as_mut())
        && retention.retain_next()
    {
        events.bar.push(bar as i64);
        events.kind.push(EVENT_REJECT);
        events.status.push(STATUS_REJECTED);
        events.order_id.push(order_id);
        events.target_id.push(-1);
        events.symbol.push(symbol as i64);
        events.reject_code.push(rejection_code);
    }
}

fn direct_target_order_id(bar: usize, symbol: usize, n_symbols: usize) -> Result<i64, String> {
    let offset = bar
        .checked_mul(n_symbols)
        .and_then(|value| value.checked_add(symbol))
        .and_then(|value| value.checked_add(1))
        .ok_or_else(|| "native direct target order id overflow".to_owned())?;
    i64::try_from(offset).map_err(|_| "native direct target order id exceeds i64".to_owned())
}

fn direct_target_contract_bundle_hash(request: &DirectTargetRequestV1) -> u128 {
    let mut hash = FingerprintWriter::new();
    hash.bytes(b"native-direct-target-contract-bundle-v1");
    hash.bytes(&request.template().fingerprint());
    hash.u8(request.kind() as u8);
    hash.u8(request.timing());
    hash.u8(request.invalid_target_policy() as u8);
    let bytes = hash.finish();
    let mut lower = [0_u8; 16];
    lower.copy_from_slice(&bytes[..16]);
    u128::from_le_bytes(lower)
}
