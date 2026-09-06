//! Versioned typed execution requests for the shared QuantBT Rust runtime.
//!
//! This crate deliberately sits above `quantbt-engine`: it owns immutable
//! request/provenance data and lowers every supported workload to the same
//! [`CommandTapeV5`] consumed by [`FullSession`].  It owns no mutable account,
//! order, lifecycle, or matching state.  A fresh `FullSession` remains the
//! single authoritative execution owner for every request run.

use std::sync::Arc;

use quantbt_domain::InstrumentRegistryV2;
use quantbt_domain::commands::CommandTapeV5;
use quantbt_domain::enums::{CommandAction, OrderType};
use quantbt_domain::generated_contracts::{
    CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN,
    CONTRACT_REGISTRY_FINGERPRINT,
};
use quantbt_domain::generated_product_contracts::{
    COMMAND_ABI_VERSION, CORE_PROTOCOL_MAX, CORE_PROTOCOL_MIN, RESULT_ABI_VERSION,
};
use quantbt_domain::ids::SymbolId;
use quantbt_engine::{
    AuditRetentionV1, ExecutionModelPlanV1, FullMarketData, FullSession, MetricContractV2,
    NativeExecutionOutputV1, NativeMetricSnapshotV2, NativeScoreOutputV1, OutputRequirementsV1,
    StaticOutputProfile, StaticTapeOutput,
};
use quantbt_package::{
    PackageEventKind, PackageExecutionResult, PackageIntentV2, PackageLegRequest,
    PackageMarketExecutionRequestV2, PackagePlan, PackagePolicy, PackageState,
};
use quantbt_portfolio::{PortfolioMarginAllocationPolicy, PortfolioTargetTape};
use quantbt_strategy_ir::{PARAMETER_WIDTH, StrategyProgram};

pub mod intrabar;
pub mod package;
pub mod target;

use package::{PackageMarketAuditV2, PackageMarketWorkloadV2};

/// Stable version for the immutable request layout, independent of the public
/// PyO3 API version.  Additive fields require a new request version.
pub const NATIVE_EXECUTION_REQUEST_VERSION_V1: u16 = 1;
pub const NATIVE_EXECUTION_REQUEST_SCHEMA_V1: &str = "native-execution-request-v1";

/// The current generated product registry intentionally supports one native
/// core protocol.  Keeping this explicit in the request fingerprint prevents
/// cache reuse across a future protocol change.
pub const NATIVE_EXECUTION_PROTOCOL_VERSION_V1: u16 = CORE_PROTOCOL_MIN as u16;

/// Stable envelope version for native result provenance. The underlying
/// score/compact/audit SoA payloads stay domain-specific; this header records
/// their common authority, retention, and terminal accounting identity.
pub const NATIVE_RESULT_VERSION_V2: u16 = 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum NativeOutputProfileV1 {
    Score = 0,
    Compact = 1,
    Audit = 2,
}

impl TryFrom<u8> for NativeOutputProfileV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Score),
            1 => Ok(Self::Compact),
            2 => Ok(Self::Audit),
            _ => Err("unsupported native execution output profile".to_owned()),
        }
    }
}

impl NativeOutputProfileV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Score => "score",
            Self::Compact => "compact",
            Self::Audit => "audit",
        }
    }
}

/// Immutable account inputs that the current `FullSession` implements.
///
/// The field set is intentionally exact: unsupported venue-specific account
/// semantics must fail capability checks above this request instead of being
/// silently represented by a default here.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AccountModelV1 {
    pub initial_capital: f64,
    pub maintenance_ratio: f64,
    pub slippage_rate: f64,
    pub use_funding: bool,
}

impl AccountModelV1 {
    pub fn new(
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        if !initial_capital.is_finite()
            || initial_capital <= 0.0
            || !maintenance_ratio.is_finite()
            || maintenance_ratio < 0.0
            || !slippage_rate.is_finite()
            || slippage_rate < 0.0
        {
            return Err("native execution account model is invalid".to_owned());
        }
        Ok(Self {
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        })
    }
}

/// Per-symbol constraints already honored by the current full event session.
///
/// `symbol_ids` must be normalized to the bar-major market columns.  Price
/// tick, quantity step, and venue-specific minimums are intentionally absent:
/// the current `FullSession` does not yet apply them, so accepting them here
/// would falsely claim support.
#[derive(Clone, Debug, PartialEq)]
pub struct InstrumentTableV1 {
    symbol_ids: Box<[SymbolId]>,
    contract_sizes: Box<[f64]>,
    leverages: Box<[f64]>,
    fee_rates: Box<[f64]>,
}

impl InstrumentTableV1 {
    /// Compatibility lowering from the canonical V2 registry.  The V1 full
    /// session has not yet modeled venue minima/ticks itself, but it receives
    /// its multiplier/leverage/fee arrays from the same immutable rule source
    /// rather than a workload-local parallel table.
    pub fn from_registry_v2(registry: &InstrumentRegistryV2) -> Result<Self, String> {
        let contract_sizes = registry
            .rules
            .iter()
            .map(|rule| rule.contract_multiplier)
            .collect();
        let leverages = registry
            .rules
            .iter()
            .map(|rule| rule.leverage_limit)
            .collect();
        let fee_rates = registry
            .rules
            .iter()
            .map(|rule| rule.one_way_fee_rate)
            .collect();
        Self::sequential(contract_sizes, leverages, fee_rates)
    }

    pub fn new(
        symbol_ids: Vec<SymbolId>,
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
        fee_rates: Vec<f64>,
    ) -> Result<Self, String> {
        let count = symbol_ids.len();
        if count == 0
            || contract_sizes.len() != count
            || leverages.len() != count
            || fee_rates.len() != count
            || symbol_ids
                .iter()
                .enumerate()
                .any(|(index, symbol)| u32::try_from(index) != Ok(symbol.0))
            || contract_sizes
                .iter()
                .any(|value| !value.is_finite() || *value <= 0.0)
            || leverages
                .iter()
                .any(|value| !value.is_finite() || *value <= 0.0)
            || fee_rates
                .iter()
                .any(|value| !value.is_finite() || *value < 0.0)
        {
            return Err(
                "native execution instrument table must match normalized market columns".to_owned(),
            );
        }
        Ok(Self {
            symbol_ids: symbol_ids.into_boxed_slice(),
            contract_sizes: contract_sizes.into_boxed_slice(),
            leverages: leverages.into_boxed_slice(),
            fee_rates: fee_rates.into_boxed_slice(),
        })
    }

    pub fn sequential(
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
        fee_rates: Vec<f64>,
    ) -> Result<Self, String> {
        let symbol_ids = (0..contract_sizes.len())
            .map(|index| {
                u32::try_from(index)
                    .map(SymbolId)
                    .map_err(|_| "native execution has too many symbols".to_owned())
            })
            .collect::<Result<Vec<_>, _>>()?;
        Self::new(symbol_ids, contract_sizes, leverages, fee_rates)
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.symbol_ids.len()
    }

    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.symbol_ids.is_empty()
    }

    /// Immutable contract multipliers in normalized market-column order.
    #[must_use]
    pub fn contract_sizes(&self) -> &[f64] {
        &self.contract_sizes
    }

    /// Immutable leverage limits in normalized market-column order.
    #[must_use]
    pub fn leverages(&self) -> &[f64] {
        &self.leverages
    }

    /// Immutable canonical one-way fee rates in normalized market-column order.
    #[must_use]
    pub fn fee_rates(&self) -> &[f64] {
        &self.fee_rates
    }
}

/// Complete supported event-clock contract for the current full session.
///
/// The numeric ID references the generated contract registry, whose digest is
/// captured by every request fingerprint.  Unknown/future contracts reject at
/// construction instead of falling back to a default fill timing.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExecutionContractV1 {
    pub event_contract_code: i64,
}

impl ExecutionContractV1 {
    pub fn new(event_contract_code: i64) -> Result<Self, String> {
        if event_contract_code != CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE
            && event_contract_code != CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN
        {
            return Err(format!(
                "unsupported native execution contract code {event_contract_code}"
            ));
        }
        Ok(Self {
            event_contract_code,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum NativeWorkloadKindV1 {
    CommandTape = 0,
    StrategyIr = 1,
    PortfolioTarget = 2,
    Package = 3,
    PortfolioTargetMarket = 4,
    PackageAtomicMarket = 5,
    PackageMarketV2 = 6,
}

impl NativeWorkloadKindV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::CommandTape => "command_tape_v5",
            Self::StrategyIr => "strategy_ir_v1",
            Self::PortfolioTarget => "portfolio_target_tape_v1",
            Self::Package => "package_tape_v1",
            Self::PortfolioTargetMarket => "portfolio_target_market_v1",
            Self::PackageAtomicMarket => "package_atomic_market_v1",
            Self::PackageMarketV2 => "package_market_v2",
        }
    }
}

/// Immutable close projection prepared from one exact template/symbol pair.
/// It lets batch callers reuse the strategy-IR input without accepting a raw
/// close slice from another market view by accident.
#[derive(Clone, Debug)]
pub struct StrategyIrCloseProjectionV1 {
    template_fingerprint: [u8; 32],
    symbol: usize,
    closes: Arc<[f64]>,
}

impl StrategyIrCloseProjectionV1 {
    #[must_use]
    pub fn len(&self) -> usize {
        self.closes.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.closes.is_empty()
    }

    /// Return the immutable close column retained by this prepared projection.
    ///
    /// Batch/WFO runtimes may share this allocation across fold views.  The
    /// returned `Arc` is immutable and belongs to the template identity that
    /// created the projection; callers must still validate their own window
    /// bounds before compiling an intent against it.
    #[must_use]
    pub fn values_arc(&self) -> Arc<[f64]> {
        Arc::clone(&self.closes)
    }
}

/// Fully prepared native strategy payload. The program/signal/parameters are
/// retained for provenance, while `command_tape` is compiled once at request
/// construction and is the only object consumed by `FullSession`.
#[derive(Clone, Debug)]
pub struct StrategyIrWorkloadV1 {
    pub program: StrategyProgram,
    pub signal: Box<[f64]>,
    pub parameters: Option<Box<[f64]>>,
    command_tape: CommandTapeV5,
}

impl StrategyIrWorkloadV1 {
    pub fn new(
        template: &NativeExecutionTemplateV1,
        program: StrategyProgram,
        signal: Vec<f64>,
        parameters: Option<Vec<f64>>,
    ) -> Result<Self, String> {
        let symbol = program.symbol().0 as usize;
        if symbol >= template.n_symbols() {
            return Err("native strategy IR symbol is outside prepared market".to_owned());
        }
        let projection = template.strategy_ir_close_projection(symbol)?;
        Self::new_with_projection(template, program, signal, parameters, &projection)
    }

    /// Compile against a typed close projection prepared from `template`.
    /// Batch and walk-forward callers retain that projection once per immutable
    /// market view, rather than allocating it again for every scenario.
    pub fn new_with_projection(
        template: &NativeExecutionTemplateV1,
        program: StrategyProgram,
        signal: Vec<f64>,
        parameters: Option<Vec<f64>>,
        projection: &StrategyIrCloseProjectionV1,
    ) -> Result<Self, String> {
        let symbol = program.symbol().0 as usize;
        if symbol >= template.n_symbols() {
            return Err("native strategy IR symbol is outside prepared market".to_owned());
        }
        if projection.template_fingerprint != template.fingerprint || projection.symbol != symbol {
            return Err(
                "native strategy IR close projection belongs to another prepared market".to_owned(),
            );
        }
        if signal.len() != template.bar_count() || signal.iter().any(|value| !value.is_finite()) {
            return Err("native strategy IR signal must match prepared market bars".to_owned());
        }
        if projection.closes.len() != template.bar_count()
            || projection.closes.iter().any(|value| !value.is_finite())
        {
            return Err(
                "native strategy IR close projection must match prepared market bars".to_owned(),
            );
        }
        let parameters = parameters.map(Vec::into_boxed_slice);
        if let Some(values) = parameters.as_deref()
            && (values.len() != PARAMETER_WIDTH || values.iter().any(|value| !value.is_finite()))
        {
            return Err("native strategy IR parameters have an unsupported shape".to_owned());
        }
        let command_tape = program
            .compile_tape(&signal, &projection.closes, parameters.as_deref())
            .map_err(|error| error.to_string())?;
        Ok(Self {
            program,
            signal: signal.into_boxed_slice(),
            parameters,
            command_tape,
        })
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        &self.command_tape
    }
}

/// Prepared portfolio target tape paired with the already resolved canonical
/// event commands.  Target acceptance may be computed by a higher-level
/// planner, but it never mutates position/account state directly: the paired
/// tape is always executed by `FullSession`.
#[derive(Clone, Debug)]
pub struct PortfolioTargetWorkloadV1 {
    pub targets: PortfolioTargetTape,
    pub policy: PortfolioMarginAllocationPolicy,
    command_tape: CommandTapeV5,
}

impl PortfolioTargetWorkloadV1 {
    pub fn new(
        targets: PortfolioTargetTape,
        policy: PortfolioMarginAllocationPolicy,
        command_tape: CommandTapeV5,
    ) -> Result<Self, String> {
        if targets.n_bars() != command_tape.bars() {
            return Err("portfolio target and command tapes have different bar counts".to_owned());
        }
        Ok(Self {
            targets,
            policy,
            command_tape,
        })
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        &self.command_tape
    }
}

/// Rust-owned target-units workload for the promoted market route.
///
/// The target matrix is research output. At execution time the shared session
/// projects the actual account state before each bar, this workload performs
/// an all-or-none acceptance decision, then emits canonical market commands
/// into the same `FullSession` lifecycle. No Python account/position state is
/// retained or replayed.
#[derive(Clone, Debug)]
pub struct PortfolioTargetMarketWorkloadV1 {
    pub targets: PortfolioTargetTape,
    pub tradable: Box<[bool]>,
    pub stale: Box<[bool]>,
    pub min_qty: Box<[f64]>,
    pub min_notional: Box<[f64]>,
    pub external_id_start: i64,
    empty_tape: CommandTapeV5,
}

impl PortfolioTargetMarketWorkloadV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        targets: PortfolioTargetTape,
        tradable: Vec<bool>,
        stale: Vec<bool>,
        min_qty: Vec<f64>,
        min_notional: Vec<f64>,
        external_id_start: i64,
    ) -> Result<Self, String> {
        let width = targets
            .n_bars()
            .checked_mul(targets.n_symbols())
            .ok_or_else(|| "portfolio target market dimensions overflow".to_owned())?;
        if tradable.len() != width
            || stale.len() != width
            || min_qty.len() != targets.n_symbols()
            || min_notional.len() != targets.n_symbols()
            || min_qty
                .iter()
                .any(|value| !value.is_finite() || *value < 0.0)
            || min_notional
                .iter()
                .any(|value| !value.is_finite() || *value < 0.0)
        {
            return Err("portfolio target market workload has invalid constraints".to_owned());
        }
        let empty_tape = CommandTapeV5::new(vec![0; targets.n_bars() + 1], Vec::new())
            .map_err(|error| error.to_string())?;
        Ok(Self {
            targets,
            tradable: tradable.into_boxed_slice(),
            stale: stale.into_boxed_slice(),
            min_qty: min_qty.into_boxed_slice(),
            min_notional: min_notional.into_boxed_slice(),
            external_id_start,
            empty_tape,
        })
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        &self.empty_tape
    }

    #[must_use]
    pub fn tradable_at(&self, bar: usize) -> &[bool] {
        let start = bar * self.targets.n_symbols();
        &self.tradable[start..start + self.targets.n_symbols()]
    }

    #[must_use]
    pub fn stale_at(&self, bar: usize) -> &[bool] {
        let start = bar * self.targets.n_symbols();
        &self.stale[start..start + self.targets.n_symbols()]
    }
}

