//! Deterministic native scenario batching over one immutable market tape.
//!
//! This crate deliberately batches only bounded [`quantbt_strategy_ir`]
//! programs. Arbitrary Python callbacks remain outside the worker pool. Every
//! scenario creates no market copy, runs the same [`quantbt_engine::FullSession`]
//! lifecycle, and writes a scalar row in stable input order.

use std::collections::VecDeque;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use quantbt_domain::ids::SymbolId;
use quantbt_engine::{FullMarketData, FullSession};
use quantbt_execution::{
    NativeExecutionRequestV1, NativeExecutionRunnerV1, NativeExecutionTemplateV1,
    NativeOutputProfileV1, WorkloadPayloadV1,
};
use quantbt_strategy_ir::{PARAMETER_WIDTH, StrategyProgram};

pub mod target_wfo;

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

/// Stable non-exception status for an independent parameter row.
#[repr(u16)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScenarioStatus {
    Complete = 0,
    InvalidInput = 1,
    ExecutionError = 2,
}

impl ScenarioStatus {
    #[must_use]
    pub const fn code(self) -> u16 {
        self as u16
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ScenarioOutcome {
    pub score: ScenarioScore,
    pub status: ScenarioStatus,
    pub error: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScenarioFailurePolicy {
    /// Validate all rows first and fail the complete batch deterministically if
    /// any row cannot compile or execute.
    FailFast,
    /// Keep valid rows and return structured status/error information for the
    /// invalid ones. Internal engine invariants still remain Rust errors.
    CollectPerScenarioErrors,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BatchPlan {
    pub workers: usize,
    pub chunk_size: usize,
    pub failure_policy: ScenarioFailurePolicy,
}

impl Default for BatchPlan {
    fn default() -> Self {
        Self {
            workers: 1,
            chunk_size: 256,
            failure_policy: ScenarioFailurePolicy::CollectPerScenarioErrors,
        }
    }
}

impl BatchPlan {
    pub fn validate(self) -> Result<Self, String> {
        if self.workers == 0 || self.chunk_size == 0 {
            return Err("batch workers and chunk_size must be > 0".to_owned());
        }
        Ok(self)
    }
}

/// One causal walk-forward execution window. Strategy/indicator warm-up stays
/// in the caller's precomputed signal tape; the native runner resets account
/// state and executes only ``test_start..test_end``.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FoldPlan {
    pub fold_id: u32,
    pub warmup_start: u32,
    pub train_start: u32,
    pub train_end: u32,
    pub test_start: u32,
    pub test_end: u32,
}

impl FoldPlan {
    pub fn validate(self, n_bars: usize) -> Result<Self, String> {
        let warmup_start = self.warmup_start as usize;
        let train_start = self.train_start as usize;
        let train_end = self.train_end as usize;
        let test_start = self.test_start as usize;
        let test_end = self.test_end as usize;
        if warmup_start > train_start
            || train_start >= train_end
            || train_end > test_start
            || test_start >= test_end
            || test_end > n_bars
        {
            return Err("fold plan is not causal or exceeds the prepared market tape".to_owned());
        }
        Ok(self)
    }

    #[must_use]
    pub fn test_range(self) -> std::ops::Range<usize> {
        self.test_start as usize..self.test_end as usize
    }
}

/// Explicit shared-market identity used to prove that scenarios only share a
/// validated immutable prepared tape, never mutable session state.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct SharedMarketKey {
    pub symbol: SymbolId,
    pub market_fingerprint: u64,
}

/// One borrowed row of precomputed signals and its four-column parameter row.
#[derive(Clone, Copy)]
pub struct ScenarioInput<'a> {
    pub scenario: ScenarioId,
    pub signal: &'a [f64],
    pub parameters: Option<&'a [f64]>,
}

/// Immutable material shared by all sessions in one batch. The market and
/// close projection are allocated once at preparation time, not once per
/// scenario or worker.
#[derive(Clone)]
pub struct BatchTemplate {
    execution_template: Arc<NativeExecutionTemplateV1>,
    pub strategy_program: Arc<StrategyProgram>,
    /// One immutable, symbol-local close projection for the complete parent
    /// tape. Fold views retain an offset/length into this allocation instead
    /// of copying closes for every fold or candidate.
    close_projection: Arc<[f64]>,
    close_offset: usize,
    close_len: usize,
    market_key: SharedMarketKey,
}

impl BatchTemplate {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        market: Arc<FullMarketData>,
        strategy_program: Arc<StrategyProgram>,
        contract_sizes: Arc<[f64]>,
        leverages: Arc<[f64]>,
        fee_rates: Arc<[f64]>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage: f64,
        use_funding: bool,
        event_contract_code: i64,
    ) -> Result<Self, String> {
        let instruments = quantbt_execution::InstrumentTableV1::sequential(
            contract_sizes.to_vec(),
            leverages.to_vec(),
            fee_rates.to_vec(),
        )?;
        let account = quantbt_execution::AccountModelV1::new(
            initial_capital,
            maintenance_ratio,
            slippage,
            use_funding,
        )?;
        let contract = quantbt_execution::ExecutionContractV1::new(event_contract_code)?;
        Self::from_execution_template(
            Arc::new(NativeExecutionTemplateV1::new(
                market,
                instruments,
                account,
                contract,
            )?),
            strategy_program,
        )
    }

    pub fn from_execution_template(
        execution_template: Arc<NativeExecutionTemplateV1>,
        strategy_program: Arc<StrategyProgram>,
    ) -> Result<Self, String> {
        let symbol = strategy_program.symbol();
        if symbol.0 as usize >= execution_template.n_symbols() {
            return Err("strategy program symbol is outside prepared market".to_owned());
        }
        let close_projection = execution_template
            .strategy_ir_close_projection(symbol.0 as usize)?
            .values_arc();
        let fingerprint = execution_template.fingerprint();
        let market_fingerprint = u64::from_le_bytes(
            fingerprint[..8]
                .try_into()
                .expect("native execution fingerprint prefix has fixed width"),
        );
        let close_len = close_projection.len();
        Ok(Self {
            market_key: SharedMarketKey {
                symbol,
                market_fingerprint,
            },
            execution_template,
            strategy_program,
            close_projection,
            close_offset: 0,
            close_len,
        })
    }

    fn from_fold_view(
        execution_template: Arc<NativeExecutionTemplateV1>,
        strategy_program: Arc<StrategyProgram>,
        close_projection: Arc<[f64]>,
        close_offset: usize,
        close_len: usize,
    ) -> Result<Self, String> {
        let symbol = strategy_program.symbol();
        if symbol.0 as usize >= execution_template.n_symbols() {
            return Err("strategy program symbol is outside prepared market".to_owned());
        }
        let end = close_offset
            .checked_add(close_len)
            .ok_or_else(|| "native batch close projection range overflow".to_owned())?;
        if end > close_projection.len() || close_len != execution_template.bar_count() {
            return Err("native batch fold close projection does not match market view".to_owned());
        }
        let fingerprint = execution_template.fingerprint();
        let market_fingerprint = u64::from_le_bytes(
            fingerprint[..8]
                .try_into()
                .expect("native execution fingerprint prefix has fixed width"),
        );
        Ok(Self {
            market_key: SharedMarketKey {
                symbol,
                market_fingerprint,
            },
            execution_template,
            strategy_program,
            close_projection,
            close_offset,
            close_len,
        })
    }

    pub fn from_session(
        session: &FullSession,
        strategy_program: Arc<StrategyProgram>,
    ) -> Result<Self, String> {
        Self::from_execution_template(
            Arc::new(NativeExecutionTemplateV1::from_session(session)?),
            strategy_program,
        )
    }

    /// Build an isolated OOS view with a local account/bar-zero reset. The
    /// underlying OHLCV/funding tape remains one shared `Arc`; no fold market
    /// copy is materialized.
    pub fn for_fold(&self, fold: FoldPlan) -> Result<Self, String> {
        let fold = fold.validate(self.execution_template.bar_count())?;
        let range = fold.test_range();
        Self::from_fold_view(
            Arc::new(self.execution_template.window(range.start, range.end)?),
            self.strategy_program.clone(),
            self.close_projection.clone(),
            self.close_offset
                .checked_add(range.start)
                .ok_or_else(|| "native batch fold projection offset overflow".to_owned())?,
            range.end - range.start,
        )
    }

    #[must_use]
    pub const fn market_key(&self) -> SharedMarketKey {
        self.market_key
    }

    #[must_use]
    pub fn market_bytes(&self) -> usize {
        self.execution_template.source_market_bytes()
    }

    #[must_use]
    pub fn market_view_bytes(&self) -> usize {
        self.execution_template.view_bytes()
    }

    fn new_runner(&self) -> Result<NativeExecutionRunnerV1, String> {
        NativeExecutionRunnerV1::new(self.execution_template.clone())
    }

    fn close_slice(&self) -> &[f64] {
        &self.close_projection[self.close_offset..self.close_offset + self.close_len]
    }

