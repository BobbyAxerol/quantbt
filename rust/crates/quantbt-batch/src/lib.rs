//! Deterministic native scenario batching over one immutable market tape.
//!
//! This crate deliberately batches only bounded [`quantbt_strategy_ir`]
//! programs. Arbitrary Python callbacks remain outside the worker pool. Every
//! scenario creates no market copy, runs the same [`quantbt_engine::FullSession`]
//! lifecycle, and writes a scalar row in stable input order.

use std::sync::Arc;

use quantbt_domain::ids::SymbolId;
use quantbt_engine::{FullMarketData, FullSession};
use quantbt_strategy_ir::StrategyProgram;

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
    pub market: Arc<FullMarketData>,
    pub strategy_program: Arc<StrategyProgram>,
    pub contract_sizes: Arc<[f64]>,
    pub leverages: Arc<[f64]>,
    pub fee_rates: Arc<[f64]>,
    pub initial_capital: f64,
    pub maintenance_ratio: f64,
    pub slippage: f64,
    pub use_funding: bool,
    pub event_contract_code: i64,
    closes_for_program: Arc<[f64]>,
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
        let symbol = strategy_program.symbol();
        if symbol.0 as usize >= market.n_symbols {
            return Err("strategy program symbol is outside prepared market".to_owned());
        }
        if contract_sizes.len() != market.n_symbols
            || leverages.len() != market.n_symbols
            || fee_rates.len() != market.n_symbols
        {
            return Err("batch account vectors do not match prepared market".to_owned());
        }
        let closes_for_program = (0..market.n_bars)
            .map(|bar| market.closes[bar * market.n_symbols + symbol.0 as usize])
            .collect::<Vec<_>>()
            .into();
        Ok(Self {
            market_key: SharedMarketKey {
                symbol,
                market_fingerprint: fingerprint_market(&market),
            },
            market,
            strategy_program,
            contract_sizes,
            leverages,
            fee_rates,
            initial_capital,
            maintenance_ratio,
            slippage,
            use_funding,
            event_contract_code,
            closes_for_program,
        })
    }

    pub fn from_session(
        session: &FullSession,
        strategy_program: Arc<StrategyProgram>,
    ) -> Result<Self, String> {
        Self::new(
            session.market.clone(),
            strategy_program,
            Arc::from(session.contract_sizes.to_vec()),
            Arc::from(session.leverages.to_vec()),
            Arc::from(session.fee_rates.to_vec()),
            session.initial_capital,
            session.maintenance_ratio,
            session.slippage,
            session.use_funding,
            session.event_contract_code,
        )
    }

    /// Build a one-time market window for an isolated OOS fold. This preserves
    /// zero market copies per *scenario* while making the fold/account reset
    /// explicit instead of accidentally carrying earlier fold positions.
    pub fn for_fold(&self, fold: FoldPlan) -> Result<Self, String> {
        let fold = fold.validate(self.market.n_bars)?;
        let range = fold.test_range();
        let market = Arc::new(self.market.window(range.start, range.end)?);
        Self::new(
            market,
            self.strategy_program.clone(),
            self.contract_sizes.clone(),
            self.leverages.clone(),
            self.fee_rates.clone(),
            self.initial_capital,
            self.maintenance_ratio,
            self.slippage,
            self.use_funding,
            self.event_contract_code,
        )
    }

    #[must_use]
    pub const fn market_key(&self) -> SharedMarketKey {
        self.market_key
    }

    #[must_use]
    pub fn market_bytes(&self) -> usize {
        self.market.timestamps_ns.len() * std::mem::size_of::<i64>()
            + self.market.opens.len() * std::mem::size_of::<f64>()
            + self.market.highs.len() * std::mem::size_of::<f64>()
            + self.market.lows.len() * std::mem::size_of::<f64>()
            + self.market.closes.len() * std::mem::size_of::<f64>()
            + self.market.volumes.len() * std::mem::size_of::<f64>()
            + self.market.funding.len() * std::mem::size_of::<f64>()
            + self.market.funding_mask.len() * std::mem::size_of::<bool>()
    }

    fn new_session(&self) -> Result<FullSession, String> {
        let mut session = FullSession::new(
            self.market.clone(),
            self.contract_sizes.to_vec(),
            self.leverages.to_vec(),
            self.fee_rates.to_vec(),
            self.initial_capital,
            self.maintenance_ratio,
            self.slippage,
            self.use_funding,
        )?;
        session.set_event_contract(self.event_contract_code)?;
        Ok(session)
    }

    fn validate_input(&self, input: ScenarioInput<'_>) -> Result<(), String> {
        self.strategy_program
            .compile_tape(input.signal, &self.closes_for_program, input.parameters)
            .map(|_| ())
            .map_err(|error| error.to_string())
    }

    fn run_one(&self, session: &mut FullSession, input: ScenarioInput<'_>) -> ScenarioOutcome {
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
        let tape = match self.strategy_program.compile_tape(
            input.signal,
            &self.closes_for_program,
            input.parameters,
        ) {
            Ok(tape) => tape,
            Err(error) => {
                return ScenarioOutcome {
                    score: zero,
                    status: ScenarioStatus::InvalidInput,
                    error: Some(error.to_string()),
                };
            }
        };
        session.reset();
        if let Err(error) = session.set_event_contract(self.event_contract_code) {
            return ScenarioOutcome {
                score: zero,
                status: ScenarioStatus::ExecutionError,
                error: Some(error),
            };
        }
        match session.run_typed_score(&tape) {
            Ok(output) => ScenarioOutcome {
                score: ScenarioScore {
                    scenario: input.scenario,
                    final_equity: output.final_equity,
                    total_fee: output.total_fee,
                    total_funding: output.total_funding,
                    turnover: output.total_turnover,
                    fill_count: output.fill_count.max(0) as u64,
                    rejected_count: output.rejected_count.max(0) as u64,
                    liquidated: output.liquidated,
                },
                status: ScenarioStatus::Complete,
                error: None,
            },
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
                        let mut session = template.new_session()?;
                        let mut outcomes = Vec::with_capacity(worker_inputs.len());
                        for chunk in worker_inputs.chunks(plan.chunk_size) {
                            for input in chunk {
                                outcomes.push(template.run_one(&mut session, *input));
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
        let fold = fold.validate(self.market.n_bars)?;
        if inputs
            .iter()
            .any(|input| input.signal.len() != self.market.n_bars)
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
            market_window_bytes: folded.market_bytes(),
        })
    }

    /// Re-run one selected scenario with the audit sink. The caller must use
    /// this after stable top-K selection rather than retaining audit data for
    /// every trial.
    pub fn audit_scenario(
        &self,
        input: ScenarioInput<'_>,
    ) -> Result<quantbt_engine::StaticTapeOutput, String> {
        let tape = self
            .strategy_program
            .compile_tape(input.signal, &self.closes_for_program, input.parameters)
            .map_err(|error| error.to_string())?;
        let mut session = self.new_session()?;
        session.run_typed_audit(&tape)
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
    pub market_window_bytes: usize,
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

fn fingerprint_market(market: &FullMarketData) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for timestamp in market.timestamps_ns.iter().copied() {
        hash ^= timestamp as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    for close in market.closes.iter().copied() {
        hash ^= close.to_bits();
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash ^ (market.n_symbols as u64)
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
    fn fold_batch_is_causal_and_reuses_one_oos_window_for_all_scenarios() {
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
        assert!(result.market_window_bytes > 0);
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
}