/// Prepared multi-leg package intent plus its accepted canonical commands.
/// Preflight and reservation provenance stays immutable here; execution fills,
/// costs, lifecycle, and terminal account state are still owned solely by the
/// shared `FullSession`.
#[derive(Clone, Debug)]
pub struct PackageTapeV1 {
    pub plan: PackagePlan,
    pub preflight: PackageExecutionResult,
    command_tape: CommandTapeV5,
}

impl PackageTapeV1 {
    pub fn new(
        plan: PackagePlan,
        preflight: PackageExecutionResult,
        command_tape: CommandTapeV5,
    ) -> Result<Self, String> {
        if plan.id != preflight.package_id
            || plan.policy != preflight.policy
            || plan.legs.len() != preflight.accepted.len()
            || plan.legs.len() != preflight.rejection_reasons.len()
        {
            return Err("package tape does not match package preflight provenance".to_owned());
        }
        Ok(Self {
            plan,
            preflight,
            command_tape,
        })
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        &self.command_tape
    }
}

/// One exact same-bar atomic package request. Any unsupported package policy
/// remains outside this promoted workload and must use the Python reference
/// route with an explicit capability reason.
#[derive(Clone, Debug)]
pub struct PackageAtomicMarketWorkloadV1 {
    pub plan: PackagePlan,
    pub legs: Box<[PackageLegRequest]>,
    pub command_bar: usize,
    pub max_staleness_ns: i64,
    empty_tape: CommandTapeV5,
}

impl PackageAtomicMarketWorkloadV1 {
    pub fn new(
        n_bars: usize,
        plan: PackagePlan,
        legs: Vec<PackageLegRequest>,
        command_bar: usize,
        max_staleness_ns: i64,
    ) -> Result<Self, String> {
        if n_bars == 0
            || command_bar == 0
            || command_bar >= n_bars
            || plan.policy != PackagePolicy::AtomicBarSimulation
            || plan.legs.len() != legs.len()
            || plan
                .legs
                .iter()
                .zip(legs.iter())
                .any(|(reference, leg)| reference.order_id != leg.order_id)
        {
            return Err("native atomic package workload has invalid immutable plan".to_owned());
        }
        let empty_tape = CommandTapeV5::new(vec![0; n_bars + 1], Vec::new())
            .map_err(|error| error.to_string())?;
        Ok(Self {
            plan,
            legs: legs.into_boxed_slice(),
            command_bar,
            max_staleness_ns,
            empty_tape,
        })
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        &self.empty_tape
    }
}

/// Tagged immutable workload family.  None of these variants stores a Python
/// callback or a second mutable execution state.
#[derive(Clone, Debug)]
pub enum WorkloadPayloadV1 {
    CommandTape(CommandTapeV5),
    StrategyIr(StrategyIrWorkloadV1),
    PortfolioTarget(PortfolioTargetWorkloadV1),
    Package(PackageTapeV1),
    PortfolioTargetMarket(PortfolioTargetMarketWorkloadV1),
    PackageAtomicMarket(PackageAtomicMarketWorkloadV1),
    PackageMarketV2(PackageMarketWorkloadV2),
}

impl WorkloadPayloadV1 {
    #[must_use]
    pub const fn kind(&self) -> NativeWorkloadKindV1 {
        match self {
            Self::CommandTape(_) => NativeWorkloadKindV1::CommandTape,
            Self::StrategyIr(_) => NativeWorkloadKindV1::StrategyIr,
            Self::PortfolioTarget(_) => NativeWorkloadKindV1::PortfolioTarget,
            Self::Package(_) => NativeWorkloadKindV1::Package,
            Self::PortfolioTargetMarket(_) => NativeWorkloadKindV1::PortfolioTargetMarket,
            Self::PackageAtomicMarket(_) => NativeWorkloadKindV1::PackageAtomicMarket,
            Self::PackageMarketV2(_) => NativeWorkloadKindV1::PackageMarketV2,
        }
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        match self {
            Self::CommandTape(tape) => tape,
            Self::StrategyIr(workload) => workload.command_tape(),
            Self::PortfolioTarget(workload) => workload.command_tape(),
            Self::Package(workload) => workload.command_tape(),
            Self::PortfolioTargetMarket(workload) => workload.command_tape(),
            Self::PackageAtomicMarket(workload) => workload.command_tape(),
            Self::PackageMarketV2(workload) => workload.command_tape(),
        }
    }
}

/// Immutable native preparation shared by static, IR, batch, portfolio, and
/// package workloads. It owns no account/order/lifecycle state; it only fixes
/// the market view, instrument/account/contract configuration, and its content
/// fingerprint once before execution begins.
#[derive(Clone)]
pub struct NativeExecutionTemplateV1 {
    market: Arc<FullMarketData>,
    market_start: usize,
    market_end: usize,
    instruments: InstrumentTableV1,
    account: AccountModelV1,
    contract: ExecutionContractV1,
    fingerprint: [u8; 32],
}

/// Cold-path provenance for a dynamic workload. Score and compact profiles
/// retain only the scalar counters; audit profile retains flat decision rows.
/// This is intentionally separate from the canonical fill/event output so it
/// cannot become a second execution ledger.
#[derive(Clone, Debug, Default)]
pub struct PortfolioTargetAuditV1 {
    pub bar: Vec<i64>,
    pub requested_units: Vec<f64>,
    pub accepted_units: Vec<f64>,
    pub rejection_code: Vec<i64>,
    pub decision_count: usize,
    pub rejected_decision_count: usize,
    /// Bounded target-admission rows. Aggregate counters above remain exact
    /// even when the optional diagnostic rows are truncated.
    pub detail_retention: AuditRetentionV1,
}

impl PortfolioTargetAuditV1 {
    fn with_detail_limit(detail_row_limit: usize) -> Self {
        Self {
            detail_retention: AuditRetentionV1::new(detail_row_limit),
            ..Self::default()
        }
    }

    fn record(
        &mut self,
        bar: usize,
        requested_units: f64,
        accepted_units: f64,
        rejection_code: i64,
    ) {
        if !self.detail_retention.retain_next() {
            return;
        }
        self.bar.push(bar as i64);
        self.requested_units.push(requested_units);
        self.accepted_units.push(accepted_units);
        self.rejection_code.push(rejection_code);
    }
}

#[derive(Clone, Debug, Default)]
pub struct PackageAtomicAuditV1 {
    pub command_bar: i64,
    pub package_id: u64,
    pub accepted: Vec<bool>,
    pub rejection_code: Vec<i64>,
    pub transition_code: Vec<i64>,
    pub reserved_margin: f64,
    pub released_margin: f64,
    pub package_fee: f64,
    pub residual_notional: f64,
    pub attempted: bool,
    /// One shared cap covers leg outcomes and package transitions, so a large
    /// package cannot bypass the audit-memory contract through two vectors.
    pub detail_retention: AuditRetentionV1,
}

impl PackageAtomicAuditV1 {
    fn with_detail_limit(command_bar: usize, package_id: u64, detail_row_limit: usize) -> Self {
        Self {
            command_bar: command_bar as i64,
            package_id,
            detail_retention: AuditRetentionV1::new(detail_row_limit),
            ..Self::default()
        }
    }

    fn record_leg(&mut self, accepted: bool, rejection_code: i64) {
        if !self.detail_retention.retain_next() {
            return;
        }
        self.accepted.push(accepted);
        self.rejection_code.push(rejection_code);
    }

    fn record_transition(&mut self, transition_code: i64) {
        if self.detail_retention.retain_next() {
            self.transition_code.push(transition_code);
        }
    }
}

#[derive(Clone, Debug, Default)]
pub enum NativeWorkloadAuditV1 {
    #[default]
    None,
    PortfolioTarget(PortfolioTargetAuditV1),
    PackageAtomic(PackageAtomicAuditV1),
    // Package V2 has many bounded provenance vectors. Keep that audit behind
    // one allocation so score/compact workflow enums do not reserve its full
    // inline footprint on every execution result.
    PackageMarketV2(Box<PackageMarketAuditV2>),
}

impl NativeWorkloadAuditV1 {
    #[must_use]
    pub const fn detail_retention(&self) -> AuditRetentionV1 {
        match self {
            Self::None => AuditRetentionV1::new(0),
            Self::PortfolioTarget(audit) => audit.detail_retention,
            Self::PackageAtomic(audit) => audit.detail_retention,
            Self::PackageMarketV2(audit) => audit.detail_retention,
        }
    }
}

impl NativeExecutionTemplateV1 {
    pub fn new(
        market: Arc<FullMarketData>,
        instruments: InstrumentTableV1,
        account: AccountModelV1,
        contract: ExecutionContractV1,
    ) -> Result<Self, String> {
        let market_end = market.n_bars;
        Self::new_window(market, 0, market_end, instruments, account, contract)
    }

    /// Create a zero-copy local market view. The source tape remains owned by
    /// the same `Arc`; local bar zero is the frozen snapshot of this view.
    pub fn new_window(
        market: Arc<FullMarketData>,
        market_start: usize,
        market_end: usize,
        instruments: InstrumentTableV1,
        account: AccountModelV1,
        contract: ExecutionContractV1,
    ) -> Result<Self, String> {
        if market_start >= market_end
            || market_end > market.n_bars
            || market.n_symbols != instruments.len()
        {
            return Err(
                "native execution template does not match the prepared market view".to_owned(),
            );
        }
        let fingerprint = fingerprint_template(
            &market,
            market_start,
            market_end,
            &instruments,
            account,
            contract,
        );
        Ok(Self {
            market,
            market_start,
            market_end,
            instruments,
            account,
            contract,
            fingerprint,
        })
    }

    /// Reconstruct an immutable template from the one authoritative Rust
    /// session configuration. This is used by compatibility batch APIs and
    /// does not import mutable session state.
    pub fn from_session(session: &FullSession) -> Result<Self, String> {
        let (market_start, market_end) = session.market_range();
        Self::new_window(
            session.market.clone(),
            market_start,
            market_end,
            InstrumentTableV1::sequential(
                session.contract_sizes.to_vec(),
                session.leverages.to_vec(),
                session.fee_rates.to_vec(),
            )?,
            AccountModelV1::new(
                session.initial_capital,
                session.maintenance_ratio,
                session.slippage,
                session.use_funding,
            )?,
            ExecutionContractV1::new(session.event_contract_code)?,
        )
    }

    /// Make a no-copy subrange relative to this template's local bar clock.
    pub fn window(&self, start: usize, end: usize) -> Result<Self, String> {
        if start >= end || end > self.bar_count() {
            return Err("native execution template window is outside the prepared view".to_owned());
        }
        Self::new_window(
            self.market.clone(),
            self.market_start + start,
            self.market_start + end,
            self.instruments.clone(),
            self.account,
            self.contract,
        )
    }

    #[must_use]
    pub const fn bar_count(&self) -> usize {
        self.market_end - self.market_start
    }

    #[must_use]
    pub fn n_symbols(&self) -> usize {
        self.market.n_symbols
    }

    #[must_use]
    pub const fn market_range(&self) -> (usize, usize) {
        (self.market_start, self.market_end)
    }

    #[must_use]
    pub fn market(&self) -> &Arc<FullMarketData> {
        &self.market
    }