    fn command_tape_for_input(
        &self,
        input: ScenarioInput<'_>,
    ) -> Result<quantbt_domain::CommandTapeV5, String> {
        // The caller owns an immutable prepared signal slice. It is borrowed
        // for compilation and never copied into a per-scenario workload. The
        // resulting command tape is the necessary execution artifact.
        if input.signal.len() != self.close_len {
            return Err("native strategy IR signal must match prepared market bars".to_owned());
        }
        if input.signal.iter().any(|value| !value.is_finite()) {
            return Err("native strategy IR signal must be finite".to_owned());
        }
        if let Some(parameters) = input.parameters
            && (parameters.len() != PARAMETER_WIDTH
                || parameters.iter().any(|value| !value.is_finite()))
        {
            return Err("native strategy IR parameters have an unsupported shape".to_owned());
        }
        self.strategy_program
            .compile_tape(input.signal, self.close_slice(), input.parameters)
            .map_err(|error| error.to_string())
    }

    fn validate_input(&self, input: ScenarioInput<'_>) -> Result<(), String> {
        self.command_tape_for_input(input).map(|_| ())
    }

    fn run_one(
        &self,
        runner: &mut NativeExecutionRunnerV1,
        input: ScenarioInput<'_>,
    ) -> ScenarioOutcome {
        let zero = ScenarioScore {
            scenario: input.scenario,
            final_equity: f64::NAN,
            total_fee: f64::NAN,
            total_funding: f64::NAN,
            turnover: f64::NAN,
            fill_count: 0,
            rejected_count: 0,
            liquidated: false,
        };
        let tape = match self.command_tape_for_input(input) {
            Ok(tape) => tape,
            Err(error) => {
                return ScenarioOutcome {
                    score: zero,
                    status: ScenarioStatus::InvalidInput,
                    error: Some(error.to_string()),
                };
            }
        };
        let request = match NativeExecutionRequestV1::from_template(
            self.execution_template.clone(),
            NativeOutputProfileV1::Score,
            WorkloadPayloadV1::CommandTape(tape),
        ) {
            Ok(request) => request,
            Err(error) => {
                return ScenarioOutcome {
                    score: zero,
                    status: ScenarioStatus::InvalidInput,
                    error: Some(error),
                };
            }
        };
        match runner.execute_request(&request) {
            Ok(result) => {
                let score = result.score();
                ScenarioOutcome {
                    score: ScenarioScore {
                        scenario: input.scenario,
                        final_equity: score.final_equity,
                        total_fee: score.total_fee,
                        total_funding: score.total_funding,
                        turnover: score.total_turnover,
                        fill_count: score.fill_count.max(0) as u64,
                        rejected_count: score.rejected_count.max(0) as u64,
                        liquidated: score.liquidated,
                    },
                    status: ScenarioStatus::Complete,
                    error: None,
                }
            }
            Err(error) => ScenarioOutcome {
                score: zero,
                status: ScenarioStatus::ExecutionError,
                error: Some(error),
            },
        }
    }

    /// Score independent scenarios in deterministic input order. Workers own
    /// their sessions/buffers and never share mutable account or order state.
    pub fn score_batch(
        &self,
        inputs: &[ScenarioInput<'_>],
        plan: BatchPlan,
    ) -> Result<BatchResult, String> {
        let plan = plan.validate()?;
        if inputs.is_empty() {
            return Ok(BatchResult::default());
        }
        if matches!(plan.failure_policy, ScenarioFailurePolicy::FailFast) {
            for input in inputs {
                self.validate_input(*input)?;
            }
        }
        let worker_count = plan.workers.min(inputs.len()).max(1);
        let block = inputs.len().div_ceil(worker_count);
        let mut rows = std::thread::scope(|scope| {
            let mut handles = Vec::with_capacity(worker_count);
            for worker in 0..worker_count {
                let start = worker * block;
                let end = (start + block).min(inputs.len());
                if start >= end {
                    break;
                }
                let template = self.clone();
                let worker_inputs = &inputs[start..end];
                handles.push(
                    scope.spawn(move || -> Result<Vec<ScenarioOutcome>, String> {
                        let mut runner = template.new_runner()?;
                        let mut outcomes = Vec::with_capacity(worker_inputs.len());
                        for chunk in worker_inputs.chunks(plan.chunk_size) {
                            for input in chunk {
                                outcomes.push(template.run_one(&mut runner, *input));
                            }
                        }
                        Ok(outcomes)
                    }),
                );
            }
            let mut joined = Vec::with_capacity(inputs.len());
            for handle in handles {
                let mut worker_rows = handle
                    .join()
                    .map_err(|_| "native batch worker panicked".to_owned())??;
                joined.append(&mut worker_rows);
            }
            Ok::<_, String>(joined)
        })?;
        rows.sort_by_key(|row| row.score.scenario);
        if matches!(plan.failure_policy, ScenarioFailurePolicy::FailFast)
            && let Some(first) = rows
                .iter()
                .find(|row| row.status != ScenarioStatus::Complete)
        {
            return Err(first
                .error
                .clone()
                .unwrap_or_else(|| "native batch scenario failed".to_owned()));
        }
        Ok(BatchResult { rows })
    }

    /// Score an isolated OOS fold. ``inputs`` must carry signals aligned to
    /// the parent prepared market; only the declared OOS slice is executed.
    pub fn score_fold_batch(
        &self,
        inputs: &[ScenarioInput<'_>],
        fold: FoldPlan,
        plan: BatchPlan,
    ) -> Result<FoldBatchResult, String> {
        let fold = fold.validate(self.execution_template.bar_count())?;
        if inputs
            .iter()
            .any(|input| input.signal.len() != self.execution_template.bar_count())
        {
            return Err("fold batch signals must align to the parent prepared market".to_owned());
        }
        let range = fold.test_range();
        let folded = self.for_fold(fold)?;
        let sliced = inputs
            .iter()
            .map(|input| ScenarioInput {
                scenario: input.scenario,
                signal: &input.signal[range.clone()],
                parameters: input.parameters,
            })
            .collect::<Vec<_>>();
        let rows = folded.score_batch(&sliced, plan)?;
        Ok(FoldBatchResult {
            fold,
            rows,
            execution_bars: range.end - range.start,
            // A fold owns only its template/close projection. Market OHLCV,
            // volume, funding, and timestamps remain in the parent `Arc`.
            market_window_bytes: 0,
            market_view_bytes: folded.market_view_bytes(),
            source_market_bytes: folded.market_bytes(),
        })
    }

    /// Re-run one selected scenario with the audit sink. The caller must use
    /// this after stable top-K selection rather than retaining audit data for
    /// every trial.
    pub fn audit_scenario(
        &self,
        input: ScenarioInput<'_>,
    ) -> Result<quantbt_engine::StaticTapeOutput, String> {
        let tape = self.command_tape_for_input(input)?;
        let request = NativeExecutionRequestV1::from_template(
            self.execution_template.clone(),
            NativeOutputProfileV1::Audit,
            WorkloadPayloadV1::CommandTape(tape),
        )?;
        let mut runner = self.new_runner()?;
        runner
            .execute_request(&request)
            .map(quantbt_execution::NativeExecutionResultV1::into_legacy_static)
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BatchResult {
    pub rows: Vec<ScenarioOutcome>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FoldBatchResult {
    pub fold: FoldPlan,
    pub rows: BatchResult,
    pub execution_bars: usize,
    /// Always zero for the shared-view implementation. Retained as an
    /// observable compatibility diagnostic so callers can prove no materialized
    /// fold tape was allocated.
    pub market_window_bytes: usize,
    /// Logical bytes visible to the OOS execution view.
    pub market_view_bytes: usize,
    /// Physical bytes owned by the immutable source tape shared with the
    /// parent template. It is not charged once per fold or scenario.
    pub source_market_bytes: usize,
}

impl BatchResult {
    /// Stable ranking: larger final equity first, then lower scenario ID.
    #[must_use]
    pub fn top_k(&self, k: usize) -> Vec<ScenarioId> {
        let mut complete = self
            .rows
            .iter()
            .filter(|row| row.status == ScenarioStatus::Complete)
            .collect::<Vec<_>>();
        complete.sort_by(|left, right| {
            right
                .score
                .final_equity
                .total_cmp(&left.score.final_equity)
                .then_with(|| left.score.scenario.cmp(&right.score.scenario))
        });
        complete
            .into_iter()
            .take(k)
            .map(|row| row.score.scenario)
            .collect()
    }
}

// ---------------------------------------------------------------------------
// Native WFO Runtime V2
// ---------------------------------------------------------------------------

/// Version marker for the persistent native WFO plan/runtime pair.
pub const NATIVE_WFO_RUNTIME_VERSION_V2: u16 = 2;

/// Typed prepared intent vocabulary accepted by a native WFO plan.
///
/// The runtime deliberately exposes the complete vocabulary before every
/// variant is executable.  V2 certifies only the bounded `StrategyIrSignal`
/// row; later target/portfolio/package phases must opt in with their own
/// accounting and planner contracts rather than being coerced through a
/// signal-tape bridge.
#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PreparedWfoIntentKindV2 {
    StrategyIrSignal = 0,
    TargetUnits = 1,
    TargetNotional = 2,
    TargetWeight = 3,
    EquityFraction = 4,
    StaticOrders = 5,
    PortfolioTargets = 6,
    StrategyIr = 7,
}

impl PreparedWfoIntentKindV2 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::StrategyIrSignal => "strategy_ir_signal_target_v1",
            Self::TargetUnits => "target_units_v2",
            Self::TargetNotional => "target_notional_v2",
            Self::TargetWeight => "target_weight_v2",
            Self::EquityFraction => "equity_fraction_v2",
            Self::StaticOrders => "static_orders_v2",
            Self::PortfolioTargets => "portfolio_targets_v2",
            Self::StrategyIr => "strategy_ir_v2",
        }
    }

    pub fn from_name(value: &str) -> Result<Self, String> {
        match value.trim().to_ascii_lowercase().as_str() {
            "strategy_ir_signal_target_v1" | "strategy_ir_signal" | "signal_target" => {
                Ok(Self::StrategyIrSignal)
            }
            "target_units_v2" | "target_units" => Ok(Self::TargetUnits),
            "target_notional_v2" | "target_notional" => Ok(Self::TargetNotional),
            "target_weight_v2" | "target_weight" => Ok(Self::TargetWeight),
            "equity_fraction_v2" | "equity_fraction" => Ok(Self::EquityFraction),
            "static_orders_v2" | "static_orders" => Ok(Self::StaticOrders),
            "portfolio_targets_v2" | "portfolio_targets" => Ok(Self::PortfolioTargets),
            "strategy_ir_v2" | "strategy_ir" => Ok(Self::StrategyIr),
            _ => Err("unknown native WFO prepared intent kind".to_owned()),
        }
    }
}

/// The optimizer control-flow contract is explicit because batched adaptive
/// TPE is intentionally not candidate-sequence equivalent to sequential TPE.
#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WfoOptimizerScheduleV1 {
    CertifiedSequential = 0,
    ThroughputBatch = 1,
    FixedMatrix = 2,
}

