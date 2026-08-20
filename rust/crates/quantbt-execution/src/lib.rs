//! Versioned typed execution requests for the shared QuantBT Rust runtime.
//!
//! This crate deliberately sits above `quantbt-engine`: it owns immutable
//! request/provenance data and lowers every supported workload to the same
//! [`CommandTapeV5`] consumed by [`FullSession`].  It owns no mutable account,
//! order, lifecycle, or matching state.  A fresh `FullSession` remains the
//! single authoritative execution owner for every request run.

use std::sync::Arc;

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
    FullMarketData, FullSession, NativeExecutionOutputV1, NativeScoreOutputV1, StaticTapeOutput,
};
use quantbt_package::{PackageEventKind, PackageExecutionResult, PackagePlan, PackageState};
use quantbt_portfolio::{PortfolioMarginAllocationPolicy, PortfolioTargetTape};
use quantbt_strategy_ir::{PARAMETER_WIDTH, StrategyProgram};

/// Stable version for the immutable request layout, independent of the public
/// PyO3 API version.  Additive fields require a new request version.
pub const NATIVE_EXECUTION_REQUEST_VERSION_V1: u16 = 1;
pub const NATIVE_EXECUTION_REQUEST_SCHEMA_V1: &str = "native-execution-request-v1";

/// The current generated product registry intentionally supports one native
/// core protocol.  Keeping this explicit in the request fingerprint prevents
/// cache reuse across a future protocol change.
pub const NATIVE_EXECUTION_PROTOCOL_VERSION_V1: u16 = CORE_PROTOCOL_MIN as u16;

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
}

impl NativeWorkloadKindV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::CommandTape => "command_tape_v5",
            Self::StrategyIr => "strategy_ir_v1",
            Self::PortfolioTarget => "portfolio_target_tape_v1",
            Self::Package => "package_tape_v1",
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

/// Tagged immutable workload family.  None of these variants stores a Python
/// callback or a second mutable execution state.
#[derive(Clone, Debug)]
pub enum WorkloadPayloadV1 {
    CommandTape(CommandTapeV5),
    StrategyIr(StrategyIrWorkloadV1),
    PortfolioTarget(PortfolioTargetWorkloadV1),
    Package(PackageTapeV1),
}

impl WorkloadPayloadV1 {
    #[must_use]
    pub const fn kind(&self) -> NativeWorkloadKindV1 {
        match self {
            Self::CommandTape(_) => NativeWorkloadKindV1::CommandTape,
            Self::StrategyIr(_) => NativeWorkloadKindV1::StrategyIr,
            Self::PortfolioTarget(_) => NativeWorkloadKindV1::PortfolioTarget,
            Self::Package(_) => NativeWorkloadKindV1::Package,
        }
    }

    #[must_use]
    pub fn command_tape(&self) -> &CommandTapeV5 {
        match self {
            Self::CommandTape(tape) => tape,
            Self::StrategyIr(workload) => workload.command_tape(),
            Self::PortfolioTarget(workload) => workload.command_tape(),
            Self::Package(workload) => workload.command_tape(),
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
        let output = self.execute_workload(request.output, &request.workload)?;
        Ok(NativeExecutionResultV1 {
            request_version: request.request_version(),
            protocol_version: request.protocol_version(),
            request_fingerprint: request.fingerprint,
            template_fingerprint: self.template.fingerprint,
            workload_kind: request.workload.kind(),
            output_profile: request.output,
            command_count: request.workload.command_tape().command_count(),
            bar_count: self.template.bar_count(),
            execution_generation: self.generation,
            runner_run_count: self.run_count,
            output,
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
        validate_workload(&self.template, workload)?;
        self.reset_for_execution()?;
        let tape = workload.command_tape();
        let result = match output {
            NativeOutputProfileV1::Score => self
                .session
                .run_typed_score_v1(tape)
                .map(NativeExecutionOutputV1::Score),
            NativeOutputProfileV1::Compact => self
                .session
                .run_typed_compact_v1(tape)
                .map(|output| NativeExecutionOutputV1::Compact(Box::new(output))),
            NativeOutputProfileV1::Audit => self
                .session
                .run_typed_audit_v1(tape)
                .map(|output| NativeExecutionOutputV1::Audit(Box::new(output))),
        };
        if result.is_ok() {
            self.run_count = self
                .run_count
                .checked_add(1)
                .ok_or_else(|| "native execution runner run count overflow".to_owned())?;
        }
        result
    }
}

/// Immutable request passed to one shared Rust execution runner. Construction
/// resolves all workload data before the hot loop; execution cannot create a
/// second Python ledger or mutate the immutable contract.
#[derive(Clone)]
pub struct NativeExecutionRequestV1 {
    template: Arc<NativeExecutionTemplateV1>,
    output: NativeOutputProfileV1,
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
        let fingerprint = fingerprint_request(&template, output, &workload);
        Ok(Self {
            template,
            output,
            workload,
            fingerprint,
        })
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

/// Native result plus immutable request provenance.  Python report adaptation
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
    pub output: NativeExecutionOutputV1,
}

impl NativeExecutionResultV1 {
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
    workload: &WorkloadPayloadV1,
) -> [u8; 32] {
    let mut hash = FingerprintWriter::new();
    hash.bytes(NATIVE_EXECUTION_REQUEST_SCHEMA_V1.as_bytes());
    hash.u16(NATIVE_EXECUTION_REQUEST_VERSION_V1);
    hash.u16(NATIVE_EXECUTION_PROTOCOL_VERSION_V1);
    hash.bytes(&template.fingerprint());
    hash.u8(output as u8);
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

struct FingerprintWriter {
    lanes: [u64; 4],
}

impl FingerprintWriter {
    const fn new() -> Self {
        Self {
            lanes: [
                0xcbf2_9ce4_8422_2325_u64,
                0x8422_2325_cbf2_9ce4_u64,
                0x9e37_79b9_7f4a_7c15_u64,
                0x517c_c1b7_2722_0a95_u64,
            ],
        }
    }

    fn bytes(&mut self, bytes: &[u8]) {
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

    fn bool(&mut self, value: bool) {
        self.u8(u8::from(value));
    }

    fn u8(&mut self, value: u8) {
        self.raw_bytes(&[value]);
    }

    fn u16(&mut self, value: u16) {
        self.raw_bytes(&value.to_le_bytes());
    }

    fn u32(&mut self, value: u32) {
        self.raw_bytes(&value.to_le_bytes());
    }

    fn u64(&mut self, value: u64) {
        self.raw_bytes(&value.to_le_bytes());
    }

    fn i64(&mut self, value: i64) {
        self.raw_bytes(&value.to_le_bytes());
    }

    fn usize(&mut self, value: usize) {
        self.u64(u64::try_from(value).unwrap_or(u64::MAX));
    }

    fn f64(&mut self, value: f64) {
        self.u64(value.to_bits());
    }

    fn finish(self) -> [u8; 32] {
        let mut fingerprint = [0_u8; 32];
        for (index, lane) in self.lanes.into_iter().enumerate() {
            fingerprint[index * 8..(index + 1) * 8].copy_from_slice(&lane.to_le_bytes());
        }
        fingerprint
    }
}

fn hex_fingerprint(fingerprint: [u8; 32]) -> String {
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
    use quantbt_domain::ids::ExternalOrderId;
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