    /// Immutable account model fixed by this prepared template.
    #[must_use]
    pub const fn account(&self) -> AccountModelV1 {
        self.account
    }

    /// Immutable instrument table fixed by this prepared template.
    #[must_use]
    pub fn instruments(&self) -> &InstrumentTableV1 {
        &self.instruments
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
    pub fn source_market_bytes(&self) -> usize {
        self.market.timestamps_ns.len() * std::mem::size_of::<i64>()
            + self.market.opens.len() * std::mem::size_of::<f64>()
            + self.market.highs.len() * std::mem::size_of::<f64>()
            + self.market.lows.len() * std::mem::size_of::<f64>()
            + self.market.closes.len() * std::mem::size_of::<f64>()
            + self.market.volumes.len() * std::mem::size_of::<f64>()
            + self.market.funding.len() * std::mem::size_of::<f64>()
            + self.market.funding_mask.len() * std::mem::size_of::<bool>()
    }

    #[must_use]
    pub fn view_bytes(&self) -> usize {
        let bars = self.bar_count();
        bars * std::mem::size_of::<i64>()
            + bars * self.n_symbols() * (6 * std::mem::size_of::<f64>())
            + bars * std::mem::size_of::<bool>()
    }

    pub fn strategy_ir_close_projection(
        &self,
        symbol: usize,
    ) -> Result<StrategyIrCloseProjectionV1, String> {
        if symbol >= self.n_symbols() {
            return Err("native strategy IR symbol is outside prepared market".to_owned());
        }
        Ok(StrategyIrCloseProjectionV1 {
            template_fingerprint: self.fingerprint,
            symbol,
            closes: (0..self.bar_count())
                .map(|bar| {
                    self.market.closes[(self.market_start + bar) * self.n_symbols() + symbol]
                })
                .collect::<Vec<_>>()
                .into(),
        })
    }

    fn fresh_session(&self) -> Result<FullSession, String> {
        let mut session = FullSession::new_window(
            self.market.clone(),
            self.market_start,
            self.market_end,
            self.instruments.contract_sizes.to_vec(),
            self.instruments.leverages.to_vec(),
            self.instruments.fee_rates.to_vec(),
            self.account.initial_capital,
            self.account.maintenance_ratio,
            self.account.slippage_rate,
            self.account.use_funding,
        )?;
        session.set_event_contract(self.contract.event_contract_code)?;
        Ok(session)
    }
}

/// The only reusable mutable native state for prepared workloads. It is Rust
/// owned, reset between independent scenarios, and never shares an account or
/// lifecycle across workers/folds.
pub struct NativeExecutionRunnerV1 {
    template: Arc<NativeExecutionTemplateV1>,
    session: FullSession,
    generation: u64,
    run_count: u64,
    explicit_reset_count: u64,
}

impl NativeExecutionRunnerV1 {
    pub fn new(template: Arc<NativeExecutionTemplateV1>) -> Result<Self, String> {
        Self::new_with_generation(template, 0)
    }

    /// Construct a fresh mutable session while preserving a caller-owned
    /// lifecycle generation. This is used by explicit full rebuilds so result
    /// provenance never moves backward merely because capacities were dropped.
    pub fn new_with_generation(
        template: Arc<NativeExecutionTemplateV1>,
        generation: u64,
    ) -> Result<Self, String> {
        let session = template.fresh_session()?;
        Ok(Self {
            template,
            session,
            generation,
            run_count: 0,
            explicit_reset_count: 0,
        })
    }

    /// Reset the mutable account, orders, indexes, and session cursors for an
    /// independent scenario. Immutable market and instrument preparation is
    /// retained through the template `Arc`.
    pub fn reset_account_and_orders(&mut self) -> Result<(), String> {
        self.reset_for_execution()?;
        self.explicit_reset_count = self
            .explicit_reset_count
            .checked_add(1)
            .ok_or_else(|| "native execution runner reset count overflow".to_owned())?;
        Ok(())
    }

    fn reset_for_execution(&mut self) -> Result<(), String> {
        self.session.reset();
        self.session
            .set_event_contract(self.template.contract.event_contract_code)?;
        self.generation = self
            .generation
            .checked_add(1)
            .ok_or_else(|| "native execution runner generation overflow".to_owned())?;
        Ok(())
    }

    /// Release reusable per-step scratch capacity above the requested bound.
    /// Results are never retained by this runner, so this cannot invalidate a
    /// previously returned typed output.
    pub fn release_transient_buffers(&mut self, max_capacity: usize) {
        self.session.release_step_buffer_capacity(max_capacity);
    }

    #[must_use]
    pub fn step_buffer_capacities(&self) -> (usize, usize, usize) {
        self.session.step_buffer_capacities()
    }

    /// Cold-path diagnostics for the authoritative runner. These values are
    /// observed after the native execution pass; they are never required to
    /// execute a typed request or materialize a Python result.
    #[must_use]
    pub fn order_arena_counters(&self) -> (usize, usize, u64, u64) {
        (
            self.session.orders_len(),
            self.session.orders_capacity(),
            self.session.compaction_count,
            self.session.terminal_orders_removed,
        )
    }

    #[must_use]
    pub fn engine_scan_counters(&self) -> (u64, u64, u64) {
        self.session.engine_scan_counters()
    }

    #[must_use]
    pub fn margin_recompute_count(&self) -> u64 {
        self.session.margin_recompute_count()
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn run_count(&self) -> u64 {
        self.run_count
    }

    #[must_use]
    pub const fn explicit_reset_count(&self) -> u64 {
        self.explicit_reset_count
    }

    pub fn execute_request(
        &mut self,
        request: &NativeExecutionRequestV1,
    ) -> Result<NativeExecutionResultV1, String> {
        if self.template.fingerprint != request.template.fingerprint {
            return Err("native execution runner/template mismatch".to_owned());
        }
        let (output, command_count, workload_audit) =
            self.execute_workload_detailed(request.output_requirements(), &request.workload)?;
        let header_v2 = NativeResultHeaderV2::from_authoritative_run(
            self.generation,
            request,
            &self.session,
            &output,
            &workload_audit,
        );
        Ok(NativeExecutionResultV1 {
            request_version: request.request_version(),
            protocol_version: request.protocol_version(),
            request_fingerprint: request.fingerprint,
            template_fingerprint: self.template.fingerprint,
            workload_kind: request.workload.kind(),
            output_profile: request.output,
            command_count,
            bar_count: self.template.bar_count(),
            execution_generation: self.generation,
            runner_run_count: self.run_count,
            header_v2,
            output,
            workload_audit,
        })
    }

    /// Execute one already validated native workload using the same Rust-owned
    /// session buffer after a deterministic account/order reset. Batch callers
    /// use this to avoid allocating a full session per scenario.
    pub fn execute_workload(
        &mut self,
        output: NativeOutputProfileV1,
        workload: &WorkloadPayloadV1,
    ) -> Result<NativeExecutionOutputV1, String> {
        self.execute_workload_detailed(
            OutputRequirementsV1::resolve(static_profile(output)),
            workload,
        )
        .map(|(result, _, _)| result)
    }

    fn execute_workload_detailed(
        &mut self,
        requirements: OutputRequirementsV1,
        workload: &WorkloadPayloadV1,
    ) -> Result<(NativeExecutionOutputV1, usize, NativeWorkloadAuditV1), String> {
        validate_workload(&self.template, workload)?;
        self.reset_for_execution()?;
        let result = match workload {
            WorkloadPayloadV1::PortfolioTargetMarket(workload) => {
                self.execute_portfolio_target_market(requirements, workload)
            }
            WorkloadPayloadV1::PackageAtomicMarket(workload) => {
                self.execute_package_atomic_market(requirements, workload)
            }
            WorkloadPayloadV1::PackageMarketV2(workload) => {
                self.execute_package_market_v2(requirements, workload)
            }
            _ => self.execute_static_workload(requirements, workload),
        };
        if result.is_ok() {
            self.run_count = self
                .run_count
                .checked_add(1)
                .ok_or_else(|| "native execution runner run count overflow".to_owned())?;
        }
        result
    }

    fn execute_static_workload(
        &mut self,
        requirements: OutputRequirementsV1,
        workload: &WorkloadPayloadV1,
    ) -> Result<(NativeExecutionOutputV1, usize, NativeWorkloadAuditV1), String> {
        let tape = workload.command_tape();
        let result = self
            .session
            .run_typed_output_with_requirements_v1(tape, requirements);
        result.map(|value| (value, tape.command_count(), NativeWorkloadAuditV1::None))
    }

    fn execute_portfolio_target_market(
        &mut self,
        requirements: OutputRequirementsV1,
        workload: &PortfolioTargetMarketWorkloadV1,
    ) -> Result<(NativeExecutionOutputV1, usize, NativeWorkloadAuditV1), String> {
        let n_symbols = self.template.n_symbols();
        let symbol_ids = self.template.instruments.symbol_ids.to_vec();
        let contract_sizes = self.template.instruments.contract_sizes.to_vec();
        let leverages = self.template.instruments.leverages.to_vec();
        let fee_rates = self.template.instruments.fee_rates.to_vec();
        let slippage_rate = self.template.account.slippage_rate;
        let slippage_rates = vec![slippage_rate; n_symbols];
        let mut prices = vec![0.0; n_symbols];
        let mut audit =
            PortfolioTargetAuditV1::with_detail_limit(requirements.detail_row_limit.unwrap_or(0));
        let retain_audit = requirements.retain_detail;
        let (native_output, command_count) =
            self.session.run_typed_dynamic_output_with_requirements_v1(
                requirements,
                |bar, session, commands| {
                    let requested = workload.targets.targets_at(bar);
                    let changed = requested
                        .iter()
                        .zip(session.positions.iter())
                        .any(|(target, current)| (target - current).abs() > 1e-12);
                    if !changed {
                        return Ok(());
                    }
                    let projection = session.project_pre_command_account_v1(bar)?;
                    if projection.liquidated {
                        audit.decision_count += 1;
                        audit.rejected_decision_count += 1;
                        if retain_audit {
                            for (index, target) in requested.iter().copied().enumerate() {
                                audit.record(
                                    bar,
                                    target,
                                    session.positions[index],
                                    quantbt_portfolio::PortfolioTargetRejectReason::PostCostMargin
                                        as i64,
                                );
                            }
                        }
                        return Ok(());
                    }
                    for (symbol, price) in prices.iter_mut().enumerate() {
                        *price = session.close_price_at(bar, symbol)?;
                    }
                    let execution = quantbt_portfolio::execute_portfolio_target_market_all_or_none(
                        quantbt_portfolio::PortfolioTargetRequest {
                            previous_units: &session.positions,
                            requested_units: requested,
                            prices: &prices,
                            equity: projection.equity,
                            contract_sizes: &contract_sizes,
                            leverages: &leverages,
                            fee_rates: &fee_rates,
                            slippage_rates: &slippage_rates,
                            tradable: workload.tradable_at(bar),
                            stale: workload.stale_at(bar),
                            min_qty: &workload.min_qty,
                            min_notional: &workload.min_notional,
                            reserved_margin: 0.0,
                            policy: PortfolioMarginAllocationPolicy::AllOrNoneTarget,
                        },
                    )?;
                    audit.decision_count += 1;
                    if execution.rejection_reasons.iter().any(|reason| {
                        *reason != quantbt_portfolio::PortfolioTargetRejectReason::Accepted
                    }) {
                        audit.rejected_decision_count += 1;
                    }
                    if retain_audit {
                        for (index, requested_units) in requested.iter().copied().enumerate() {
                            audit.record(
                                bar,
                                requested_units,
                                execution.accepted_units[index],
                                execution.rejection_reasons[index] as i64,
                            );
                        }
                    }
                    let bar_offset = i64::try_from(bar)
                        .ok()
                        .and_then(|value| value.checked_mul(n_symbols as i64))
                        .ok_or_else(|| "portfolio target external id range overflow".to_owned())?;
                    let external_id_start = workload
                        .external_id_start
                        .checked_add(bar_offset)
                        .ok_or_else(|| "portfolio target external id range overflow".to_owned())?;
                    commands.extend(quantbt_portfolio::compile_target_delta_commands(
                        &symbol_ids,
                        &session.positions,
                        &execution,
                        external_id_start,
                    )?);
                    Ok(())
                },
            )?;
        Ok((
            native_output,
            command_count,
            NativeWorkloadAuditV1::PortfolioTarget(audit),
        ))
    }

    fn execute_package_atomic_market(
        &mut self,
        requirements: OutputRequirementsV1,
        workload: &PackageAtomicMarketWorkloadV1,
    ) -> Result<(NativeExecutionOutputV1, usize, NativeWorkloadAuditV1), String> {
        let n_symbols = self.template.n_symbols();
        let contract_sizes = self.template.instruments.contract_sizes.to_vec();
        let leverages = self.template.instruments.leverages.to_vec();
        let fee_rates = self.template.instruments.fee_rates.to_vec();
        let slippage_rate = self.template.account.slippage_rate;
        let mut prices = vec![0.0; n_symbols];
        let mut resolved_legs = workload.legs.to_vec();
        let mut audit = PackageAtomicAuditV1::with_detail_limit(
            workload.command_bar,
            workload.plan.id.0,
            requirements.detail_row_limit.unwrap_or(0),
        );
        let retain_audit = requirements.retain_detail;
        let (native_output, command_count) =
            self.session.run_typed_dynamic_output_with_requirements_v1(
                requirements,
                |bar, session, commands| {
                    if bar != workload.command_bar {
                        return Ok(());
                    }
                    audit.attempted = true;
                    let projection = session.project_pre_command_account_v1(bar)?;
                    if projection.liquidated {
                        if retain_audit {
                            for _ in 0..workload.legs.len() {
                                audit.record_leg(
                                    false,
                                    quantbt_package::PackageRejectReason::PostCostMargin as i64,
                                );
                            }
                        }
                        return Ok(());
                    }
                    for (symbol, price) in prices.iter_mut().enumerate() {
                        *price = session.close_price_at(bar, symbol)?;
                    }
                    for leg in &mut resolved_legs {
                        let symbol = leg.symbol.0 as usize;
                        leg.price = prices[symbol];
                        leg.contract_size = contract_sizes[symbol];
                        leg.fee_rate = fee_rates[symbol];
                        leg.initial_margin = leg.signed_qty.abs() * leg.price * leg.contract_size
                            / leverages[symbol];
                    }
                    let result = quantbt_package::execute_package_market_atomic(
                        quantbt_package::PackageMarketExecutionRequest {
                            package_id: workload.plan.id,
                            legs: &resolved_legs,
                            previous_units: &session.positions,
                            close_prices: &prices,
                            contract_sizes: &contract_sizes,
                            leverages: &leverages,
                            fee_rates: &fee_rates,
                            slippage_rate,
                            equity: projection.equity,
                            policy: PackagePolicy::AtomicBarSimulation,
                            max_staleness_ns: workload.max_staleness_ns,
                        },
                    )?;
                    if retain_audit {
                        for (accepted, rejection_reason) in result
                            .accepted
                            .iter()
                            .copied()
                            .zip(result.rejection_reasons.iter().copied())
                        {
                            audit.record_leg(accepted, rejection_reason as i64);
                        }
                        for event in result.transitions.iter().copied() {
                            audit.record_transition(package_event_code(event) as i64);
                        }
                    }
                    audit.reserved_margin = result.reserved_margin;
                    audit.released_margin = result.released_margin;
                    audit.package_fee = result.package_fee;
                    audit.residual_notional = result.residual_notional;
                    commands.extend(quantbt_package::compile_package_commands(
                        workload.plan.id,
                        &resolved_legs,
                        &result,
                    )?);
                    Ok(())
                },
            )?;
        Ok((
            native_output,
            command_count,
            NativeWorkloadAuditV1::PackageAtomic(audit),
        ))
    }

    /// Execute bounded V2 package planning in the same dynamic session used
    /// by target workloads. The package domain computes only a deterministic
    /// preview and exact submitted quantities; `FullSession` commits every
    /// emitted command, owns the canonical fill/event trace, and updates the
    /// one linear account. There is deliberately no package-local ledger.
    fn execute_package_market_v2(
        &mut self,
        requirements: OutputRequirementsV1,
        workload: &PackageMarketWorkloadV2,
    ) -> Result<(NativeExecutionOutputV1, usize, NativeWorkloadAuditV1), String> {
        let n_symbols = self.template.n_symbols();
        let contract_sizes = self.template.instruments.contract_sizes.to_vec();
        let leverages = self.template.instruments.leverages.to_vec();
        let fee_rates = self.template.instruments.fee_rates.to_vec();
        let slippage_rate = self.template.account.slippage_rate;
        let mut prices = vec![0.0; n_symbols];
        let mut audit =
            PackageMarketAuditV2::with_detail_limit(requirements.detail_row_limit.unwrap_or(0));
        let (native_output, command_count) =
            self.session.run_typed_dynamic_output_with_requirements_v1(
                requirements,
                |bar, session, commands| {
                    let Some(intent) = workload.intent_at(bar) else {
                        return Ok(());
                    };
                    let projection = session.project_pre_command_account_v1(bar)?;
                    if projection.liquidated {
                        let result = quantbt_package::abort_package_market_v2(
                            intent,
                            quantbt_package::PackageRejectReasonV2::PostCostMargin,
                        );
                        audit.record(intent, &result);
                        return Ok(());
                    }
                    for (symbol, price) in prices.iter_mut().enumerate() {
                        *price = session.close_price_at(bar, symbol)?;
                    }
                    let result = quantbt_package::execute_package_market_v2(
                        PackageMarketExecutionRequestV2 {
                            intent,
                            previous_units: &session.positions,
                            close_prices: &prices,
                            contract_sizes: &contract_sizes,
                            leverages: &leverages,
                            fee_rates: &fee_rates,
                            slippage_rate,
                            equity: projection.equity,
                        },
                    )?;
                    // The deterministic V2 preview is emitted as canonical
                    // market commands immediately. Under the bounded linear
                    // contract these quantities are the actual session fills;
                    // a future L2 venue model must add a new contract rather
                    // than reinterpret `fill_fraction` here.
                    commands.extend(quantbt_package::compile_package_commands_v2(
                        intent, &result,
                    )?);
                    audit.record(intent, &result);
                    Ok(())
                },
            )?;
        Ok((
            native_output,
            command_count,
            NativeWorkloadAuditV1::PackageMarketV2(Box::new(audit)),
        ))
    }
}

const fn static_profile(output: NativeOutputProfileV1) -> StaticOutputProfile {
    match output {
        NativeOutputProfileV1::Score => StaticOutputProfile::Score,
        NativeOutputProfileV1::Compact => StaticOutputProfile::Compact,
        NativeOutputProfileV1::Audit => StaticOutputProfile::Audit,
    }
}

/// Immutable request passed to one shared Rust execution runner. Construction
/// resolves all workload data before the hot loop; execution cannot create a
/// second Python ledger or mutate the immutable contract.
#[derive(Clone)]
pub struct NativeExecutionRequestV1 {
    template: Arc<NativeExecutionTemplateV1>,
    output: NativeOutputProfileV1,
    audit_detail_row_limit: Option<usize>,
    workload: WorkloadPayloadV1,
    fingerprint: [u8; 32],
}

impl NativeExecutionRequestV1 {
    pub fn new(
        market: Arc<FullMarketData>,
        instruments: InstrumentTableV1,
        account: AccountModelV1,
        contract: ExecutionContractV1,
        output: NativeOutputProfileV1,
        workload: WorkloadPayloadV1,
    ) -> Result<Self, String> {
        let template = Arc::new(NativeExecutionTemplateV1::new(
            market,
            instruments,
            account,
            contract,
        )?);
        Self::from_template(template, output, workload)
    }