impl WfoOptimizerScheduleV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::CertifiedSequential => "certified_sequential_v1",
            Self::ThroughputBatch => "throughput_batch_v1",
            Self::FixedMatrix => "fixed_matrix_v1",
        }
    }

    pub fn from_name(value: &str) -> Result<Self, String> {
        match value.trim().to_ascii_lowercase().as_str() {
            "certified_sequential_v1" => Ok(Self::CertifiedSequential),
            "throughput_batch_v1" => Ok(Self::ThroughputBatch),
            "fixed_matrix_v1" => Ok(Self::FixedMatrix),
            _ => Err(
                "native WFO optimizer schedule must be certified_sequential_v1, throughput_batch_v1, or fixed_matrix_v1"
                    .to_owned(),
            ),
        }
    }
}

/// Typed non-exception status for one candidate/fold/scenario metric row.
#[repr(u16)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CandidateStatusCodeV2 {
    Success = 0,
    InvalidParameters = 1,
    InvalidIntent = 2,
    UnsupportedCapability = 3,
    MarginRejected = 4,
    Liquidated = 5,
    StrategyError = 6,
    RuntimeCanceled = 7,
    BudgetExceeded = 8,
    InternalInvariantFailure = 9,
}

impl CandidateStatusCodeV2 {
    #[must_use]
    pub const fn code(self) -> u16 {
        self as u16
    }
}

/// Bounded resource plan held for one persistent WFO runtime.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeBudgetV1 {
    pub workers: usize,
    pub max_metric_rows: usize,
    pub max_error_rows: usize,
    pub max_bars: Option<u64>,
    pub max_wall_time_ms: Option<u64>,
    pub max_commands: Option<u64>,
    pub max_orders: Option<u64>,
    pub max_active_orders: Option<u64>,
    pub max_fills: Option<u64>,
    pub max_audit_rows: Option<u64>,
    pub max_native_memory_bytes: Option<u64>,
    pub max_workers: Option<u16>,
}

impl Default for RuntimeBudgetV1 {
    fn default() -> Self {
        Self {
            workers: 1,
            max_metric_rows: 1_000_000,
            max_error_rows: 64,
            max_bars: None,
            max_wall_time_ms: None,
            max_commands: None,
            max_orders: None,
            max_active_orders: None,
            max_fills: None,
            max_audit_rows: None,
            max_native_memory_bytes: None,
            max_workers: None,
        }
    }
}

impl RuntimeBudgetV1 {
    pub fn validate(self) -> Result<Self, String> {
        if self.workers == 0 || self.max_metric_rows == 0 || self.max_error_rows == 0 {
            return Err("native WFO runtime budget values must be > 0".to_owned());
        }
        if self
            .max_workers
            .is_some_and(|limit| self.workers > usize::from(limit))
        {
            return Err("native WFO workers exceed max_workers budget".to_owned());
        }
        Ok(self)
    }

    fn check_optional(limit: Option<u64>, actual: usize, label: &str) -> Result<(), String> {
        if limit.is_some_and(|value| actual as u128 > u128::from(value)) {
            return Err(format!("native WFO {label} budget exceeded"));
        }
        Ok(())
    }

    fn deadline(self) -> Option<Instant> {
        self.max_wall_time_ms
            .map(|value| Instant::now() + Duration::from_millis(value))
    }
}

/// Scalar-only native row for one independent candidate/fold execution.
///
/// It intentionally has no Python object, equity path, fill/event table, or
/// optimizer object.  Audit detail is a selected-candidate rerun only.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WfoCandidateMetricRowV2 {
    pub candidate_id: u64,
    pub fold_id: u32,
    pub scenario_id: u32,
    pub status: CandidateStatusCodeV2,
    pub final_equity: f64,
    pub fold_return: f64,
    pub fold_sharpe: f64,
    pub fold_sortino: f64,
    pub max_drawdown: f64,
    pub turnover: f64,
    pub total_fee: f64,
    pub total_funding: f64,
    pub fill_rate: f64,
    pub fill_count: u64,
    pub rejected_count: u64,
    pub liquidated: bool,
    pub request_fingerprint: [u8; 32],
    pub terminal_fingerprint: [u8; 32],
    /// `u32::MAX` means no retained error text exists for this row.
    pub error_slot: u32,
}

impl WfoCandidateMetricRowV2 {
    fn canceled(candidate_id: u64, fold_id: u32, scenario_id: u32) -> Self {
        Self {
            candidate_id,
            fold_id,
            scenario_id,
            status: CandidateStatusCodeV2::RuntimeCanceled,
            final_equity: f64::NAN,
            fold_return: f64::NAN,
            fold_sharpe: f64::NAN,
            fold_sortino: f64::NAN,
            max_drawdown: f64::NAN,
            turnover: f64::NAN,
            total_fee: f64::NAN,
            total_funding: f64::NAN,
            fill_rate: f64::NAN,
            fill_count: 0,
            rejected_count: 0,
            liquidated: false,
            request_fingerprint: [0; 32],
            terminal_fingerprint: [0; 32],
            error_slot: u32::MAX,
        }
    }

    fn budget_exceeded(candidate_id: u64, fold_id: u32, scenario_id: u32) -> Self {
        Self {
            status: CandidateStatusCodeV2::BudgetExceeded,
            ..Self::canceled(candidate_id, fold_id, scenario_id)
        }
    }

    fn failed(
        candidate_id: u64,
        fold_id: u32,
        scenario_id: u32,
        status: CandidateStatusCodeV2,
        error_slot: u32,
    ) -> Self {
        Self {
            candidate_id,
            fold_id,
            scenario_id,
            status,
            final_equity: f64::NAN,
            fold_return: f64::NAN,
            fold_sharpe: f64::NAN,
            fold_sortino: f64::NAN,
            max_drawdown: f64::NAN,
            turnover: f64::NAN,
            total_fee: f64::NAN,
            total_funding: f64::NAN,
            fill_rate: f64::NAN,
            fill_count: 0,
            rejected_count: 0,
            liquidated: false,
            request_fingerprint: [0; 32],
            terminal_fingerprint: [0; 32],
            error_slot,
        }
    }
}

/// One immutable WFO plan.  It owns references to one prepared execution
/// template and its fold views; no market/tape allocation is made per
/// candidate, scenario, or worker.
#[derive(Clone)]
pub struct NativeWfoPlanV2 {
    base_template: BatchTemplate,
    fold_templates: Arc<[BatchTemplate]>,
    folds: Arc<[FoldPlan]>,
    intent_kind: PreparedWfoIntentKindV2,
    optimizer_schedule: WfoOptimizerScheduleV1,
    budget: RuntimeBudgetV1,
    fingerprint: [u8; 32],
}