    pub fn from_template(
        template: Arc<NativeExecutionTemplateV1>,
        output: NativeOutputProfileV1,
        workload: WorkloadPayloadV1,
    ) -> Result<Self, String> {
        validate_workload(&template, &workload)?;
        let audit_detail_row_limit =
            OutputRequirementsV1::resolve(static_profile(output)).detail_row_limit;
        let fingerprint = fingerprint_request(&template, output, audit_detail_row_limit, &workload);
        Ok(Self {
            template,
            output,
            audit_detail_row_limit,
            workload,
            fingerprint,
        })
    }

    /// Return a new immutable audit request with an explicit combined
    /// fill/event retention limit. The bound changes only diagnostic output,
    /// but is included in the request fingerprint so prepared caches cannot
    /// reuse an artifact under a different retention contract.
    pub fn with_audit_detail_limit(mut self, detail_row_limit: usize) -> Result<Self, String> {
        if self.output != NativeOutputProfileV1::Audit {
            return Err("audit detail limit is only valid for audit output".to_owned());
        }
        self.audit_detail_row_limit = Some(detail_row_limit);
        self.fingerprint = fingerprint_request(
            &self.template,
            self.output,
            self.audit_detail_row_limit,
            &self.workload,
        );
        Ok(self)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn from_strategy_ir(
        market: Arc<FullMarketData>,
        instruments: InstrumentTableV1,
        account: AccountModelV1,
        contract: ExecutionContractV1,
        output: NativeOutputProfileV1,
        program: StrategyProgram,
        signal: Vec<f64>,
        parameters: Option<Vec<f64>>,
    ) -> Result<Self, String> {
        let template = Arc::new(NativeExecutionTemplateV1::new(
            market,
            instruments,
            account,
            contract,
        )?);
        Self::from_strategy_ir_template(template, output, program, signal, parameters)
    }

    pub fn from_strategy_ir_template(
        template: Arc<NativeExecutionTemplateV1>,
        output: NativeOutputProfileV1,
        program: StrategyProgram,
        signal: Vec<f64>,
        parameters: Option<Vec<f64>>,
    ) -> Result<Self, String> {
        let workload = StrategyIrWorkloadV1::new(&template, program, signal, parameters)?;
        Self::from_template(template, output, WorkloadPayloadV1::StrategyIr(workload))
    }

    /// Build the bounded Rust-owned portfolio target route.  Allocation stays
    /// outside this type; the immutable input is a bar-major target-units
    /// matrix plus per-bar tradability/staleness masks. At run time Rust
    /// resolves each accepted delta from the live session projection.
    #[allow(clippy::too_many_arguments)]
    pub fn from_template_portfolio_target_market(
        template: Arc<NativeExecutionTemplateV1>,
        output: NativeOutputProfileV1,
        target_units: Vec<f64>,
        tradable: Vec<bool>,
        stale: Vec<bool>,
        min_qty: Vec<f64>,
        min_notional: Vec<f64>,
        external_id_start: i64,
    ) -> Result<Self, String> {
        if template.contract.event_contract_code != CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE {
            return Err(
                "native portfolio target market route requires event_lifecycle_v2_next_bar_close"
                    .to_owned(),
            );
        }
        let targets =
            PortfolioTargetTape::new(template.bar_count(), template.n_symbols(), target_units)?;
        let workload = PortfolioTargetMarketWorkloadV1::new(
            targets,
            tradable,
            stale,
            min_qty,
            min_notional,
            external_id_start,
        )?;
        Self::from_template(
            template,
            output,
            WorkloadPayloadV1::PortfolioTargetMarket(workload),
        )
    }

    /// Build the bounded same-bar atomic package route. Only the policy that
    /// is modeled end-to-end (`AtomicBarSimulation`) is accepted here; every
    /// other package policy remains an explicit Python-reference route.
    pub fn from_template_package_atomic_market(
        template: Arc<NativeExecutionTemplateV1>,
        output: NativeOutputProfileV1,
        plan: PackagePlan,
        legs: Vec<PackageLegRequest>,
        command_bar: usize,
        max_staleness_ns: i64,
    ) -> Result<Self, String> {
        if template.contract.event_contract_code != CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE {
            return Err(
                "native atomic package market route requires event_lifecycle_v2_next_bar_close"
                    .to_owned(),
            );
        }
        let workload = PackageAtomicMarketWorkloadV1::new(
            template.bar_count(),
            plan,
            legs,
            command_bar,
            max_staleness_ns,
        )?;
        Self::from_template(
            template,
            output,
            WorkloadPayloadV1::PackageAtomicMarket(workload),
        )
    }

    /// Build an immutable bounded same-account package request.  V2 accepts
    /// only exact deterministic OHLC-bar scenarios: a package may execute on
    /// a command bar, and one subsequent bar remains available for canonical
    /// session reconciliation/inspection.  It is not a claim of native venue
    /// OCO, L2 queue, cross-currency, or multi-account semantics.
    pub fn from_template_package_market_v2(
        template: Arc<NativeExecutionTemplateV1>,
        output: NativeOutputProfileV1,
        intents: Vec<PackageIntentV2>,
    ) -> Result<Self, String> {
        if template.contract.event_contract_code != CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE {
            return Err(
                "native package V2 market route requires event_lifecycle_v2_next_bar_close"
                    .to_owned(),
            );
        }
        let workload = PackageMarketWorkloadV2::new(template.bar_count(), intents)?;
        Self::from_template(
            template,
            output,
            WorkloadPayloadV1::PackageMarketV2(workload),
        )
    }

    #[must_use]
    pub const fn request_version(&self) -> u16 {
        NATIVE_EXECUTION_REQUEST_VERSION_V1
    }

    #[must_use]
    pub const fn protocol_version(&self) -> u16 {
        NATIVE_EXECUTION_PROTOCOL_VERSION_V1
    }

    #[must_use]
    pub const fn output_profile(&self) -> NativeOutputProfileV1 {
        self.output
    }

    #[must_use]
    pub const fn audit_detail_row_limit(&self) -> Option<usize> {
        self.audit_detail_row_limit
    }

    #[must_use]
    pub fn output_requirements(&self) -> OutputRequirementsV1 {
        match self.audit_detail_row_limit {
            Some(limit) => OutputRequirementsV1::audit_with_detail_limit(limit),
            None => OutputRequirementsV1::resolve(static_profile(self.output)),
        }
    }

    #[must_use]
    pub const fn workload_kind(&self) -> NativeWorkloadKindV1 {
        self.workload.kind()
    }

    #[must_use]
    pub fn command_count(&self) -> usize {
        self.workload.command_tape().command_count()
    }

    #[must_use]
    pub fn market(&self) -> &Arc<FullMarketData> {
        self.template.market()
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

    /// Build a fresh Rust-owned session from the immutable preparation.
    pub fn fresh_session(&self) -> Result<FullSession, String> {
        self.template.fresh_session()
    }

    pub fn new_runner(&self) -> Result<NativeExecutionRunnerV1, String> {
        NativeExecutionRunnerV1::new(self.template.clone())
    }

    pub fn execute(&self) -> Result<NativeExecutionResultV1, String> {
        let mut runner = self.new_runner()?;
        runner.execute_request(self)
    }
}

/// Native workload authority embedded in [`NativeResultHeaderV2`]. This keeps
/// promotion claims attached to the result instead of inferred from a Python
/// endpoint name after the fact.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeWorkloadAuthorityDescriptorV1 {
    pub workload_kind: NativeWorkloadKindV1,
    pub runtime_class: &'static str,
    pub account_authority: &'static str,
    pub execution_model_id: &'static str,
    pub metric_contract_version: u16,
}

/// Common result provenance for all output retention profiles. It is scalar
/// and allocation-light, so score runs do not construct a Python dictionary,
/// tabular report, or nested lifecycle objects merely to carry metadata.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeResultHeaderV2 {
    pub result_version: u16,
    pub run_id: u64,
    pub request_fingerprint: [u8; 32],
    pub template_fingerprint: [u8; 32],
    pub contract_bundle_hash: u128,
    pub authority: NativeWorkloadAuthorityDescriptorV1,
    pub retention: NativeOutputProfileV1,
    pub detail_truncated: bool,
    pub retained_rows: u64,
    pub dropped_rows: u64,
    pub terminal_fingerprint: [u8; 32],
}

impl NativeResultHeaderV2 {
    fn from_authoritative_run(
        run_id: u64,
        request: &NativeExecutionRequestV1,
        session: &FullSession,
        output: &NativeExecutionOutputV1,
        workload_audit: &NativeWorkloadAuditV1,
    ) -> Self {
        let execution_detail = output.detail_retention();
        let workload_detail = workload_audit.detail_retention();
        // The canonical fill/event trace and the optional dynamic-workload
        // admission trace each have an explicit bounded sink. Report their
        // aggregate here so a caller can see total retained diagnostic rows
        // without mistaking either artifact for an unbounded side ledger.
        let retained_rows = execution_detail
            .retained_rows
            .saturating_add(workload_detail.retained_rows);
        let dropped_rows = execution_detail
            .dropped_rows
            .saturating_add(workload_detail.dropped_rows);
        let workload_kind = request.workload.kind();
        Self {
            result_version: NATIVE_RESULT_VERSION_V2,
            run_id,
            request_fingerprint: request.fingerprint,
            template_fingerprint: request.template.fingerprint,
            contract_bundle_hash: contract_bundle_hash_v2(
                &request.template,
                session,
                workload_kind,
            ),
            authority: NativeWorkloadAuthorityDescriptorV1 {
                workload_kind,
                runtime_class: "whole_run_native",
                account_authority: "linear_account_v1",
                execution_model_id: session.execution_model.id(),
                metric_contract_version: output.score().metrics_v2.metric_contract_version,
            },
            retention: request.output,
            detail_truncated: execution_detail.truncated() || workload_detail.truncated(),
            retained_rows: u64::try_from(retained_rows).unwrap_or(u64::MAX),
            dropped_rows: u64::try_from(dropped_rows).unwrap_or(u64::MAX),
            terminal_fingerprint: terminal_fingerprint_v2(output),
        }
    }

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

/// Borrowed NativeResult V2 envelope over the existing flat result payload.
/// It deliberately avoids cloning potentially large compact/audit arrays just
/// to present a versioned common result view.
#[derive(Clone, Copy, Debug)]
pub struct NativeResultV2<'a> {
    pub header: &'a NativeResultHeaderV2,
    pub output: &'a NativeExecutionOutputV1,
}

/// Native result plus immutable request provenance. Python report adaptation
/// remains a cold-path concern and must consume this authoritative output.
pub struct NativeExecutionResultV1 {
    pub request_version: u16,
    pub protocol_version: u16,
    pub request_fingerprint: [u8; 32],
    pub template_fingerprint: [u8; 32],
    pub workload_kind: NativeWorkloadKindV1,
    pub output_profile: NativeOutputProfileV1,
    pub command_count: usize,
    pub bar_count: usize,
    pub execution_generation: u64,
    pub runner_run_count: u64,
    /// Versioned common result envelope over the profile-specific SoA payload.
    pub header_v2: NativeResultHeaderV2,
    pub output: NativeExecutionOutputV1,
    pub workload_audit: NativeWorkloadAuditV1,
}

impl NativeExecutionResultV1 {
    #[must_use]
    pub const fn native_result_v2(&self) -> NativeResultV2<'_> {
        NativeResultV2 {
            header: &self.header_v2,
            output: &self.output,
        }
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_fingerprint(self.request_fingerprint)
    }