impl NativeWfoPlanV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        base_template: BatchTemplate,
        folds: Vec<FoldPlan>,
        intent_kind: PreparedWfoIntentKindV2,
        optimizer_schedule: WfoOptimizerScheduleV1,
        budget: RuntimeBudgetV1,
    ) -> Result<Self, String> {
        let budget = budget.validate()?;
        if intent_kind != PreparedWfoIntentKindV2::StrategyIrSignal {
            return Err(format!(
                "native WFO intent '{}' is not certified in Phase 65; use the explicit compatibility route",
                intent_kind.name()
            ));
        }
        if folds.is_empty() {
            return Err("native WFO plan requires at least one causal fold".to_owned());
        }
        RuntimeBudgetV1::check_optional(
            budget.max_bars,
            base_template.execution_template.bar_count(),
            "bar",
        )?;
        RuntimeBudgetV1::check_optional(
            budget.max_native_memory_bytes,
            base_template.market_bytes(),
            "native memory",
        )?;
        let mut seen_fold_ids = std::collections::BTreeSet::new();
        let mut fold_templates = Vec::with_capacity(folds.len());
        for fold in &folds {
            fold.validate(base_template.execution_template.bar_count())?;
            if !seen_fold_ids.insert(fold.fold_id) {
                return Err("native WFO fold IDs must be unique".to_owned());
            }
            fold_templates.push(base_template.for_fold(*fold)?);
        }
        let fingerprint = native_wfo_plan_fingerprint(
            &base_template,
            &folds,
            intent_kind,
            optimizer_schedule,
            budget,
        );
        Ok(Self {
            base_template,
            fold_templates: fold_templates.into(),
            folds: folds.into(),
            intent_kind,
            optimizer_schedule,
            budget,
            fingerprint,
        })
    }

    #[must_use]
    pub const fn version(&self) -> u16 {
        NATIVE_WFO_RUNTIME_VERSION_V2
    }

    #[must_use]
    pub const fn intent_kind(&self) -> PreparedWfoIntentKindV2 {
        self.intent_kind
    }

    #[must_use]
    pub const fn optimizer_schedule(&self) -> WfoOptimizerScheduleV1 {
        self.optimizer_schedule
    }

    #[must_use]
    pub const fn budget(&self) -> RuntimeBudgetV1 {
        self.budget
    }

    #[must_use]
    pub fn folds(&self) -> &[FoldPlan] {
        &self.folds
    }

    #[must_use]
    pub fn bar_count(&self) -> usize {
        self.base_template.execution_template.bar_count()
    }

    #[must_use]
    pub fn market_bytes(&self) -> usize {
        self.base_template.market_bytes()
    }

    #[must_use]
    pub fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_bytes(&self.fingerprint)
    }

    fn make_worker_runners(&self) -> Result<Vec<NativeExecutionRunnerV1>, String> {
        self.fold_templates
            .iter()
            .map(BatchTemplate::new_runner)
            .collect()
    }
}

/// Immutable, Rust-owned candidate signal/parameter matrix.  Python may make
/// one controlled ingestion copy for each score batch; every worker then
/// borrows these slices without a per-candidate/fold copy.
#[derive(Clone)]
pub struct PreparedWfoSignalBatchV2 {
    candidate_ids: Arc<[u64]>,
    parameters: Option<Arc<[f64]>>,
    values: Arc<[f64]>,
    rows: usize,
    bars: usize,
    fold_count: usize,
    per_fold: bool,
    cost_hints: Arc<[u64]>,
    fingerprint: [u8; 32],
    ingest_bytes: usize,
}

impl PreparedWfoSignalBatchV2 {
    pub fn shared(
        candidate_ids: Vec<u64>,
        values: Vec<f64>,
        bars: usize,
        parameters: Option<Vec<f64>>,
    ) -> Result<Self, String> {
        Self::new(candidate_ids, values, bars, 1, false, parameters)
    }

    pub fn per_fold(
        candidate_ids: Vec<u64>,
        values: Vec<f64>,
        bars: usize,
        fold_count: usize,
        parameters: Option<Vec<f64>>,
    ) -> Result<Self, String> {
        Self::new(candidate_ids, values, bars, fold_count, true, parameters)
    }

    fn new(
        candidate_ids: Vec<u64>,
        values: Vec<f64>,
        bars: usize,
        fold_count: usize,
        per_fold: bool,
        parameters: Option<Vec<f64>>,
    ) -> Result<Self, String> {
        if candidate_ids.is_empty() || bars == 0 || fold_count == 0 {
            return Err("prepared WFO signal batch dimensions must be non-zero".to_owned());
        }
        let rows = candidate_ids.len();
        let matrix_count = if per_fold { fold_count } else { 1 };
        let expected = rows
            .checked_mul(bars)
            .and_then(|value| value.checked_mul(matrix_count))
            .ok_or_else(|| "prepared WFO signal matrix size overflow".to_owned())?;
        if values.len() != expected || values.iter().any(|value| !value.is_finite()) {
            return Err(
                "prepared WFO signal matrix has an invalid shape or non-finite value".to_owned(),
            );
        }
        let mut unique = std::collections::BTreeSet::new();
        if candidate_ids
            .iter()
            .any(|candidate| !unique.insert(*candidate))
        {
            return Err("prepared WFO candidate IDs must be unique".to_owned());
        }
        if let Some(values) = parameters.as_deref()
            && (values.len() != rows * PARAMETER_WIDTH
                || values.iter().any(|value| !value.is_finite()))
        {
            return Err(
                "prepared WFO parameter matrix must have shape (candidates, 4) and be finite"
                    .to_owned(),
            );
        }
        let mut cost_hints = Vec::with_capacity(rows * matrix_count);
        for fold_index in 0..matrix_count {
            for candidate_index in 0..rows {
                let start = (fold_index * rows + candidate_index) * bars;
                let active = values[start..start + bars]
                    .iter()
                    .filter(|value| value.abs() > f64::EPSILON)
                    .count();
                cost_hints.push(u64::try_from(active.saturating_add(1)).unwrap_or(u64::MAX));
            }
        }
        let ingest_bytes = values.len() * std::mem::size_of::<f64>()
            + candidate_ids.len() * std::mem::size_of::<u64>()
            + parameters
                .as_ref()
                .map_or(0, |row| row.len() * std::mem::size_of::<f64>());
        let fingerprint = prepared_signal_fingerprint(
            &candidate_ids,
            &values,
            parameters.as_deref(),
            bars,
            fold_count,
            per_fold,
        );
        Ok(Self {
            candidate_ids: candidate_ids.into(),
            parameters: parameters.map(Into::into),
            values: values.into(),
            rows,
            bars,
            fold_count,
            per_fold,
            cost_hints: cost_hints.into(),
            fingerprint,
            ingest_bytes,
        })
    }

    #[must_use]
    pub const fn rows(&self) -> usize {
        self.rows
    }

    #[must_use]
    pub const fn bars(&self) -> usize {
        self.bars
    }

    #[must_use]
    pub const fn is_per_fold(&self) -> bool {
        self.per_fold
    }

    #[must_use]
    pub fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_bytes(&self.fingerprint)
    }

    #[must_use]
    pub const fn ingest_bytes(&self) -> usize {
        self.ingest_bytes
    }

    fn signal(&self, fold_index: usize, candidate_index: usize) -> &[f64] {
        let matrix = if self.per_fold { fold_index } else { 0 };
        let start = (matrix * self.rows + candidate_index) * self.bars;
        &self.values[start..start + self.bars]
    }

    fn parameters(&self, candidate_index: usize) -> Option<&[f64]> {
        self.parameters.as_deref().map(|values| {
            let start = candidate_index * PARAMETER_WIDTH;
            &values[start..start + PARAMETER_WIDTH]
        })
    }

    fn candidate_id(&self, candidate_index: usize) -> u64 {
        self.candidate_ids[candidate_index]
    }

    fn cost_hint(&self, fold_index: usize, candidate_index: usize) -> u64 {
        let matrix = if self.per_fold { fold_index } else { 0 };
        self.cost_hints[matrix * self.rows + candidate_index]
    }
}

/// Bounded native result matrix for an independent candidate/fold score or
/// audit pass. Errors are held once in a side table, not duplicated as a
/// string per row.
#[derive(Clone, Debug)]
pub struct NativeWfoMetricMatrixV2 {
    pub rows: Vec<WfoCandidateMetricRowV2>,
    pub errors: Vec<String>,
    pub errors_dropped: usize,
    pub plan_fingerprint: [u8; 32],
    pub intent_fingerprint: [u8; 32],
    pub audit: bool,
    pub worker_count: usize,
    pub active_worker_count: usize,
    pub worker_tasks: Vec<u64>,
    pub market_copy_bytes: usize,
    pub candidate_execution_copy_bytes: usize,
    pub intent_ingest_bytes: usize,
    pub worker_pool_creations: u64,
    pub worker_pool_batches: u64,
    pub poison_recoveries: u64,
}

/// Snapshot of persistent runtime ownership. It deliberately reports counts
/// rather than exposing worker/session internals across the Python boundary.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NativeWfoRuntimeStatsV2 {
    pub worker_pool_creations: u64,
    pub score_batches: u64,
    pub audit_batches: u64,
    pub completed_tasks: u64,
    pub canceled_tasks: u64,
    pub poison_recoveries: u64,
    pub worker_tasks: Vec<u64>,
}

impl NativeWfoMetricMatrixV2 {
    #[must_use]
    pub fn plan_fingerprint_hex(&self) -> String {
        hex_bytes(&self.plan_fingerprint)
    }

    #[must_use]
    pub fn intent_fingerprint_hex(&self) -> String {
        hex_bytes(&self.intent_fingerprint)
    }
}

#[derive(Clone, Copy, Debug)]
struct WfoWork {
    candidate_index: usize,
    fold_index: usize,
    cost_hint: u64,
}

#[derive(Default)]
struct WfoErrorTable {
    values: Vec<String>,
    dropped: usize,
    limit: usize,
}

impl WfoErrorTable {
    fn with_limit(limit: usize) -> Self {
        Self {
            values: Vec::with_capacity(limit),
            dropped: 0,
            limit,
        }
    }

    fn retain(&mut self, value: String) -> u32 {
        if self.values.len() < self.limit {
            let slot = u32::try_from(self.values.len()).unwrap_or(u32::MAX);
            self.values.push(value);
            slot
        } else {
            self.dropped = self.dropped.saturating_add(1);
            u32::MAX
        }
    }
}

struct WfoJob {
    batch: Arc<PreparedWfoSignalBatchV2>,
    queue: Mutex<VecDeque<WfoWork>>,
    response: mpsc::Sender<WfoWorkerResponse>,
    output: NativeOutputProfileV1,
    errors: Mutex<WfoErrorTable>,
    deadline: Option<Instant>,
    budget_exceeded: AtomicBool,
}

impl WfoJob {
    fn next_work(&self) -> Option<WfoWork> {
        self.queue
            .lock()
            .expect("native WFO queue lock poisoned")
            .pop_front()
    }

    fn remaining_work(&self) -> Vec<WfoWork> {
        self.queue
            .lock()
            .expect("native WFO queue lock poisoned")
            .drain(..)
            .collect()
    }

    fn error_slot(&self, value: String) -> u32 {
        self.errors
            .lock()
            .expect("native WFO error table lock poisoned")
            .retain(value)
    }

    fn errors(&self) -> (Vec<String>, usize) {
        let table = self
            .errors
            .lock()
            .expect("native WFO error table lock poisoned");
        (table.values.clone(), table.dropped)
    }

    fn timed_out(&self) -> bool {
        self.deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
    }
}

enum WfoWorkerResponse {
    Row(WfoCandidateMetricRowV2),
    Done(usize),
}

enum WfoWorkerMessage {
    Run(Arc<WfoJob>),
    Reset(mpsc::Sender<Result<(), String>>),
    Close,
}

struct WfoWorkerHandle {
    sender: mpsc::Sender<WfoWorkerMessage>,
    join: Mutex<Option<JoinHandle<()>>>,
}

#[derive(Default)]
struct WfoRuntimeCounters {
    worker_pool_creations: u64,
    score_batches: u64,
    audit_batches: u64,
    completed_tasks: u64,
    canceled_tasks: u64,
    poison_recoveries: u64,
    worker_tasks: Vec<u64>,
}

/// Persistent Rust worker runtime for one immutable native WFO plan.
///
/// Workers are created once and retain a `NativeExecutionRunnerV1` per fold.
/// Each score/audit call only ingests prepared intent data and dispatches typed
/// candidate/fold work to the existing pool.  Python strategy generation and
/// optimizer control are deliberately outside this type.
pub struct NativeWfoRuntimeV2 {
    plan: Arc<NativeWfoPlanV2>,
    workers: Vec<WfoWorkerHandle>,
    cancellation: Arc<AtomicBool>,
    closed: AtomicBool,
    running: AtomicBool,
    injected_poison: Arc<AtomicU64>,
    generation: AtomicU64,
    counters: Arc<Mutex<WfoRuntimeCounters>>,
}

impl NativeWfoRuntimeV2 {
    pub fn new(plan: Arc<NativeWfoPlanV2>) -> Result<Self, String> {
        let worker_count = plan.budget().workers;
        let cancellation = Arc::new(AtomicBool::new(false));
        let counters = Arc::new(Mutex::new(WfoRuntimeCounters {
            worker_pool_creations: 1,
            worker_tasks: vec![0; worker_count],
            ..WfoRuntimeCounters::default()
        }));
        let injected_poison = Arc::new(AtomicU64::new(0));
        let mut workers = Vec::with_capacity(worker_count);
        for worker_id in 0..worker_count {
            let (sender, receiver) = mpsc::channel();
            let worker_plan = plan.clone();
            let worker_cancel = cancellation.clone();
            let worker_counters = counters.clone();
            let worker_poison = injected_poison.clone();
            let join = std::thread::Builder::new()
                .name(format!("quantbt-wfo-{worker_id}"))
                .spawn(move || {
                    native_wfo_worker_loop(
                        worker_id,
                        worker_plan,
                        receiver,
                        worker_cancel,
                        worker_counters,
                        worker_poison,
                    )
                })
                .map_err(|error| format!("failed to start native WFO worker: {error}"))?;
            workers.push(WfoWorkerHandle {
                sender,
                join: Mutex::new(Some(join)),
            });
        }
        let runtime = Self {
            plan,
            workers,
            cancellation,
            closed: AtomicBool::new(false),
            running: AtomicBool::new(false),
            injected_poison,
            generation: AtomicU64::new(1),
            counters,
        };
        Ok(runtime)
    }

    #[must_use]
    pub fn plan(&self) -> &NativeWfoPlanV2 {
        &self.plan
    }

    #[must_use]
    pub fn closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }

    pub fn cancel(&self) {
        self.cancellation.store(true, Ordering::Release);
    }

    pub fn clear_cancellation(&self) {
        self.cancellation.store(false, Ordering::Release);
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::Acquire)
    }

    /// Test-only fault injection. A real panic is also caught and causes the
    /// same session reconstruction path, but production callers never need
    /// this method.
    pub fn inject_poison_for_test(&self, count: u64) {
        self.injected_poison.fetch_add(count, Ordering::AcqRel);
    }

    pub fn reset(&self) -> Result<(), String> {
        self.ensure_idle()?;
        if self.closed() {
            return Err("native WFO runtime is closed".to_owned());
        }
        self.clear_cancellation();
        let (sender, receiver) = mpsc::channel();
        for worker in &self.workers {
            worker
                .sender
                .send(WfoWorkerMessage::Reset(sender.clone()))
                .map_err(|_| "native WFO worker is unavailable during reset".to_owned())?;
        }
        for _ in &self.workers {
            receiver
                .recv()
                .map_err(|_| "native WFO worker reset response is unavailable".to_owned())??;
        }
        self.generation.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    pub fn score(
        &self,
        batch: Arc<PreparedWfoSignalBatchV2>,
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        self.run(batch, NativeOutputProfileV1::Score, None)
    }

    pub fn audit_selected(
        &self,
        batch: Arc<PreparedWfoSignalBatchV2>,
        candidate_ids: &[u64],
        expected_intent_fingerprint: [u8; 32],
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        if batch.fingerprint() != expected_intent_fingerprint {
            return Err(
                "native WFO audit batch fingerprint differs from the scored prepared intent"
                    .to_owned(),
            );
        }
        let selected = candidate_ids
            .iter()
            .copied()
            .collect::<std::collections::BTreeSet<_>>();
        if selected.is_empty() {
            return Err("native WFO audit requires at least one selected candidate".to_owned());
        }
        let available = batch
            .candidate_ids
            .iter()
            .copied()
            .collect::<std::collections::BTreeSet<_>>();
        if selected
            .iter()
            .any(|candidate_id| !available.contains(candidate_id))
        {
            return Err(
                "native WFO audit candidate was not present in the scored prepared intent"
                    .to_owned(),
            );
        }
        self.run(batch, NativeOutputProfileV1::Audit, Some(selected))
    }

    #[must_use]
    pub fn stats(&self) -> NativeWfoRuntimeStatsV2 {
        let values = self
            .counters
            .lock()
            .expect("native WFO counter lock poisoned");
        NativeWfoRuntimeStatsV2 {
            worker_pool_creations: values.worker_pool_creations,
            score_batches: values.score_batches,
            audit_batches: values.audit_batches,
            completed_tasks: values.completed_tasks,
            canceled_tasks: values.canceled_tasks,
            poison_recoveries: values.poison_recoveries,
            worker_tasks: values.worker_tasks.clone(),
        }
    }

    fn run(
        &self,
        batch: Arc<PreparedWfoSignalBatchV2>,
        output: NativeOutputProfileV1,
        selected: Option<std::collections::BTreeSet<u64>>,
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        if self.closed() {
            return Err("native WFO runtime is closed".to_owned());
        }
        if batch.bars() != self.plan.bar_count() {
            return Err(
                "prepared WFO signal bars differ from the immutable native WFO plan".to_owned(),
            );
        }
        if batch.is_per_fold() && batch.fold_count != self.plan.folds().len() {
            return Err(
                "prepared per-fold WFO signal cube does not match plan fold count".to_owned(),
            );
        }
        let candidate_count = selected
            .as_ref()
            .map_or_else(|| batch.rows(), std::collections::BTreeSet::len);
        let expected_rows = candidate_count
            .checked_mul(self.plan.folds().len())
            .ok_or_else(|| "native WFO metric row count overflow".to_owned())?;
        if expected_rows > self.plan.budget().max_metric_rows {
            return Err("native WFO metric row budget exceeded before execution".to_owned());
        }
        if output == NativeOutputProfileV1::Audit {
            RuntimeBudgetV1::check_optional(
                self.plan.budget().max_audit_rows,
                expected_rows,
                "audit row",
            )?;
        }
        RuntimeBudgetV1::check_optional(
            self.plan.budget().max_native_memory_bytes,
            self.plan
                .market_bytes()
                .saturating_add(batch.ingest_bytes()),
            "native memory",
        )?;
        self.running
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| "native WFO runtime already has an active score batch".to_owned())?;
        let result = self.run_active(batch, output, selected);
        self.running.store(false, Ordering::Release);
        result
    }

    fn run_active(
        &self,
        batch: Arc<PreparedWfoSignalBatchV2>,
        output: NativeOutputProfileV1,
        selected: Option<std::collections::BTreeSet<u64>>,
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        {
            let mut counters = self
                .counters
                .lock()
                .expect("native WFO counter lock poisoned");
            if output == NativeOutputProfileV1::Audit {
                counters.audit_batches = counters.audit_batches.saturating_add(1);
            } else {
                counters.score_batches = counters.score_batches.saturating_add(1);
            }
        }
        let mut work = Vec::new();
        for (fold_index, fold) in self.plan.folds().iter().enumerate() {
            for candidate_index in 0..batch.rows() {
                let candidate_id = batch.candidate_id(candidate_index);
                if selected
                    .as_ref()
                    .is_some_and(|ids| !ids.contains(&candidate_id))
                {
                    continue;
                }
                work.push(WfoWork {
                    candidate_index,
                    fold_index,
                    cost_hint: batch.cost_hint(fold_index, candidate_index),
                });
            }
            if fold.fold_id != self.plan.folds()[fold_index].fold_id {
                return Err("native WFO plan fold identity changed during execution".to_owned());
            }
        }
        // Cost-descending dispatch gives the stealing queue long/high-churn
        // work first, while the final result is sorted by stable IDs below.
        work.sort_by(|left, right| {
            right
                .cost_hint
                .cmp(&left.cost_hint)
                .then_with(|| {
                    batch
                        .candidate_id(left.candidate_index)
                        .cmp(&batch.candidate_id(right.candidate_index))
                })
                .then_with(|| left.fold_index.cmp(&right.fold_index))
        });
        let active_worker_count = self.workers.len().min(work.len());
        let work_len = work.len();
        let (sender, receiver) = mpsc::channel();
        let job = Arc::new(WfoJob {
            batch: batch.clone(),
            queue: Mutex::new(VecDeque::from(work)),
            response: sender,
            output,
            errors: Mutex::new(WfoErrorTable::with_limit(self.plan.budget().max_error_rows)),
            deadline: self.plan.budget().deadline(),
            budget_exceeded: AtomicBool::new(false),
        });
        for worker in &self.workers {
            worker
                .sender
                .send(WfoWorkerMessage::Run(job.clone()))
                .map_err(|_| "native WFO worker is unavailable during score".to_owned())?;
        }
        let mut rows = Vec::with_capacity(work_len);
        let mut done = 0_usize;
        while done < self.workers.len() {
            match receiver
                .recv()
                .map_err(|_| "native WFO worker response channel closed".to_owned())?
            {
                WfoWorkerResponse::Row(row) => rows.push(row),
                WfoWorkerResponse::Done(worker_id) => {
                    if worker_id >= self.workers.len() {
                        return Err("native WFO worker reported an invalid ID".to_owned());
                    }
                    done += 1;
                }
            }
        }
        for remaining in job.remaining_work() {
            let constructor = if job.budget_exceeded.load(Ordering::Acquire) {
                WfoCandidateMetricRowV2::budget_exceeded
            } else {
                WfoCandidateMetricRowV2::canceled
            };
            rows.push(constructor(
                batch.candidate_id(remaining.candidate_index),
                self.plan.folds()[remaining.fold_index].fold_id,
                0,
            ));
        }
        rows.sort_by(|left, right| {
            left.candidate_id
                .cmp(&right.candidate_id)
                .then_with(|| left.fold_id.cmp(&right.fold_id))
                .then_with(|| left.scenario_id.cmp(&right.scenario_id))
        });
        let (errors, errors_dropped) = job.errors();
        let counters = self
            .counters
            .lock()
            .expect("native WFO counter lock poisoned");
        Ok(NativeWfoMetricMatrixV2 {
            rows,
            errors,
            errors_dropped,
            plan_fingerprint: self.plan.fingerprint(),
            intent_fingerprint: batch.fingerprint(),
            audit: output == NativeOutputProfileV1::Audit,
            worker_count: self.workers.len(),
            active_worker_count,
            worker_tasks: counters.worker_tasks.clone(),
            market_copy_bytes: 0,
            candidate_execution_copy_bytes: 0,
            intent_ingest_bytes: batch.ingest_bytes(),
            worker_pool_creations: counters.worker_pool_creations,
            worker_pool_batches: counters
                .score_batches
                .saturating_add(counters.audit_batches),
            poison_recoveries: counters.poison_recoveries,
        })
    }

    fn ensure_idle(&self) -> Result<(), String> {
        if self.running.load(Ordering::Acquire) {
            Err("native WFO runtime cannot reset/close while a score batch is active".to_owned())
        } else {
            Ok(())
        }
    }

    pub fn close(&self) -> Result<(), String> {
        self.ensure_idle()?;
        if self.closed.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        self.cancel();
        for worker in &self.workers {
            let _ = worker.sender.send(WfoWorkerMessage::Close);
        }
        for worker in &self.workers {
            if let Some(join) = worker
                .join
                .lock()
                .expect("native WFO join lock poisoned")
                .take()
            {
                join.join()
                    .map_err(|_| "native WFO worker panicked while closing".to_owned())?;
            }
        }
        Ok(())
    }
}