    #[must_use]
    pub fn template_fingerprint_hex(&self) -> String {
        hex_fingerprint(self.template_fingerprint)
    }

    #[must_use]
    pub const fn score(&self) -> &NativeScoreOutputV1 {
        self.output.score()
    }

    /// Explicit compatibility adapter for callers still pinned to the
    /// API-0.4 `StaticTapeOutput` shape. It moves flat buffers and never
    /// replays the authoritative native execution.
    #[must_use]
    pub fn into_legacy_static(self) -> StaticTapeOutput {
        self.output.into_legacy_static()
    }
}

fn contract_bundle_hash_v2(
    template: &NativeExecutionTemplateV1,
    session: &FullSession,
    workload_kind: NativeWorkloadKindV1,
) -> u128 {
    let mut hash = FingerprintWriter::new();
    hash.bytes(b"native-contract-bundle-v2");
    hash.u16(NATIVE_RESULT_VERSION_V2);
    hash.bytes(&template.fingerprint);
    hash.u8(workload_kind as u8);
    hash.i64(template.contract.event_contract_code);
    hash.f64(template.account.initial_capital);
    hash.f64(template.account.maintenance_ratio);
    hash.bool(template.account.use_funding);
    fingerprint_execution_model_v1(&mut hash, session.execution_model);
    fingerprint_metric_contract_v2(&mut hash, session.metric_contract);
    let bytes = hash.finish();
    let mut lower = [0_u8; 16];
    lower.copy_from_slice(&bytes[..16]);
    u128::from_le_bytes(lower)
}

fn fingerprint_execution_model_v1(hash: &mut FingerprintWriter, model: ExecutionModelPlanV1) {
    hash.bytes(model.id().as_bytes());
    match model {
        ExecutionModelPlanV1::BarTouch {
            proportional_slippage,
        } => {
            hash.u8(0);
            hash.f64(proportional_slippage);
        }
        ExecutionModelPlanV1::Cost(cost) => {
            hash.u8(1);
            hash.f64(cost.proportional_slippage);
            hash.f64(cost.spread_bps);
            hash.f64(cost.fixed_slippage);
            hash.f64(cost.impact_coefficient);
            match cost.participation_rate {
                Some(value) => {
                    hash.bool(true);
                    hash.f64(value);
                }
                None => hash.bool(false),
            }
        }
    }
}

fn fingerprint_metric_contract_v2(hash: &mut FingerprintWriter, contract: MetricContractV2) {
    hash.bytes(b"metric-contract-v2");
    hash.u8(contract.return_frequency as u8);
    hash.f64(contract.annualization_factor);
    hash.f64(contract.risk_free_rate);
    hash.u8(contract.variance_ddof);
    hash.u8(contract.zero_variance_policy as u8);
    hash.u8(contract.short_run_policy as u8);
    hash.u8(contract.trade_count_definition as u8);
}

pub(crate) fn terminal_fingerprint_v2(output: &NativeExecutionOutputV1) -> [u8; 32] {
    let score = output.score();
    let metrics = *score.metrics_v2;
    let mut hash = FingerprintWriter::new();
    hash.bytes(b"native-terminal-accounting-v2");
    hash.u16(NATIVE_RESULT_VERSION_V2);
    hash.f64(score.final_equity);
    hash.usize(score.final_positions.len());
    for position in score.final_positions.iter().copied() {
        hash.f64(position);
    }
    hash.f64(score.total_fee);
    hash.f64(score.total_turnover);
    hash.f64(score.total_funding);
    hash.i64(score.fill_count);
    hash.i64(score.event_count);
    hash.i64(score.rejected_count);
    hash.i64(score.canceled_count);
    hash.f64(score.max_initial_margin);
    hash.f64(score.max_maintenance_margin);
    hash.bool(score.liquidated);
    hash.i64(score.liquidation_bar);
    hash.i64(score.liquidation_reason);
    fingerprint_metric_contract_v2(&mut hash, score.metric_contract);
    fingerprint_metric_snapshot_v2(&mut hash, metrics);
    hash.finish()
}

fn fingerprint_metric_snapshot_v2(hash: &mut FingerprintWriter, metrics: NativeMetricSnapshotV2) {
    hash.u16(metrics.metric_contract_version);
    hash.f64(metrics.final_equity);
    hash.f64(metrics.total_return);
    hash.f64(metrics.cagr);
    hash.f64(metrics.mean_return);
    hash.f64(metrics.variance);
    hash.f64(metrics.sharpe);
    hash.f64(metrics.sortino);
    hash.f64(metrics.max_drawdown);
    hash.f64(metrics.calmar);
    hash.f64(metrics.omega);
    hash.f64(metrics.profit_factor);
    hash.f64(metrics.average_gross_exposure);
    hash.f64(metrics.turnover);
    hash.f64(metrics.total_fee);
    hash.f64(metrics.total_funding);
    hash.u64(metrics.fill_count);
    hash.u64(metrics.event_count);
    hash.u64(metrics.rejected_count);
    hash.u64(metrics.canceled_count);
    hash.u64(metrics.sample_count);
    hash.bool(metrics.liquidated);
}

fn validate_workload(
    template: &NativeExecutionTemplateV1,
    workload: &WorkloadPayloadV1,
) -> Result<(), String> {
    let tape = workload.command_tape();
    if tape.bars() != template.bar_count() {
        return Err(
            "native execution workload tape does not match prepared market bars".to_owned(),
        );
    }
    match workload {
        WorkloadPayloadV1::StrategyIr(strategy) => {
            if strategy.signal.len() != template.bar_count() {
                return Err(
                    "native strategy IR signal does not match prepared market bars".to_owned(),
                );
            }
            if strategy.program.symbol().0 as usize >= template.n_symbols() {
                return Err("native strategy IR symbol is outside prepared market".to_owned());
            }
        }
        WorkloadPayloadV1::PortfolioTarget(portfolio) => {
            if portfolio.targets.n_bars() != template.bar_count()
                || portfolio.targets.n_symbols() != template.n_symbols()
            {
                return Err(
                    "portfolio target tape does not match prepared market layout".to_owned(),
                );
            }
        }
        WorkloadPayloadV1::PortfolioTargetMarket(portfolio) => {
            if portfolio.targets.n_bars() != template.bar_count()
                || portfolio.targets.n_symbols() != template.n_symbols()
                || portfolio.tradable.len() != template.bar_count() * template.n_symbols()
                || portfolio.stale.len() != template.bar_count() * template.n_symbols()
            {
                return Err(
                    "portfolio target market workload does not match prepared market layout"
                        .to_owned(),
                );
            }
        }
        WorkloadPayloadV1::PackageAtomicMarket(package) => {
            if package.command_bar == 0
                || package.command_bar >= template.bar_count()
                || package.plan.policy != PackagePolicy::AtomicBarSimulation
            {
                return Err(
                    "native atomic package workload is outside the prepared market clock"
                        .to_owned(),
                );
            }
        }
        WorkloadPayloadV1::PackageMarketV2(package) => {
            if package.package_count() == 0
                || package.intents.iter().any(|intent| {
                    intent.command_bar == 0
                        || intent.command_bar + 1 >= template.bar_count()
                        || intent.legs.is_empty()
                })
            {
                return Err(
                    "native package V2 workload is outside the prepared market clock".to_owned(),
                );
            }
        }
        WorkloadPayloadV1::CommandTape(_) | WorkloadPayloadV1::Package(_) => {}
    }
    validate_command_tape(tape, template.n_symbols())
}

fn validate_command_tape(tape: &CommandTapeV5, n_symbols: usize) -> Result<(), String> {
    for bar in 0..tape.bars() {
        let command_offset = tape.offsets()[bar] as usize;
        for (local_index, command) in tape.commands_at(bar).iter().enumerate() {
            let command_index = command_offset + local_index;
            if let Some(symbol) = command.symbol
                && symbol.0 as usize >= n_symbols
            {
                return Err(format!(
                    "native execution command {command_index} symbol is outside prepared market"
                ));
            }
            if matches!(
                command.action,
                CommandAction::Place | CommandAction::Replace
            ) {
                let order_type = command.order_type.ok_or_else(|| {
                    format!("native execution command {command_index} has no order type")
                })?;
                if command.symbol.is_none() || command.side.is_none() || command.tif.is_none() {
                    return Err(format!(
                        "native execution command {command_index} has incomplete order fields"
                    ));
                }
                if !command.qty.is_finite() || command.qty <= 0.0 {
                    return Err(format!(
                        "native execution command {command_index} quantity is invalid"
                    ));
                }
                if !command.limit_price.is_finite() || !command.stop_price.is_finite() {
                    return Err(format!(
                        "native execution command {command_index} price is invalid"
                    ));
                }
                match order_type {
                    OrderType::Market => {}
                    OrderType::Limit if command.limit_price > 0.0 => {}
                    OrderType::StopMarket if command.stop_price > 0.0 => {}
                    OrderType::StopLimit
                        if command.limit_price > 0.0 && command.stop_price > 0.0 => {}
                    _ => {
                        return Err(format!(
                            "native execution command {command_index} order price or trigger is invalid"
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}

fn fingerprint_template(
    market: &FullMarketData,
    market_start: usize,
    market_end: usize,
    instruments: &InstrumentTableV1,
    account: AccountModelV1,
    contract: ExecutionContractV1,
) -> [u8; 32] {
    let mut hash = FingerprintWriter::new();
    hash.bytes(b"native-execution-template-v1");
    hash.u16(NATIVE_EXECUTION_PROTOCOL_VERSION_V1);
    hash.i64(CORE_PROTOCOL_MIN);
    hash.i64(CORE_PROTOCOL_MAX);
    hash.bytes(CONTRACT_REGISTRY_FINGERPRINT.as_bytes());
    hash.bytes(COMMAND_ABI_VERSION.as_bytes());
    hash.bytes(RESULT_ABI_VERSION.as_bytes());
    fingerprint_market_window(&mut hash, market, market_start, market_end);
    fingerprint_instruments(&mut hash, instruments);
    hash.f64(account.initial_capital);
    hash.f64(account.maintenance_ratio);
    hash.f64(account.slippage_rate);
    hash.bool(account.use_funding);
    hash.i64(contract.event_contract_code);
    hash.finish()
}

fn fingerprint_request(
    template: &NativeExecutionTemplateV1,
    output: NativeOutputProfileV1,
    audit_detail_row_limit: Option<usize>,
    workload: &WorkloadPayloadV1,
) -> [u8; 32] {
    let mut hash = FingerprintWriter::new();
    hash.bytes(NATIVE_EXECUTION_REQUEST_SCHEMA_V1.as_bytes());
    hash.u16(NATIVE_EXECUTION_REQUEST_VERSION_V1);
    hash.u16(NATIVE_EXECUTION_PROTOCOL_VERSION_V1);
    hash.bytes(&template.fingerprint());
    hash.u8(output as u8);
    match audit_detail_row_limit {
        Some(limit) => {
            hash.bool(true);
            hash.usize(limit);
        }
        None => hash.bool(false),
    }
    fingerprint_workload(&mut hash, workload);
    hash.finish()
}

fn fingerprint_market_window(
    hash: &mut FingerprintWriter,
    market: &FullMarketData,
    market_start: usize,
    market_end: usize,
) {
    hash.bytes(b"market-window-v1");
    hash.usize(market_start);
    hash.usize(market_end);
    hash.usize(market_end - market_start);
    hash.usize(market.n_symbols);
    for timestamp in market.timestamps_ns[market_start..market_end]
        .iter()
        .copied()
    {
        hash.i64(timestamp);
    }
    let width_start = market_start * market.n_symbols;
    let width_end = market_end * market.n_symbols;
    for field in [
        &market.opens[width_start..width_end],
        &market.highs[width_start..width_end],
        &market.lows[width_start..width_end],
        &market.closes[width_start..width_end],
        &market.volumes[width_start..width_end],
        &market.funding[width_start..width_end],
    ] {
        hash.usize(field.len());
        for value in field.iter().copied() {
            hash.f64(value);
        }
    }
    hash.usize(market_end - market_start);
    for value in market.funding_mask[market_start..market_end]
        .iter()
        .copied()
    {
        hash.bool(value);
    }
}

fn fingerprint_instruments(hash: &mut FingerprintWriter, instruments: &InstrumentTableV1) {
    hash.bytes(b"instruments-v1");
    hash.usize(instruments.len());
    for index in 0..instruments.len() {
        hash.u32(instruments.symbol_ids[index].0);
        hash.f64(instruments.contract_sizes[index]);
        hash.f64(instruments.leverages[index]);
        hash.f64(instruments.fee_rates[index]);
    }
}

fn fingerprint_workload(hash: &mut FingerprintWriter, workload: &WorkloadPayloadV1) {
    hash.bytes(b"workload-v1");
    hash.u8(workload.kind() as u8);
    match workload {
        WorkloadPayloadV1::CommandTape(tape) => fingerprint_command_tape(hash, tape),
        WorkloadPayloadV1::StrategyIr(strategy) => {
            hash.u16(strategy.program.version());
            hash.u8(strategy.program.kind() as u8);
            hash.u32(strategy.program.symbol().0);
            hash.bytes(&strategy.program.fingerprint());
            hash.usize(strategy.signal.len());
            for value in strategy.signal.iter().copied() {
                hash.f64(value);
            }
            match strategy.parameters.as_deref() {
                Some(values) => {
                    hash.bool(true);
                    hash.usize(values.len());
                    for value in values.iter().copied() {
                        hash.f64(value);
                    }
                }
                None => hash.bool(false),
            }
            fingerprint_command_tape(hash, strategy.command_tape());
        }
        WorkloadPayloadV1::PortfolioTarget(portfolio) => {
            hash.u8(portfolio.policy as u8);
            hash.usize(portfolio.targets.n_bars());
            hash.usize(portfolio.targets.n_symbols());
            for bar in 0..portfolio.targets.n_bars() {
                for target in portfolio.targets.targets_at(bar).iter().copied() {
                    hash.f64(target);
                }
            }
            fingerprint_command_tape(hash, portfolio.command_tape());
        }
        WorkloadPayloadV1::Package(package) => {
            hash.u64(package.plan.id.0);
            hash.u8(package.plan.policy as u8);
            hash.usize(package.plan.legs.len());
            for leg in package.plan.legs.iter() {
                hash.i64(leg.order_id.0);
            }
            hash.u64(package.preflight.package_id.0);
            hash.u8(package.preflight.policy as u8);
            hash.u8(package_state_code(package.preflight.final_state));
            hash.usize(package.preflight.accepted.len());
            for accepted in package.preflight.accepted.iter().copied() {
                hash.bool(accepted);
            }
            for reason in package.preflight.rejection_reasons.iter().copied() {
                hash.u8(reason as u8);
            }
            for event in package.preflight.transitions.iter().copied() {
                hash.u8(package_event_code(event));
            }
            hash.f64(package.preflight.reserved_margin);
            hash.f64(package.preflight.released_margin);
            hash.f64(package.preflight.package_fee);
            hash.f64(package.preflight.residual_notional);
            fingerprint_command_tape(hash, package.command_tape());
        }
        WorkloadPayloadV1::PortfolioTargetMarket(portfolio) => {
            hash.bytes(b"portfolio-target-market-v1");
            hash.i64(portfolio.external_id_start);
            hash.usize(portfolio.targets.n_bars());
            hash.usize(portfolio.targets.n_symbols());
            for bar in 0..portfolio.targets.n_bars() {
                for target in portfolio.targets.targets_at(bar).iter().copied() {
                    hash.f64(target);
                }
                for value in portfolio.tradable_at(bar).iter().copied() {
                    hash.bool(value);
                }
                for value in portfolio.stale_at(bar).iter().copied() {
                    hash.bool(value);
                }
            }
            for value in portfolio.min_qty.iter().copied() {
                hash.f64(value);
            }
            for value in portfolio.min_notional.iter().copied() {
                hash.f64(value);
            }
        }
        WorkloadPayloadV1::PackageAtomicMarket(package) => {
            hash.bytes(b"package-atomic-market-v1");
            hash.u64(package.plan.id.0);
            hash.u8(package.plan.policy as u8);
            hash.usize(package.command_bar);
            hash.i64(package.max_staleness_ns);
            hash.usize(package.legs.len());
            for leg in package.legs.iter() {
                hash.i64(leg.order_id.0);
                hash.u32(leg.symbol.0);
                hash.f64(leg.signed_qty);
                hash.i64(leg.source_age_ns);
                hash.u16(leg.venue_code);
                hash.u32(leg.venue_sequence);
                hash.f64(leg.min_qty);
                hash.f64(leg.min_notional);
            }
        }
        WorkloadPayloadV1::PackageMarketV2(package) => {
            hash.bytes(b"package-market-v2");
            hash.usize(package.intents.len());
            for intent in package.intents.iter() {
                hash.u64(intent.package_id.0);
                hash.usize(intent.command_bar);
                hash.u8(intent.execution_policy as u8);
                hash.u8(intent.residual_policy as u8);
                hash.i64(intent.max_staleness_ns);
                hash.usize(intent.legs.len());
                for leg in intent.legs.iter() {
                    hash.i64(leg.order_id.0);
                    hash.u32(leg.symbol.0);
                    hash.f64(leg.signed_qty);
                    hash.u8(leg.quantity_source as u8);
                    hash.i64(leg.source_leg);
                    hash.f64(leg.quantity_ratio);
                    hash.f64(leg.fill_fraction);
                    hash.f64(leg.qty_step);
                    hash.f64(leg.min_qty);
                    hash.f64(leg.min_notional);
                    hash.i64(leg.source_age_ns);
                    hash.u16(leg.venue_code);
                    hash.u32(leg.venue_sequence);
                }
            }
        }
    }
}

fn fingerprint_command_tape(hash: &mut FingerprintWriter, tape: &CommandTapeV5) {
    hash.bytes(b"command-tape-v5");
    hash.usize(tape.bars());
    hash.usize(tape.command_count());
    for offset in tape.offsets().iter().copied() {
        hash.u32(offset);
    }
    for bar in 0..tape.bars() {
        for command in tape.commands_at(bar) {
            hash.u8(command.action as u8);
            hash.i64(command.symbol.map_or(-1, |symbol| i64::from(symbol.0)));
            hash.i64(command.side.map_or(0, |side| side as i8 as i64));
            hash.i64(command.order_type.map_or(-1, |kind| kind as u8 as i64));
            hash.i64(command.tif.map_or(-1, |tif| tif as u8 as i64));
            hash.bool(command.reduce_only);
            hash.i64(command.external_id.0);
            hash.i64(command.target_id.0);
            hash.i64(command.parent_id.0);
            hash.i64(command.group_id);
            hash.i64(command.oco_id);
            hash.i64(
                command
                    .activation
                    .map_or(-1, |activation| activation as u8 as i64),
            );
            hash.u32(command.command_index);
            hash.f64(command.qty);
            hash.f64(command.limit_price);
            hash.f64(command.stop_price);
            hash.i64(command.expire_bar.map_or(-1, i64::from));
        }
    }
}

fn package_state_code(state: PackageState) -> u8 {
    state as u8
}

fn package_event_code(event: PackageEventKind) -> u8 {
    match event {
        PackageEventKind::Plan => 0,
        PackageEventKind::PreflightAccepted => 1,
        PackageEventKind::PreflightRejected => 2,
        PackageEventKind::Reserve => 3,
        PackageEventKind::Commit => 4,
        PackageEventKind::Filled => 5,
        PackageEventKind::Partial => 6,
        PackageEventKind::Compensating => 7,
        PackageEventKind::Abort => 8,
        PackageEventKind::Release => 9,
    }
}

pub(crate) struct FingerprintWriter {
    lanes: [u64; 4],
}

impl FingerprintWriter {
    pub(crate) const fn new() -> Self {
        Self {
            lanes: [
                0xcbf2_9ce4_8422_2325_u64,
                0x8422_2325_cbf2_9ce4_u64,
                0x9e37_79b9_7f4a_7c15_u64,
                0x517c_c1b7_2722_0a95_u64,
            ],
        }
    }

    pub(crate) fn bytes(&mut self, bytes: &[u8]) {
        self.raw_bytes(&u64::try_from(bytes.len()).unwrap_or(u64::MAX).to_le_bytes());
        self.raw_bytes(bytes);
    }

    fn raw_bytes(&mut self, bytes: &[u8]) {
        for (lane_index, lane) in self.lanes.iter_mut().enumerate() {
            for byte in bytes {
                *lane ^= u64::from(*byte).wrapping_add((lane_index as u64) << 1);
                *lane = lane.wrapping_mul(0x0000_0100_0000_01b3);
            }
        }
    }

    pub(crate) fn bool(&mut self, value: bool) {
        self.u8(u8::from(value));
    }

    pub(crate) fn u8(&mut self, value: u8) {
        self.raw_bytes(&[value]);
    }

    pub(crate) fn u16(&mut self, value: u16) {
        self.raw_bytes(&value.to_le_bytes());
    }

    pub(crate) fn u32(&mut self, value: u32) {
        self.raw_bytes(&value.to_le_bytes());
    }

    pub(crate) fn u64(&mut self, value: u64) {
        self.raw_bytes(&value.to_le_bytes());
    }

    pub(crate) fn i64(&mut self, value: i64) {
        self.raw_bytes(&value.to_le_bytes());
    }

    pub(crate) fn usize(&mut self, value: usize) {
        self.u64(u64::try_from(value).unwrap_or(u64::MAX));
    }

    pub(crate) fn f64(&mut self, value: f64) {
        self.u64(value.to_bits());
    }

    pub(crate) fn finish(self) -> [u8; 32] {
        let mut fingerprint = [0_u8; 32];
        for (index, lane) in self.lanes.into_iter().enumerate() {
            fingerprint[index * 8..(index + 1) * 8].copy_from_slice(&lane.to_le_bytes());
        }
        fingerprint
    }
}

pub(crate) fn hex_fingerprint(fingerprint: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in fingerprint {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantbt_domain::enums::{ActivationPolicy, CommandAction, OrderType, Side, TimeInForce};
    use quantbt_domain::ids::{CurrencyId, ExternalOrderId, VenueId};
    use quantbt_domain::{InstrumentRegistryV2, InstrumentSpecV2};
    use quantbt_package::{
        PackageId, PackageLegRef, PackageLegRequest, PackagePolicy, compile_package_tape,
        execute_package_transaction,
    };
    use quantbt_portfolio::{
        PortfolioTargetRequest, compile_target_delta_tape, execute_portfolio_target,
    };
    use quantbt_strategy_ir::{
        ProgramLimits, STRATEGY_IR_VERSION, StrategyKind, StrategyParameters,
    };

    fn market() -> Arc<FullMarketData> {
        Arc::new(
            FullMarketData::new(
                vec![0, 1, 2, 3],
                vec![100.0, 100.0, 101.0, 102.0],
                vec![101.0, 101.0, 102.0, 103.0],
                vec![99.0, 99.0, 100.0, 101.0],
                vec![100.0, 100.0, 101.0, 102.0],
                vec![10.0, 11.0, 12.0, 13.0],
                vec![0.0, 0.0, 0.0001, 0.0],
                vec![false, false, true, false],
                1,
            )
            .unwrap(),
        )
    }

    fn instruments() -> InstrumentTableV1 {
        InstrumentTableV1::sequential(vec![1.0], vec![5.0], vec![0.0002]).unwrap()
    }

    #[test]
    fn v1_execution_table_lowers_only_from_the_canonical_v2_registry() {
        let registry = InstrumentRegistryV2::new(vec![InstrumentSpecV2 {
            symbol_id: SymbolId(0),
            venue_id: VenueId(1),
            instrument_kind: 1,
            price_tick: 0.1,
            quantity_step: 0.01,
            min_quantity: 0.01,
            max_quantity: None,
            min_notional: 5.0,
            contract_multiplier: 2.0,
            leverage_limit: 4.0,
            settlement_currency: CurrencyId(1),
            fee_schedule_id: 1,
            funding_schedule_id: Some(1),
            one_way_fee_rate: 0.0005,
        }])
        .unwrap();
        let table = InstrumentTableV1::from_registry_v2(&registry).unwrap();
        assert_eq!(table.contract_sizes.as_ref(), &[2.0]);
        assert_eq!(table.leverages.as_ref(), &[4.0]);
        assert_eq!(table.fee_rates.as_ref(), &[0.0005]);
    }

    fn account() -> AccountModelV1 {
        AccountModelV1::new(10_000.0, 0.005, 0.0001, true).unwrap()
    }

    fn contract() -> ExecutionContractV1 {
        ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN).unwrap()
    }

    fn market_tape() -> CommandTapeV5 {
        let mut offsets = vec![0_u32, 0, 1, 2, 2];
        offsets.shrink_to_fit();
        CommandTapeV5::new(
            offsets,
            vec![
                quantbt_domain::OrderCommandV5 {
                    action: CommandAction::Place,
                    symbol: Some(SymbolId(0)),
                    side: Some(Side::Buy),
                    order_type: Some(OrderType::Market),
                    tif: Some(TimeInForce::Gtc),
                    reduce_only: false,
                    external_id: ExternalOrderId(1),
                    target_id: ExternalOrderId(-1),
                    parent_id: ExternalOrderId(-1),
                    group_id: -1,
                    oco_id: -1,
                    activation: Some(ActivationPolicy::Immediate),
                    command_index: 0,
                    qty: 1.0,
                    limit_price: 0.0,
                    stop_price: 0.0,
                    expire_bar: None,
                },
                quantbt_domain::OrderCommandV5 {
                    action: CommandAction::Place,
                    symbol: Some(SymbolId(0)),
                    side: Some(Side::Sell),
                    order_type: Some(OrderType::Market),
                    tif: Some(TimeInForce::Gtc),
                    reduce_only: true,
                    external_id: ExternalOrderId(2),
                    target_id: ExternalOrderId(-1),
                    parent_id: ExternalOrderId(-1),
                    group_id: -1,
                    oco_id: -1,
                    activation: Some(ActivationPolicy::Immediate),
                    command_index: 1,
                    qty: 1.0,
                    limit_price: 0.0,
                    stop_price: 0.0,
                    expire_bar: None,
                },
            ],
        )
        .unwrap()
    }

    fn request(output: NativeOutputProfileV1) -> NativeExecutionRequestV1 {
        NativeExecutionRequestV1::new(
            market(),
            instruments(),
            account(),
            contract(),
            output,
            WorkloadPayloadV1::CommandTape(market_tape()),
        )
        .unwrap()
    }

    fn assert_output_eq(left: &StaticTapeOutput, right: &StaticTapeOutput) {
        assert_eq!(left.final_equity, right.final_equity);
        assert_eq!(left.final_positions, right.final_positions);
        assert_eq!(left.total_fee, right.total_fee);
        assert_eq!(left.total_turnover, right.total_turnover);
        assert_eq!(left.total_funding, right.total_funding);
        assert_eq!(left.fill_count, right.fill_count);
        assert_eq!(left.event_count, right.event_count);
        assert_eq!(left.rejected_count, right.rejected_count);
        assert_eq!(left.canceled_count, right.canceled_count);
        assert_eq!(left.equity, right.equity);
        assert_eq!(left.positions, right.positions);
        assert_eq!(left.fill_price, right.fill_price);
        assert_eq!(left.event_kind, right.event_kind);
    }

    #[test]
    fn direct_command_request_matches_a_fresh_full_session_for_every_output_profile() {
        for profile in [
            NativeOutputProfileV1::Score,
            NativeOutputProfileV1::Compact,
            NativeOutputProfileV1::Audit,
        ] {
            let request = request(profile);
            let expected = {
                let mut session = request.fresh_session().unwrap();
                match profile {
                    NativeOutputProfileV1::Score => session
                        .run_typed_score(request.workload.command_tape())
                        .unwrap(),
                    NativeOutputProfileV1::Compact => session
                        .run_typed_compact(request.workload.command_tape())
                        .unwrap(),
                    NativeOutputProfileV1::Audit => session
                        .run_typed_audit(request.workload.command_tape())
                        .unwrap(),
                }
            };
            let actual = request.execute().unwrap();
            assert_eq!(actual.workload_kind, NativeWorkloadKindV1::CommandTape);
            assert_eq!(actual.output_profile, profile);
            assert_output_eq(&actual.output.clone().into_legacy_static(), &expected);
        }
    }

    #[test]
    fn audit_retention_changes_only_diagnostic_rows_not_terminal_authority() {
        let full_request = request(NativeOutputProfileV1::Audit);
        let capped_request = full_request.clone().with_audit_detail_limit(1).unwrap();
        assert_ne!(full_request.fingerprint(), capped_request.fingerprint());

        let full = full_request.execute().unwrap();
        let capped = capped_request.execute().unwrap();
        assert_eq!(
            full.header_v2.terminal_fingerprint,
            capped.header_v2.terminal_fingerprint
        );
        assert_eq!(full.output.score(), capped.output.score());
        assert!(capped.header_v2.detail_truncated);
        assert_eq!(capped.header_v2.retained_rows, 1);
        assert!(capped.header_v2.dropped_rows > 0);
        assert_eq!(capped.output.detail_retention().retained_rows, 1);
        assert!(capped.output.detail_retention().truncated());
    }

    #[test]
    fn windowed_template_uses_local_tape_clock_and_runner_resets_without_leakage() {
        let source = market();
        let template = Arc::new(
            NativeExecutionTemplateV1::new(source.clone(), instruments(), account(), contract())
                .unwrap(),
        );
        let window = Arc::new(template.window(1, 4).unwrap());
        assert!(Arc::ptr_eq(template.market(), window.market()));
        assert_eq!(window.bar_count(), 3);

        let tape = CommandTapeV5::new(
            vec![0, 1, 1, 1],
            vec![quantbt_domain::OrderCommandV5 {
                action: CommandAction::Place,
                symbol: Some(SymbolId(0)),
                side: Some(Side::Buy),
                order_type: Some(OrderType::Market),
                tif: Some(TimeInForce::Gtc),
                reduce_only: false,
                external_id: ExternalOrderId(41),
                target_id: ExternalOrderId(-1),
                parent_id: ExternalOrderId(-1),
                group_id: -1,
                oco_id: -1,
                activation: Some(ActivationPolicy::Immediate),
                command_index: 0,
                qty: 1.0,
                limit_price: 0.0,
                stop_price: 0.0,
                expire_bar: None,
            }],
        )
        .unwrap();
        let request = NativeExecutionRequestV1::from_template(
            window.clone(),
            NativeOutputProfileV1::Audit,
            WorkloadPayloadV1::CommandTape(tape),
        )
        .unwrap();
        let expected = {
            let mut session = request.fresh_session().unwrap();
            session
                .run_typed_audit(request.workload.command_tape())
                .unwrap()
        };
        let mut runner = request.new_runner().unwrap();
        let first = runner.execute_request(&request).unwrap();
        let second = runner.execute_request(&request).unwrap();
        assert_eq!(first.execution_generation, 1);
        assert_eq!(second.execution_generation, 2);
        assert_eq!(second.runner_run_count, 2);
        assert_output_eq(&first.output.clone().into_legacy_static(), &expected);
        assert_output_eq(&second.output.clone().into_legacy_static(), &expected);

        runner.reset_account_and_orders().unwrap();
        assert_eq!(runner.generation(), 3);
        assert_eq!(runner.explicit_reset_count(), 1);
        let third = runner.execute_request(&request).unwrap();
        assert_eq!(third.execution_generation, 4);
        assert_output_eq(&third.output.into_legacy_static(), &expected);
    }

    #[test]
    fn request_fingerprint_covers_all_result_affecting_inputs() {
        let base = request(NativeOutputProfileV1::Score).fingerprint_hex();
        let changed_output = request(NativeOutputProfileV1::Audit).fingerprint_hex();
        assert_ne!(base, changed_output);

        let mut changed_market = (*market()).clone();
        changed_market.volumes[0] = 999.0;
        let changed_volume = NativeExecutionRequestV1::new(
            Arc::new(changed_market),
            instruments(),
            account(),
            contract(),
            NativeOutputProfileV1::Score,
            WorkloadPayloadV1::CommandTape(market_tape()),
        )
        .unwrap()
        .fingerprint_hex();
        assert_ne!(base, changed_volume);

        let mut changed_market = (*market()).clone();
        changed_market.funding[2] = 0.0002;
        changed_market.funding_mask[2] = false;
        let changed_funding = NativeExecutionRequestV1::new(
            Arc::new(changed_market),
            instruments(),
            account(),
            contract(),
            NativeOutputProfileV1::Score,
            WorkloadPayloadV1::CommandTape(market_tape()),
        )
        .unwrap()
        .fingerprint_hex();
        assert_ne!(base, changed_funding);

        let changed_instruments = NativeExecutionRequestV1::new(
            market(),
            InstrumentTableV1::sequential(vec![2.0], vec![5.0], vec![0.0002]).unwrap(),
            account(),
            contract(),
            NativeOutputProfileV1::Score,
            WorkloadPayloadV1::CommandTape(market_tape()),
        )
        .unwrap()
        .fingerprint_hex();
        assert_ne!(base, changed_instruments);

        let changed_contract = NativeExecutionRequestV1::new(
            market(),
            instruments(),
            account(),
            ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap(),
            NativeOutputProfileV1::Score,
            WorkloadPayloadV1::CommandTape(market_tape()),
        )
        .unwrap()
        .fingerprint_hex();
        assert_ne!(base, changed_contract);
    }

    #[test]
    fn strategy_ir_workload_is_compiled_once_then_runs_the_same_canonical_tape() {
        let market = market();
        let program = StrategyProgram::new(
            STRATEGY_IR_VERSION,
            StrategyKind::GridLevel,
            SymbolId(0),
            StrategyParameters {
                quantity: 0.5,
                threshold: 0.0,
                take_profit_pct: 0.0,
                stop_loss_pct: 0.0,
                dca_period: 1,
                max_levels: 1,
            },
            ProgramLimits::default(),
        )
        .unwrap();
        let request = NativeExecutionRequestV1::from_strategy_ir(
            market,
            instruments(),
            account(),
            contract(),
            NativeOutputProfileV1::Audit,
            program,
            vec![0.0, 1.0, 2.0, 0.0],
            None,
        )
        .unwrap();
        assert_eq!(request.workload_kind(), NativeWorkloadKindV1::StrategyIr);
        assert!(request.command_count() > 0);
        let actual = request.execute().unwrap();
        let mut session = request.fresh_session().unwrap();
        let expected = session
            .run_typed_audit(request.workload.command_tape())
            .unwrap();
        assert_output_eq(&actual.output.clone().into_legacy_static(), &expected);
        let mut runner = request.new_runner().unwrap();
        let first = runner.execute_request(&request).unwrap();
        let second = runner.execute_request(&request).unwrap();
        assert_output_eq(&first.output.clone().into_legacy_static(), &expected);
        assert_output_eq(&second.output.clone().into_legacy_static(), &expected);
    }

    #[test]
    fn strategy_ir_projection_cannot_cross_prepared_market_boundaries() {
        let source = market();
        let template = Arc::new(
            NativeExecutionTemplateV1::new(source.clone(), instruments(), account(), contract())
                .unwrap(),
        );
        let mut changed_market = (*source).clone();
        changed_market.closes[0] += 1.0;
        let changed_template = Arc::new(
            NativeExecutionTemplateV1::new(
                Arc::new(changed_market),
                instruments(),
                account(),
                contract(),
            )
            .unwrap(),
        );
        let program = StrategyProgram::new(
            STRATEGY_IR_VERSION,
            StrategyKind::SignalTarget,
            SymbolId(0),
            StrategyParameters {
                quantity: 1.0,
                threshold: 0.0,
                take_profit_pct: 0.0,
                stop_loss_pct: 0.0,
                dca_period: 1,
                max_levels: 1,
            },
            ProgramLimits::default(),
        )
        .unwrap();
        let projection = template.strategy_ir_close_projection(0).unwrap();
        let error = StrategyIrWorkloadV1::new_with_projection(
            &changed_template,
            program,
            vec![0.0; 4],
            None,
            &projection,
        )
        .unwrap_err();
        assert!(error.contains("another prepared market"));
    }

    #[test]
    fn prepared_portfolio_and_package_workloads_enter_the_same_session_without_position_mutation() {
        let market = market();
        let template = Arc::new(
            NativeExecutionTemplateV1::new(market.clone(), instruments(), account(), contract())
                .unwrap(),
        );
        let target_result = execute_portfolio_target(PortfolioTargetRequest {
            previous_units: &[0.0],
            requested_units: &[1.0],
            prices: &[100.0],
            equity: 10_000.0,
            contract_sizes: &[1.0],
            leverages: &[5.0],
            fee_rates: &[0.0002],
            slippage_rates: &[0.0001],
            tradable: &[true],
            stale: &[false],
            min_qty: &[0.0],
            min_notional: &[0.0],
            reserved_margin: 0.0,
            policy: PortfolioMarginAllocationPolicy::SequentialLegacy,
        })
        .unwrap();
        let portfolio_tape =
            compile_target_delta_tape(market.n_bars, 1, &[SymbolId(0)], &[0.0], &target_result, 10)
                .unwrap();
        let targets =
            PortfolioTargetTape::new(market.n_bars, market.n_symbols, vec![0.0, 1.0, 1.0, 1.0])
                .unwrap();
        let portfolio_request = NativeExecutionRequestV1::from_template(
            template.clone(),
            NativeOutputProfileV1::Audit,
            WorkloadPayloadV1::PortfolioTarget(
                PortfolioTargetWorkloadV1::new(
                    targets,
                    PortfolioMarginAllocationPolicy::SequentialLegacy,
                    portfolio_tape,
                )
                .unwrap(),
            ),
        )
        .unwrap();
        let mut runner = NativeExecutionRunnerV1::new(template.clone()).unwrap();
        let portfolio_output = runner.execute_request(&portfolio_request).unwrap().output;
        assert_eq!(portfolio_output.score().final_positions, vec![1.0]);
        assert_eq!(portfolio_output.score().fill_count, 1);

        let legs = [PackageLegRequest {
            order_id: ExternalOrderId(77),
            symbol: SymbolId(0),
            signed_qty: -1.0,
            price: 100.0,
            initial_margin: 20.0,
            fee_rate: 0.0002,
            source_age_ns: 0,
            venue_code: 1,
            venue_sequence: 0,
            min_qty: 0.0,
            min_notional: 0.0,
            contract_size: 1.0,
        }];
        let package_id = PackageId(99);
        let preflight = execute_package_transaction(
            package_id,
            &legs,
            10_000.0,
            PackagePolicy::AtomicBarSimulation,
            0,
        )
        .unwrap();
        let package_tape =
            compile_package_tape(market.n_bars, 1, package_id, &legs, &preflight).unwrap();
        let package_request = NativeExecutionRequestV1::from_template(
            template,
            NativeOutputProfileV1::Audit,
            WorkloadPayloadV1::Package(
                PackageTapeV1::new(
                    PackagePlan {
                        id: package_id,
                        policy: PackagePolicy::AtomicBarSimulation,
                        legs: vec![PackageLegRef {
                            order_id: ExternalOrderId(77),
                        }]
                        .into_boxed_slice(),
                    },
                    preflight,
                    package_tape,
                )
                .unwrap(),
            ),
        )
        .unwrap();
        // The same mutable FullSession is reused, but each workload starts
        // from a clean account/order/lifecycle state. If reset were omitted,
        // the package short would net against the portfolio long above.
        let package_output = runner.execute_request(&package_request).unwrap().output;
        assert_eq!(package_output.score().final_positions, vec![-1.0]);
        assert_eq!(package_output.score().fill_count, 1);
        let portfolio_replay = runner.execute_request(&portfolio_request).unwrap().output;
        assert_output_eq(
            &portfolio_replay.clone().into_legacy_static(),
            &portfolio_output.clone().into_legacy_static(),
        );
    }

    #[test]
    fn market_target_workload_is_causal_reversal_safe_and_runner_reset_safe() {
        let source = market();
        let template = Arc::new(
            NativeExecutionTemplateV1::new(
                source,
                instruments(),
                account(),
                ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap(),
            )
            .unwrap(),
        );
        let request = NativeExecutionRequestV1::from_template_portfolio_target_market(
            template,
            NativeOutputProfileV1::Audit,
            vec![0.0, 1.0, -1.0, 0.0],
            vec![true; 4],
            vec![false; 4],
            vec![0.0],
            vec![0.0],
            1_000,
        )
        .unwrap();
        let first = request.execute().unwrap();
        assert_eq!(
            first.workload_kind,
            NativeWorkloadKindV1::PortfolioTargetMarket
        );
        assert_eq!(first.command_count, 3);
        assert_eq!(first.output.score().final_positions, vec![0.0]);
        assert_eq!(first.output.score().fill_count, 3);
        assert_ne!(first.output.score().total_funding, 0.0);
        let NativeWorkloadAuditV1::PortfolioTarget(audit) = &first.workload_audit else {
            panic!("portfolio target workload must emit portfolio audit")
        };
        assert_eq!(audit.decision_count, 3);
        assert_eq!(audit.rejected_decision_count, 0);
        assert_eq!(audit.bar, vec![1, 2, 3]);

        let mut runner = request.new_runner().unwrap();
        let second = runner.execute_request(&request).unwrap();
        let third = runner.execute_request(&request).unwrap();
        assert_output_eq(
            &first.output.into_legacy_static(),
            &second.output.clone().into_legacy_static(),
        );
        assert_output_eq(
            &second.output.into_legacy_static(),
            &third.output.into_legacy_static(),
        );
    }

    #[test]
    fn dynamic_workload_audit_respects_the_same_explicit_detail_cap() {
        let template = Arc::new(
            NativeExecutionTemplateV1::new(
                market(),
                instruments(),
                account(),
                ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap(),
            )
            .unwrap(),
        );
        let uncapped = NativeExecutionRequestV1::from_template_portfolio_target_market(
            template,
            NativeOutputProfileV1::Audit,
            vec![0.0, 1.0, -1.0, 0.0],
            vec![true; 4],
            vec![false; 4],
            vec![0.0],
            vec![0.0],
            1_000,
        )
        .unwrap();
        let capped = uncapped.clone().with_audit_detail_limit(1).unwrap();
        let full_result = uncapped.execute().unwrap();
        let capped_result = capped.execute().unwrap();
        assert_eq!(
            full_result.header_v2.terminal_fingerprint,
            capped_result.header_v2.terminal_fingerprint
        );
        let NativeWorkloadAuditV1::PortfolioTarget(audit) = capped_result.workload_audit else {
            panic!("portfolio target workload must emit portfolio audit")
        };
        assert_eq!(audit.detail_retention.retained_rows, 1);
        assert_eq!(audit.detail_retention.dropped_rows, 2);
        assert_eq!(audit.bar.len(), 1);
        assert!(capped_result.header_v2.detail_truncated);
        // Header combines canonical fill/event detail plus dynamic admission
        // provenance, both of which are independently bounded by the request.
        assert!(capped_result.header_v2.retained_rows >= 1);
        assert!(capped_result.header_v2.dropped_rows >= 2);
    }

    #[test]
    fn market_target_rejects_post_cost_margin_without_partial_position_mutation() {
        let template = Arc::new(
            NativeExecutionTemplateV1::new(
                market(),
                InstrumentTableV1::sequential(vec![1.0], vec![1.0], vec![0.001]).unwrap(),
                AccountModelV1::new(10.0, 0.005, 0.001, false).unwrap(),
                ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap(),
            )
            .unwrap(),
        );
        let request = NativeExecutionRequestV1::from_template_portfolio_target_market(
            template,
            NativeOutputProfileV1::Audit,
            vec![0.0, 1.0, 1.0, 1.0],
            vec![true; 4],
            vec![false; 4],
            vec![0.0],
            vec![0.0],
            1,
        )
        .unwrap();
        let result = request.execute().unwrap();
        assert_eq!(result.output.score().final_positions, vec![0.0]);
        assert_eq!(result.output.score().fill_count, 0);
        let NativeWorkloadAuditV1::PortfolioTarget(audit) = result.workload_audit else {
            panic!("portfolio target workload must emit portfolio audit")
        };
        assert!(audit.rejected_decision_count >= 1);
        assert!(audit.rejection_code.iter().any(|code| {
            *code == quantbt_portfolio::PortfolioTargetRejectReason::PostCostMargin as i64
        }));
    }

    #[test]
    fn market_target_stale_row_is_atomic_then_can_retry_on_a_later_tradable_bar() {
        let template = Arc::new(
            NativeExecutionTemplateV1::new(
                market(),
                instruments(),
                account(),
                ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap(),
            )
            .unwrap(),
        );
        let request = NativeExecutionRequestV1::from_template_portfolio_target_market(
            template,
            NativeOutputProfileV1::Audit,
            vec![0.0, 1.0, 1.0, 1.0],
            vec![true; 4],
            vec![false, true, false, false],
            vec![0.0],
            vec![0.0],
            1,
        )
        .unwrap();
        let result = request.execute().unwrap();
        assert_eq!(result.output.score().fill_count, 1);
        let NativeWorkloadAuditV1::PortfolioTarget(audit) = result.workload_audit else {
            panic!("portfolio target workload must emit portfolio audit")
        };
        assert_eq!(audit.bar, vec![1, 2]);
        assert_eq!(
            audit.rejection_code[0],
            quantbt_portfolio::PortfolioTargetRejectReason::StalePrice as i64
        );
        assert_eq!(
            audit.rejection_code[1],
            quantbt_portfolio::PortfolioTargetRejectReason::Accepted as i64
        );
    }

    #[test]
    fn atomic_market_package_has_no_orphan_leg_after_stale_or_margin_rejection() {
        let source = Arc::new(
            FullMarketData::new(
                vec![0, 1, 2],
                vec![100.0, 50.0, 100.0, 50.0, 100.0, 50.0],
                vec![101.0, 51.0, 101.0, 51.0, 101.0, 51.0],
                vec![99.0, 49.0, 99.0, 49.0, 99.0, 49.0],
                vec![100.0, 50.0, 100.0, 50.0, 100.0, 50.0],
                vec![1_000.0; 6],
                vec![0.0; 6],
                vec![false; 3],
                2,
            )
            .unwrap(),
        );
        let template = Arc::new(
            NativeExecutionTemplateV1::new(
                source,
                InstrumentTableV1::sequential(vec![1.0, 1.0], vec![5.0, 5.0], vec![0.0002, 0.0002])
                    .unwrap(),
                account(),
                ExecutionContractV1::new(CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).unwrap(),
            )
            .unwrap(),
        );
        let legs = vec![
            PackageLegRequest {
                order_id: ExternalOrderId(91),
                symbol: SymbolId(0),
                signed_qty: 1.0,
                price: 1.0,
                initial_margin: 0.0,
                fee_rate: 0.0,
                source_age_ns: 0,
                venue_code: 1,
                venue_sequence: 0,
                min_qty: 0.0,
                min_notional: 0.0,
                contract_size: 1.0,
            },
            PackageLegRequest {
                order_id: ExternalOrderId(92),
                symbol: SymbolId(1),
                signed_qty: -1.0,
                price: 1.0,
                initial_margin: 0.0,
                fee_rate: 0.0,
                source_age_ns: 10,
                venue_code: 1,
                venue_sequence: 1,
                min_qty: 0.0,
                min_notional: 0.0,
                contract_size: 1.0,
            },
        ];
        let request = NativeExecutionRequestV1::from_template_package_atomic_market(
            template,
            NativeOutputProfileV1::Audit,
            PackagePlan {
                id: PackageId(91),
                policy: PackagePolicy::AtomicBarSimulation,
                legs: vec![
                    PackageLegRef {
                        order_id: ExternalOrderId(91),
                    },
                    PackageLegRef {
                        order_id: ExternalOrderId(92),
                    },
                ]
                .into_boxed_slice(),
            },
            legs,
            1,
            0,
        )
        .unwrap();
        let result = request.execute().unwrap();
        assert_eq!(result.output.score().fill_count, 0);
        assert_eq!(result.output.score().final_positions, vec![0.0, 0.0]);
        let NativeWorkloadAuditV1::PackageAtomic(audit) = result.workload_audit else {
            panic!("atomic package workload must emit package audit")
        };
        assert_eq!(audit.accepted, vec![false, false]);
        assert_eq!(
            audit.rejection_code[1],
            quantbt_package::PackageRejectReason::StaleMarket as i64
        );
        assert_eq!(audit.reserved_margin, audit.released_margin);
    }

    #[test]
    fn unsupported_contract_and_mismatched_tapes_fail_before_session_creation() {
        assert!(ExecutionContractV1::new(99).is_err());
        let invalid_tape = CommandTapeV5::new(vec![0, 0, 0], Vec::new()).unwrap();
        let request = NativeExecutionRequestV1::new(
            market(),
            instruments(),
            account(),
            contract(),
            NativeOutputProfileV1::Score,
            WorkloadPayloadV1::CommandTape(invalid_tape),
        );
        assert!(request.is_err());
        assert!(
            InstrumentTableV1::new(vec![SymbolId(1)], vec![1.0], vec![5.0], vec![0.0002],).is_err()
        );
    }
}