impl Drop for NativeWfoRuntimeV2 {
    fn drop(&mut self) {
        // Drop must not panic. A live Python owner should use `close()` for a
        // deterministic error surface; this only guarantees worker teardown.
        if self.closed.swap(true, Ordering::AcqRel) {
            return;
        }
        self.cancellation.store(true, Ordering::Release);
        for worker in &self.workers {
            let _ = worker.sender.send(WfoWorkerMessage::Close);
        }
        for worker in &self.workers {
            if let Some(join) = worker
                .join
                .lock()
                .expect("native WFO join lock poisoned")
                .take()
            {
                let _ = join.join();
            }
        }
    }
}

fn native_wfo_worker_loop(
    worker_id: usize,
    plan: Arc<NativeWfoPlanV2>,
    receiver: mpsc::Receiver<WfoWorkerMessage>,
    cancellation: Arc<AtomicBool>,
    counters: Arc<Mutex<WfoRuntimeCounters>>,
    injected_poison: Arc<AtomicU64>,
) {
    let mut runners = match plan.make_worker_runners() {
        Ok(runners) => runners,
        Err(_) => return,
    };
    while let Ok(message) = receiver.recv() {
        match message {
            WfoWorkerMessage::Run(job) => {
                while !cancellation.load(Ordering::Acquire) {
                    if job.timed_out() {
                        job.budget_exceeded.store(true, Ordering::Release);
                        break;
                    }
                    let Some(work) = job.next_work() else {
                        break;
                    };
                    let row = if injected_poison
                        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                            value.checked_sub(1)
                        })
                        .is_ok()
                    {
                        runners = plan.make_worker_runners().unwrap_or_default();
                        let slot = job
                            .error_slot("injected native WFO worker poison recovered".to_owned());
                        let mut values = counters.lock().expect("native WFO counter lock poisoned");
                        values.poison_recoveries = values.poison_recoveries.saturating_add(1);
                        WfoCandidateMetricRowV2::failed(
                            job.batch.candidate_id(work.candidate_index),
                            plan.folds()[work.fold_index].fold_id,
                            0,
                            CandidateStatusCodeV2::InternalInvariantFailure,
                            slot,
                        )
                    } else {
                        match catch_unwind(AssertUnwindSafe(|| {
                            execute_native_wfo_work(&plan, &mut runners, &job, work)
                        })) {
                            Ok(row) => row,
                            Err(_) => {
                                runners = plan.make_worker_runners().unwrap_or_default();
                                let slot = job.error_slot(
                                    "native WFO worker panic recovered with fresh sessions"
                                        .to_owned(),
                                );
                                let mut values =
                                    counters.lock().expect("native WFO counter lock poisoned");
                                values.poison_recoveries =
                                    values.poison_recoveries.saturating_add(1);
                                WfoCandidateMetricRowV2::failed(
                                    job.batch.candidate_id(work.candidate_index),
                                    plan.folds()[work.fold_index].fold_id,
                                    0,
                                    CandidateStatusCodeV2::InternalInvariantFailure,
                                    slot,
                                )
                            }
                        }
                    };
                    {
                        let mut values = counters.lock().expect("native WFO counter lock poisoned");
                        values.completed_tasks = values.completed_tasks.saturating_add(1);
                        if let Some(count) = values.worker_tasks.get_mut(worker_id) {
                            *count = count.saturating_add(1);
                        }
                    }
                    let _ = job.response.send(WfoWorkerResponse::Row(row));
                }
                if cancellation.load(Ordering::Acquire) {
                    let mut values = counters.lock().expect("native WFO counter lock poisoned");
                    values.canceled_tasks = values.canceled_tasks.saturating_add(1);
                }
                let _ = job.response.send(WfoWorkerResponse::Done(worker_id));
            }
            WfoWorkerMessage::Reset(response) => {
                runners = plan.make_worker_runners().unwrap_or_default();
                let result = if runners.len() == plan.folds().len() {
                    Ok(())
                } else {
                    Err("native WFO worker could not rebuild fold sessions".to_owned())
                };
                let _ = response.send(result);
            }
            WfoWorkerMessage::Close => break,
        }
    }
}

fn execute_native_wfo_work(
    plan: &NativeWfoPlanV2,
    runners: &mut [NativeExecutionRunnerV1],
    job: &WfoJob,
    work: WfoWork,
) -> WfoCandidateMetricRowV2 {
    let candidate_id = job.batch.candidate_id(work.candidate_index);
    let fold = plan.folds()[work.fold_index];
    let template = &plan.fold_templates[work.fold_index];
    let full_signal = job.batch.signal(work.fold_index, work.candidate_index);
    let range = fold.test_range();
    let signal = &full_signal[range];
    let input = ScenarioInput {
        scenario: ScenarioId(0),
        signal,
        parameters: job.batch.parameters(work.candidate_index),
    };
    let tape = match template.command_tape_for_input(input) {
        Ok(tape) => tape,
        Err(error) => {
            let slot = job.error_slot(error);
            return WfoCandidateMetricRowV2::failed(
                candidate_id,
                fold.fold_id,
                0,
                CandidateStatusCodeV2::InvalidIntent,
                slot,
            );
        }
    };
    let command_count = tape.command_count();
    let budget = plan.budget();
    for (limit, label) in [
        (budget.max_commands, "command"),
        (budget.max_orders, "order"),
        (budget.max_active_orders, "active-order upper-bound"),
        (budget.max_fills, "fill upper-bound"),
    ] {
        if RuntimeBudgetV1::check_optional(limit, command_count, label).is_err() {
            return WfoCandidateMetricRowV2::budget_exceeded(candidate_id, fold.fold_id, 0);
        }
    }
    let request = match NativeExecutionRequestV1::from_template(
        template.execution_template.clone(),
        job.output,
        WorkloadPayloadV1::CommandTape(tape),
    ) {
        Ok(request) => request,
        Err(error) => {
            let slot = job.error_slot(error);
            return WfoCandidateMetricRowV2::failed(
                candidate_id,
                fold.fold_id,
                0,
                CandidateStatusCodeV2::InvalidIntent,
                slot,
            );
        }
    };
    let runner = match runners.get_mut(work.fold_index) {
        Some(runner) => runner,
        None => {
            let slot = job.error_slot("native WFO worker has no fold session".to_owned());
            return WfoCandidateMetricRowV2::failed(
                candidate_id,
                fold.fold_id,
                0,
                CandidateStatusCodeV2::InternalInvariantFailure,
                slot,
            );
        }
    };
    match runner.execute_request(&request) {
        Ok(result) => {
            let score = result.score();
            let metrics = *score.metrics_v2;
            let status = if score.liquidated {
                CandidateStatusCodeV2::Liquidated
            } else {
                CandidateStatusCodeV2::Success
            };
            WfoCandidateMetricRowV2 {
                candidate_id,
                fold_id: fold.fold_id,
                scenario_id: 0,
                status,
                final_equity: score.final_equity,
                fold_return: metrics.total_return,
                fold_sharpe: metrics.sharpe,
                fold_sortino: metrics.sortino,
                max_drawdown: metrics.max_drawdown,
                turnover: score.total_turnover,
                total_fee: score.total_fee,
                total_funding: score.total_funding,
                fill_rate: if command_count == 0 {
                    1.0
                } else {
                    (score.fill_count.max(0) as f64 / command_count as f64).min(1.0)
                },
                fill_count: score.fill_count.max(0) as u64,
                rejected_count: score.rejected_count.max(0) as u64,
                liquidated: score.liquidated,
                request_fingerprint: result.request_fingerprint,
                terminal_fingerprint: result.header_v2.terminal_fingerprint,
                error_slot: u32::MAX,
            }
        }
        Err(error) => {
            let slot = job.error_slot(error);
            WfoCandidateMetricRowV2::failed(
                candidate_id,
                fold.fold_id,
                0,
                CandidateStatusCodeV2::InternalInvariantFailure,
                slot,
            )
        }
    }
}

fn native_wfo_plan_fingerprint(
    template: &BatchTemplate,
    folds: &[FoldPlan],
    intent: PreparedWfoIntentKindV2,
    schedule: WfoOptimizerScheduleV1,
    budget: RuntimeBudgetV1,
) -> [u8; 32] {
    let mut writer = StableFingerprint::new(b"quantbt-native-wfo-plan-v2");
    writer.bytes(&template.execution_template.fingerprint());
    writer.bytes(&template.strategy_program.fingerprint());
    writer.u8(intent as u8);
    writer.u8(schedule as u8);
    writer.usize(budget.workers);
    writer.usize(budget.max_metric_rows);
    writer.usize(budget.max_error_rows);
    for limit in [
        budget.max_bars,
        budget.max_wall_time_ms,
        budget.max_commands,
        budget.max_orders,
        budget.max_active_orders,
        budget.max_fills,
        budget.max_audit_rows,
        budget.max_native_memory_bytes,
        budget.max_workers.map(u64::from),
    ] {
        writer.u64(limit.unwrap_or(u64::MAX));
    }
    writer.usize(folds.len());
    for fold in folds {
        writer.u32(fold.fold_id);
        writer.u32(fold.warmup_start);
        writer.u32(fold.train_start);
        writer.u32(fold.train_end);
        writer.u32(fold.test_start);
        writer.u32(fold.test_end);
    }
    writer.finish()
}

fn prepared_signal_fingerprint(
    candidate_ids: &[u64],
    signals: &[f64],
    parameters: Option<&[f64]>,
    bars: usize,
    fold_count: usize,
    per_fold: bool,
) -> [u8; 32] {
    let mut writer = StableFingerprint::new(b"quantbt-prepared-wfo-signal-v2");
    writer.usize(candidate_ids.len());
    writer.usize(bars);
    writer.usize(fold_count);
    writer.u8(u8::from(per_fold));
    for candidate in candidate_ids {
        writer.u64(*candidate);
    }
    for value in signals {
        writer.f64(*value);
    }
    match parameters {
        Some(values) => {
            writer.u8(1);
            for value in values {
                writer.f64(*value);
            }
        }
        None => writer.u8(0),
    }
    writer.finish()
}

struct StableFingerprint {
    state: [u64; 4],
}

impl StableFingerprint {
    fn new(domain: &[u8]) -> Self {
        let mut value = Self {
            state: [
                0xcbf2_9ce4_8422_2325,
                0x8422_2325_cbf2_9ce4,
                0x9e37_79b9_7f4a_7c15,
                0x517c_c1b7_2722_0a95,
            ],
        };
        value.bytes(domain);
        value
    }

    fn bytes(&mut self, bytes: &[u8]) {
        for (index, byte) in bytes.iter().copied().enumerate() {
            let lane = index & 3;
            self.state[lane] ^= u64::from(byte);
            self.state[lane] = self.state[lane].wrapping_mul(0x1000_0000_01b3);
            self.state[lane] ^= self.state[(lane + 1) & 3].rotate_left(13);
        }
    }

    fn u8(&mut self, value: u8) {
        self.bytes(&[value]);
    }

    fn u32(&mut self, value: u32) {
        self.bytes(&value.to_le_bytes());
    }

    fn u64(&mut self, value: u64) {
        self.bytes(&value.to_le_bytes());
    }

    fn usize(&mut self, value: usize) {
        self.u64(u64::try_from(value).unwrap_or(u64::MAX));
    }

    fn f64(&mut self, value: f64) {
        self.u64(if value == 0.0 {
            0.0f64.to_bits()
        } else {
            value.to_bits()
        });
    }

    fn finish(mut self) -> [u8; 32] {
        for lane in 0..4 {
            self.state[lane] ^= self.state[(lane + 1) & 3].rotate_left(17);
            self.state[lane] = self.state[lane].wrapping_mul(0x9e37_79b9_7f4a_7c15);
        }
        let mut bytes = [0_u8; 32];
        for (index, state) in self.state.into_iter().enumerate() {
            bytes[index * 8..(index + 1) * 8].copy_from_slice(&state.to_le_bytes());
        }
        bytes
    }
}

fn hex_bytes(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        value.push(DIGITS[(byte >> 4) as usize] as char);
        value.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    value
}

#[cfg(test)]
mod tests {
    use super::*;
    use quantbt_strategy_ir::{
        ProgramLimits, STRATEGY_IR_VERSION, StrategyKind, StrategyParameters,
    };

    fn template() -> BatchTemplate {
        let market = Arc::new(
            FullMarketData::new(
                vec![0, 1, 2, 3, 4],
                vec![100.0; 5],
                vec![101.0; 5],
                vec![99.0; 5],
                vec![100.0, 101.0, 102.0, 101.0, 100.0],
                vec![1.0; 5],
                vec![0.0; 5],
                vec![false; 5],
                1,
            )
            .unwrap(),
        );
        let program = Arc::new(
            StrategyProgram::new(
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
            .unwrap(),
        );
        BatchTemplate::new(
            market,
            program,
            Arc::from(vec![1.0]),
            Arc::from(vec![1.0]),
            Arc::from(vec![0.0]),
            10_000.0,
            0.005,
            0.0,
            false,
            2,
        )
        .unwrap()
    }

    #[test]
    fn batch_is_exact_across_worker_counts_and_keeps_stable_top_k() {
        let template = template();
        let signals = [
            [0.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, -1.0, -1.0, 0.0, 0.0],
            [0.0, 1.0, -1.0, 0.0, 0.0],
        ];
        let parameters = [[1.0, 0.0, 0.0, 0.0]; 3];
        let inputs = signals
            .iter()
            .zip(parameters.iter())
            .enumerate()
            .map(|(id, (signal, parameter))| ScenarioInput {
                scenario: ScenarioId(id as u32),
                signal,
                parameters: Some(parameter),
            })
            .collect::<Vec<_>>();
        let one = template
            .score_batch(
                &inputs,
                BatchPlan {
                    workers: 1,
                    ..BatchPlan::default()
                },
            )
            .unwrap();
        let many = template
            .score_batch(
                &inputs,
                BatchPlan {
                    workers: 3,
                    ..BatchPlan::default()
                },
            )
            .unwrap();
        assert_eq!(one, many);
        assert_eq!(one.rows.len(), 3);
        assert_eq!(one.top_k(2), many.top_k(2));
        assert!(template.market_bytes() > 0);
    }

    #[test]
    fn collect_policy_keeps_other_scenarios_when_one_parameter_row_is_invalid() {
        let template = template();
        let valid = [0.0, 1.0, 0.0, 0.0, 0.0];
        let invalid = [0.0, 1.0, 0.0, 0.0];
        let parameters = [1.0, 0.0, 0.0, 0.0];
        let inputs = [
            ScenarioInput {
                scenario: ScenarioId(0),
                signal: &valid,
                parameters: Some(&parameters),
            },
            ScenarioInput {
                scenario: ScenarioId(1),
                signal: &invalid,
                parameters: Some(&parameters),
            },
        ];
        let result = template.score_batch(&inputs, BatchPlan::default()).unwrap();
        assert_eq!(result.rows[0].status, ScenarioStatus::Complete);
        assert_eq!(result.rows[1].status, ScenarioStatus::InvalidInput);
    }

    #[test]
    fn fold_batch_is_causal_and_reuses_one_shared_oos_view_for_all_scenarios() {
        let template = template();
        let signal = [0.0, 1.0, 1.0, 0.0, -1.0];
        let params = [1.0, 0.0, 0.0, 0.0];
        let inputs = [
            ScenarioInput {
                scenario: ScenarioId(0),
                signal: &signal,
                parameters: Some(&params),
            },
            ScenarioInput {
                scenario: ScenarioId(1),
                signal: &signal,
                parameters: Some(&params),
            },
        ];
        let result = template
            .score_fold_batch(
                &inputs,
                FoldPlan {
                    fold_id: 7,
                    warmup_start: 0,
                    train_start: 0,
                    train_end: 2,
                    test_start: 2,
                    test_end: 5,
                },
                BatchPlan {
                    workers: 2,
                    ..BatchPlan::default()
                },
            )
            .unwrap();
        assert_eq!(result.execution_bars, 3);
        assert_eq!(result.rows.rows.len(), 2);
        assert_eq!(result.market_window_bytes, 0);
        assert!(result.market_view_bytes > 0);
        assert_eq!(result.source_market_bytes, template.market_bytes());
        let folded = template
            .for_fold(FoldPlan {
                fold_id: 7,
                warmup_start: 0,
                train_start: 0,
                train_end: 2,
                test_start: 2,
                test_end: 5,
            })
            .unwrap();
        assert!(Arc::ptr_eq(
            template.execution_template.market(),
            folded.execution_template.market()
        ));
        assert!(
            template
                .for_fold(FoldPlan {
                    fold_id: 0,
                    warmup_start: 0,
                    train_start: 0,
                    train_end: 4,
                    test_start: 3,
                    test_end: 5,
                })
                .is_err()
        );
    }

    fn native_wfo_plan(workers: usize) -> Arc<NativeWfoPlanV2> {
        Arc::new(
            NativeWfoPlanV2::new(
                template(),
                vec![
                    FoldPlan {
                        fold_id: 10,
                        warmup_start: 0,
                        train_start: 0,
                        train_end: 1,
                        test_start: 1,
                        test_end: 3,
                    },
                    FoldPlan {
                        fold_id: 20,
                        warmup_start: 0,
                        train_start: 0,
                        train_end: 3,
                        test_start: 3,
                        test_end: 5,
                    },
                ],
                PreparedWfoIntentKindV2::StrategyIrSignal,
                WfoOptimizerScheduleV1::FixedMatrix,
                RuntimeBudgetV1 {
                    workers,
                    max_metric_rows: 32,
                    max_error_rows: 4,
                    ..RuntimeBudgetV1::default()
                },
            )
            .unwrap(),
        )
    }

    fn native_wfo_batch() -> Arc<PreparedWfoSignalBatchV2> {
        Arc::new(
            PreparedWfoSignalBatchV2::shared(
                vec![101, 202, 303],
                vec![
                    0.0, 1.0, 1.0, 0.0, 0.0, // 101
                    0.0, -1.0, -1.0, 0.0, 0.0, // 202
                    0.0, 1.0, -1.0, 0.0, 0.0, // 303
                ],
                5,
                Some(vec![
                    1.0, 0.0, 0.0, 0.0, // 101
                    1.0, 0.0, 0.0, 0.0, // 202
                    1.0, 0.0, 0.0, 0.0, // 303
                ]),
            )
            .unwrap(),
        )
    }

    #[test]
    fn native_wfo_runtime_matches_fold_oracle_and_is_worker_count_invariant() {
        let batch = native_wfo_batch();
        let one = NativeWfoRuntimeV2::new(native_wfo_plan(1)).unwrap();
        let many = NativeWfoRuntimeV2::new(native_wfo_plan(3)).unwrap();
        let one_rows = one.score(batch.clone()).unwrap();
        let many_rows = many.score(batch.clone()).unwrap();

        assert_eq!(one_rows.rows, many_rows.rows);
        assert_eq!(one_rows.market_copy_bytes, 0);
        assert_eq!(one_rows.candidate_execution_copy_bytes, 0);
        assert_eq!(one_rows.worker_pool_creations, 1);
        assert_eq!(many_rows.worker_pool_creations, 1);
        assert_eq!(one_rows.rows.len(), 6);

        let oracle_template = template();
        let params = [1.0, 0.0, 0.0, 0.0];
        let signals = [
            [0.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, -1.0, -1.0, 0.0, 0.0],
            [0.0, 1.0, -1.0, 0.0, 0.0],
        ];
        for fold in native_wfo_plan(1).folds() {
            let inputs = signals
                .iter()
                .enumerate()
                .map(|(index, signal)| ScenarioInput {
                    scenario: ScenarioId(index as u32),
                    signal,
                    parameters: Some(&params),
                })
                .collect::<Vec<_>>();
            let oracle = oracle_template
                .score_fold_batch(&inputs, *fold, BatchPlan::default())
                .unwrap();
            for (index, expected) in oracle.rows.rows.iter().enumerate() {
                let actual = one_rows
                    .rows
                    .iter()
                    .find(|row| {
                        row.fold_id == fold.fold_id && row.candidate_id == [101, 202, 303][index]
                    })
                    .unwrap();
                assert_eq!(actual.status, CandidateStatusCodeV2::Success);
                assert_eq!(actual.final_equity, expected.score.final_equity);
                assert_eq!(actual.total_fee, expected.score.total_fee);
                assert_eq!(actual.total_funding, expected.score.total_funding);
                assert_eq!(actual.turnover, expected.score.turnover);
                assert_eq!(actual.fill_count, expected.score.fill_count);
                assert_eq!(actual.rejected_count, expected.score.rejected_count);
                assert_eq!(actual.liquidated, expected.score.liquidated);
            }
        }
        one.close().unwrap();
        many.close().unwrap();
    }

    #[test]
    fn native_wfo_runtime_reuses_workers_and_audit_replays_identical_terminal_state() {
        let batch = native_wfo_batch();
        let runtime = NativeWfoRuntimeV2::new(native_wfo_plan(2)).unwrap();
        let score = runtime.score(batch.clone()).unwrap();
        let score_again = runtime.score(batch.clone()).unwrap();
        assert_eq!(score.rows, score_again.rows);
        assert_eq!(score.worker_pool_creations, 1);
        assert_eq!(score_again.worker_pool_creations, 1);
        assert_eq!(score_again.worker_pool_batches, 2);

        let audit = runtime
            .audit_selected(batch.clone(), &[202], score.intent_fingerprint)
            .unwrap();
        assert!(audit.audit);
        assert_eq!(audit.rows.len(), 2);
        for audit_row in &audit.rows {
            let score_row = score
                .rows
                .iter()
                .find(|row| {
                    row.candidate_id == audit_row.candidate_id && row.fold_id == audit_row.fold_id
                })
                .unwrap();
            assert_eq!(
                audit_row.terminal_fingerprint,
                score_row.terminal_fingerprint
            );
            assert_eq!(audit_row.final_equity, score_row.final_equity);
        }
        assert!(
            runtime
                .audit_selected(batch.clone(), &[999], score.intent_fingerprint)
                .is_err()
        );
        let stats = runtime.stats();
        assert_eq!(stats.worker_pool_creations, 1);
        assert_eq!(stats.score_batches, 2);
        assert_eq!(stats.audit_batches, 1);
        runtime.close().unwrap();
    }

    #[test]
    fn native_wfo_runtime_rebuilds_after_a_bounded_worker_fault() {
        let batch = native_wfo_batch();
        let runtime = NativeWfoRuntimeV2::new(native_wfo_plan(1)).unwrap();
        runtime.inject_poison_for_test(1);
        let failed = runtime.score(batch.clone()).unwrap();
        assert!(
            failed
                .rows
                .iter()
                .any(|row| { row.status == CandidateStatusCodeV2::InternalInvariantFailure })
        );
        assert_eq!(runtime.stats().poison_recoveries, 1);
        runtime.reset().unwrap();
        let recovered = runtime.score(batch).unwrap();
        assert!(
            recovered
                .rows
                .iter()
                .all(|row| row.status == CandidateStatusCodeV2::Success)
        );
        runtime.close().unwrap();
    }
}
