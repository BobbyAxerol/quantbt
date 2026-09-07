//! Persistent typed prepared-evaluation runtime.
//!
//! This module deliberately owns only immutable request handles and scalar
//! score rows. Each request keeps its specialized Rust execution/accounting
//! authority, while this runtime removes the Python-per-request scheduling and
//! result-dictionary boundary from repeated candidate/fold/scenario work.

use std::cmp::Reverse;
use std::panic::{self, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use numpy::PyArray1;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyTuple};

use quantbt_engine::NativeScoreOutputV1;
use quantbt_execution as execution;

use super::{
    NativeExecutionRequestCore, NativeIntrabarRequestCore, NativeSharedPortfolioTargetRequestCore,
    NativeTargetExecutionRequestCore, intrabar_hex,
};

const STATUS_SUCCESS: u16 = 0;
const STATUS_CANCELED: u16 = 1;
const STATUS_FAILED: u16 = 2;
const ERROR_SENTINEL: u32 = u32::MAX;

static NEXT_RUNTIME_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PreparedWorkloadKind {
    StaticCommand,
    StrategyIr,
    TargetUnits,
    TargetNotional,
    TargetWeight,
    TargetEquityFraction,
    PctEquityTransition,
    PortfolioTarget,
    BoundedPackage,
    Intrabar,
}

impl PreparedWorkloadKind {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "static_command_tape" => Ok(Self::StaticCommand),
            "strategy_ir" => Ok(Self::StrategyIr),
            "target_units" => Ok(Self::TargetUnits),
            "target_notional" => Ok(Self::TargetNotional),
            "target_weight" => Ok(Self::TargetWeight),
            "target_equity_fraction" => Ok(Self::TargetEquityFraction),
            "pct_equity_transition" => Ok(Self::PctEquityTransition),
            "shared_portfolio_target" => Ok(Self::PortfolioTarget),
            "bounded_same_account_package" => Ok(Self::BoundedPackage),
            "single_symbol_intrabar" => Ok(Self::Intrabar),
            _ => Err(format!(
                "unsupported prepared evaluation workload={value:?}"
            )),
        }
    }

    const fn name(self) -> &'static str {
        match self {
            Self::StaticCommand => "static_command_tape",
            Self::StrategyIr => "strategy_ir",
            Self::TargetUnits => "target_units",
            Self::TargetNotional => "target_notional",
            Self::TargetWeight => "target_weight",
            Self::TargetEquityFraction => "target_equity_fraction",
            Self::PctEquityTransition => "pct_equity_transition",
            Self::PortfolioTarget => "shared_portfolio_target",
            Self::BoundedPackage => "bounded_same_account_package",
            Self::Intrabar => "single_symbol_intrabar",
        }
    }
}

#[derive(Clone)]
enum PreparedRequestCore {
    Execution(Arc<execution::NativeExecutionRequestV1>),
    DirectTarget(Arc<execution::target::DirectTargetRequestV1>),
    SharedPortfolio(Arc<execution::target::SharedPortfolioTargetRequestV1>),
    Intrabar(Arc<execution::intrabar::IntrabarRequestV1>),
}

#[derive(Clone)]
struct PreparedBinding {
    request: PreparedRequestCore,
    workload: PreparedWorkloadKind,
    candidate_id: u64,
    fold_id: u32,
    scenario_id: u32,
    estimated_cost: u64,
    runtime_id: u64,
    runtime_generation: u64,
    request_fingerprint: String,
}

impl PreparedBinding {
    fn request_reference_count(&self) -> usize {
        match &self.request {
            PreparedRequestCore::Execution(request) => Arc::strong_count(request),
            PreparedRequestCore::DirectTarget(request) => Arc::strong_count(request),
            PreparedRequestCore::SharedPortfolio(request) => Arc::strong_count(request),
            PreparedRequestCore::Intrabar(request) => Arc::strong_count(request),
        }
    }

    fn execute(&self) -> Result<PreparedRow, String> {
        match &self.request {
            PreparedRequestCore::Execution(request) => {
                let result = request.execute()?;
                let score = result.score();
                row_from_score(
                    self,
                    score,
                    score.event_count.max(0) as u64,
                    result.fingerprint_hex(),
                    result.header_v2.terminal_fingerprint_hex(),
                )
            }
            PreparedRequestCore::DirectTarget(request) => {
                let result = request.execute()?;
                let score = result.output.score();
                row_from_score(
                    self,
                    score,
                    result.report_trade_count,
                    result.request_fingerprint_hex(),
                    result.terminal_fingerprint_hex(),
                )
            }
            PreparedRequestCore::SharedPortfolio(request) => {
                let result = request.execute()?;
                let score = result.output.score();
                row_from_score(
                    self,
                    score,
                    score.event_count.max(0) as u64,
                    result.request_fingerprint_hex(),
                    result.terminal_fingerprint_hex(),
                )
            }
            PreparedRequestCore::Intrabar(request) => {
                let result = request.execute();
                row_from_intrabar(
                    self,
                    &result,
                    intrabar_hex(result.request_fingerprint),
                    intrabar_hex(result.terminal_fingerprint),
                )
            }
        }
    }
}

#[derive(Clone, Debug)]
struct PreparedRow {
    candidate_id: u64,
    fold_id: u32,
    scenario_id: u32,
    status: u16,
    final_equity: f64,
    total_fee: f64,
    total_funding: f64,
    turnover: f64,
    total_return: f64,
    sharpe: f64,
    sortino: f64,
    max_drawdown: f64,
    cagr: f64,
    calmar: f64,
    omega: f64,
    profit_factor: f64,
    average_gross_exposure: f64,
    native_metric_contract_version: u16,
    native_metric_annualization_factor: f64,
    fill_count: u64,
    report_trade_count: u64,
    event_count: u64,
    rejected_count: u64,
    canceled_count: u64,
    sample_count: u64,
    liquidated: bool,
    request_fingerprint: String,
    terminal_fingerprint: String,
    error_slot: u32,
}

impl PreparedRow {
    fn canceled(binding: &PreparedBinding) -> Self {
        Self::empty(binding, STATUS_CANCELED)
    }

    fn failed(binding: &PreparedBinding) -> Self {
        Self::empty(binding, STATUS_FAILED)
    }

    fn empty(binding: &PreparedBinding, status: u16) -> Self {
        Self {
            candidate_id: binding.candidate_id,
            fold_id: binding.fold_id,
            scenario_id: binding.scenario_id,
            status,
            final_equity: f64::NAN,
            total_fee: f64::NAN,
            total_funding: f64::NAN,
            turnover: f64::NAN,
            total_return: f64::NAN,
            sharpe: f64::NAN,
            sortino: f64::NAN,
            max_drawdown: f64::NAN,
            cagr: f64::NAN,
            calmar: f64::NAN,
            omega: f64::NAN,
            profit_factor: f64::NAN,
            average_gross_exposure: f64::NAN,
            native_metric_contract_version: 0,
            native_metric_annualization_factor: f64::NAN,
            fill_count: 0,
            report_trade_count: 0,
            event_count: 0,
            rejected_count: 0,
            canceled_count: 0,
            sample_count: 0,
            liquidated: false,
            request_fingerprint: binding.request_fingerprint.clone(),
            terminal_fingerprint: String::new(),
            error_slot: ERROR_SENTINEL,
        }
    }
}

fn close_enough(left: f64, right: f64) -> bool {
    (left - right).abs() <= 1.0e-10 * left.abs().max(right.abs()).max(1.0)
}

fn row_from_score(
    binding: &PreparedBinding,
    score: &NativeScoreOutputV1,
    report_trade_count: u64,
    request_fingerprint: String,
    terminal_fingerprint: String,
) -> Result<PreparedRow, String> {
    let metrics = *score.metrics_v2;
    if metrics.metric_contract_version != 2 {
        return Err(format!(
            "prepared native score requires MetricContractV2, got version={}",
            metrics.metric_contract_version
        ));
    }
    if !close_enough(score.metric_contract.annualization_factor, 365.0) {
        return Err(format!(
            "prepared native score supports the crypto-daily MetricContractV2 only, got annualization_factor={}",
            score.metric_contract.annualization_factor
        ));
    }
    if !close_enough(metrics.final_equity, score.final_equity)
        || !close_enough(metrics.turnover, score.total_turnover)
        || !close_enough(metrics.total_fee, score.total_fee)
        || !close_enough(metrics.total_funding, score.total_funding)
        || metrics.fill_count != score.fill_count.max(0) as u64
        || metrics.event_count != score.event_count.max(0) as u64
        || metrics.rejected_count != score.rejected_count.max(0) as u64
        || metrics.canceled_count != score.canceled_count.max(0) as u64
        || metrics.liquidated != score.liquidated
    {
        return Err("prepared native score metric/accounting reconciliation failed".to_owned());
    }
    Ok(PreparedRow {
        candidate_id: binding.candidate_id,
        fold_id: binding.fold_id,
        scenario_id: binding.scenario_id,
        status: STATUS_SUCCESS,
        final_equity: score.final_equity,
        total_fee: score.total_fee,
        total_funding: score.total_funding,
        turnover: score.total_turnover,
        total_return: metrics.total_return,
        sharpe: metrics.sharpe,
        sortino: metrics.sortino,
        max_drawdown: metrics.max_drawdown,
        cagr: metrics.cagr,
        calmar: metrics.calmar,
        omega: metrics.omega,
        profit_factor: metrics.profit_factor,
        average_gross_exposure: metrics.average_gross_exposure,
        native_metric_contract_version: metrics.metric_contract_version,
        native_metric_annualization_factor: score.metric_contract.annualization_factor,
        fill_count: metrics.fill_count,
        report_trade_count,
        event_count: metrics.event_count,
        rejected_count: metrics.rejected_count,
        canceled_count: metrics.canceled_count,
        sample_count: metrics.sample_count,
        liquidated: metrics.liquidated,
        request_fingerprint,
        terminal_fingerprint,
        error_slot: ERROR_SENTINEL,
    })
}

fn row_from_intrabar(
    binding: &PreparedBinding,
    result: &execution::intrabar::IntrabarExecutionResultV1,
    request_fingerprint: String,
    terminal_fingerprint: String,
) -> Result<PreparedRow, String> {
    let metrics = result.metrics;
    let event_count = result.fill_count.saturating_add(result.rejected_count);
    if metrics.metric_contract_version != 2
        || !close_enough(result.metric_contract.annualization_factor, 365.0)
        || !close_enough(metrics.final_equity, result.final_equity)
        || !close_enough(metrics.turnover, result.total_turnover)
        || !close_enough(metrics.total_fee, result.total_fee)
        || !close_enough(metrics.total_funding, result.total_funding)
        || metrics.fill_count != result.fill_count
        || metrics.event_count != event_count
        || metrics.rejected_count != result.rejected_count
        || metrics.canceled_count != 0
        || metrics.liquidated != result.liquidated
    {
        return Err("prepared intrabar metric/accounting reconciliation failed".to_owned());
    }
    Ok(PreparedRow {
        candidate_id: binding.candidate_id,
        fold_id: binding.fold_id,
        scenario_id: binding.scenario_id,
        status: STATUS_SUCCESS,
        final_equity: result.final_equity,
        total_fee: result.total_fee,
        total_funding: result.total_funding,
        turnover: result.total_turnover,
        total_return: metrics.total_return,
        sharpe: metrics.sharpe,
        sortino: metrics.sortino,
        max_drawdown: metrics.max_drawdown,
        cagr: metrics.cagr,
        calmar: metrics.calmar,
        omega: metrics.omega,
        profit_factor: metrics.profit_factor,
        average_gross_exposure: metrics.average_gross_exposure,
        native_metric_contract_version: metrics.metric_contract_version,
        native_metric_annualization_factor: result.metric_contract.annualization_factor,
        fill_count: metrics.fill_count,
        report_trade_count: metrics.event_count,
        event_count: metrics.event_count,
        rejected_count: metrics.rejected_count,
        canceled_count: metrics.canceled_count,
        sample_count: metrics.sample_count,
        liquidated: metrics.liquidated,
        request_fingerprint,
        terminal_fingerprint,
        error_slot: ERROR_SENTINEL,
    })
}

struct WorkerTask {
    binding: PreparedBinding,
    response: Sender<WorkerOutcome>,
}

enum WorkerMessage {
    Execute(WorkerTask),
    Shutdown,
}

struct WorkerOutcome {
    row: PreparedRow,
    error: Option<String>,
}

struct PreparedRuntimeState {
    runtime_id: u64,
    generation: AtomicU64,
    workers: usize,
    max_metric_rows: usize,
    max_error_rows: usize,
    sender: Mutex<Option<Sender<WorkerMessage>>>,
    worker_handles: Mutex<Vec<JoinHandle<()>>>,
    active: AtomicBool,
    canceled: AtomicBool,
    closed: AtomicBool,
    poisoned: AtomicBool,
    native_entry_calls: AtomicU64,
    failed_rows: AtomicU64,
    worker_pool_creations: AtomicU64,
    poison_recoveries: AtomicU64,
    score_batches: AtomicU64,
}

impl PreparedRuntimeState {
    fn new(
        workers: usize,
        max_metric_rows: usize,
        max_error_rows: usize,
    ) -> Result<Arc<Self>, String> {
        if workers == 0 || max_metric_rows == 0 || max_error_rows == 0 {
            return Err("prepared evaluation workers and bounds must be positive".to_owned());
        }
        let state = Arc::new(Self {
            runtime_id: NEXT_RUNTIME_ID.fetch_add(1, Ordering::Relaxed),
            generation: AtomicU64::new(1),
            workers,
            max_metric_rows,
            max_error_rows,
            sender: Mutex::new(None),
            worker_handles: Mutex::new(Vec::with_capacity(workers)),
            active: AtomicBool::new(false),
            canceled: AtomicBool::new(false),
            closed: AtomicBool::new(false),
            poisoned: AtomicBool::new(false),
            native_entry_calls: AtomicU64::new(0),
            failed_rows: AtomicU64::new(0),
            worker_pool_creations: AtomicU64::new(0),
            poison_recoveries: AtomicU64::new(0),
            score_batches: AtomicU64::new(0),
        });
        state.start_workers()?;
        Ok(state)
    }

    fn start_workers(self: &Arc<Self>) -> Result<(), String> {
        let (sender, receiver) = mpsc::channel::<WorkerMessage>();
        let receiver = Arc::new(Mutex::new(receiver));
        let mut handles = Vec::with_capacity(self.workers);
        for worker_index in 0..self.workers {
            let receiver = receiver.clone();
            let state_for_worker = self.clone();
            let handle = thread::Builder::new()
                .name(format!("quantbt-prepared-eval-{worker_index}"))
                .spawn(move || worker_loop(receiver, state_for_worker))
                .map_err(|error| format!("failed to create prepared evaluation worker: {error}"))?;
            handles.push(handle);
        }
        *self
            .sender
            .lock()
            .map_err(|_| "prepared runtime sender lock poisoned")? = Some(sender);
        *self
            .worker_handles
            .lock()
            .map_err(|_| "prepared runtime worker lock poisoned")? = handles;
        self.worker_pool_creations.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    fn stop_workers(&self) -> Result<(), String> {
        let sender = self
            .sender
            .lock()
            .map_err(|_| "prepared runtime sender lock poisoned")?
            .take();
        if let Some(sender) = sender {
            for _ in 0..self.workers {
                let _ = sender.send(WorkerMessage::Shutdown);
            }
        }
        let handles = std::mem::take(
            &mut *self
                .worker_handles
                .lock()
                .map_err(|_| "prepared runtime worker lock poisoned")?,
        );
        for handle in handles {
            handle
                .join()
                .map_err(|_| "prepared evaluation worker terminated unexpectedly".to_owned())?;
        }
        Ok(())
    }

    fn recover_workers(self: &Arc<Self>) -> Result<(), String> {
        self.stop_workers()?;
        self.start_workers()?;
        self.poisoned.store(false, Ordering::Release);
        self.poison_recoveries.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    fn ensure_open(&self) -> Result<(), String> {
        if self.closed.load(Ordering::Acquire) {
            return Err("prepared evaluation runtime is closed".to_owned());
        }
        Ok(())
    }

    fn close(&self) -> Result<(), String> {
        if self.active.load(Ordering::Acquire) {
            return Err(
                "cannot close a prepared evaluation runtime while work is active".to_owned(),
            );
        }
        if self.closed.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        self.stop_workers()
    }
}

fn worker_loop(receiver: Arc<Mutex<Receiver<WorkerMessage>>>, state: Arc<PreparedRuntimeState>) {
    loop {
        let message = match receiver.lock() {
            Ok(guard) => guard.recv(),
            Err(_) => return,
        };
        let Ok(message) = message else {
            return;
        };
        match message {
            WorkerMessage::Shutdown => return,
            WorkerMessage::Execute(task) => {
                let WorkerTask { binding, response } = task;
                let outcome = if state.canceled.load(Ordering::Acquire) {
                    WorkerOutcome {
                        row: PreparedRow::canceled(&binding),
                        error: None,
                    }
                } else {
                    state.native_entry_calls.fetch_add(1, Ordering::Relaxed);
                    match panic::catch_unwind(AssertUnwindSafe(|| binding.execute())) {
                        Ok(Ok(row)) => WorkerOutcome { row, error: None },
                        Ok(Err(error)) => WorkerOutcome {
                            row: PreparedRow::failed(&binding),
                            error: Some(error),
                        },
                        Err(_) => {
                            state.poisoned.store(true, Ordering::Release);
                            WorkerOutcome {
                                row: PreparedRow::failed(&binding),
                                error: Some(
                                    "InternalInvariantFailure: native prepared worker panicked"
                                        .to_owned(),
                                ),
                            }
                        }
                    }
                };
                // The result owns no request state. Drop the worker's temporary
                // Arc before waking the receiver so ownership diagnostics have
                // a deterministic post-batch value.
                drop(binding);
                let _ = response.send(outcome);
            }
        }
    }
}

/// Native immutable binding for one candidate/fold/scenario request.
#[pyclass]
pub(crate) struct NativePreparedEvaluationBindingCore {
    inner: PreparedBinding,
}

#[pymethods]
impl NativePreparedEvaluationBindingCore {
    #[getter]
    fn candidate_id(&self) -> u64 {
        self.inner.candidate_id
    }

    #[getter]
    fn fold_id(&self) -> u32 {
        self.inner.fold_id
    }

    #[getter]
    fn scenario_id(&self) -> u32 {
        self.inner.scenario_id
    }

    #[getter]
    fn workload(&self) -> &'static str {
        self.inner.workload.name()
    }

    #[getter]
    fn runtime_id(&self) -> u64 {
        self.inner.runtime_id
    }

    #[getter]
    fn runtime_generation(&self) -> u64 {
        self.inner.runtime_generation
    }

    #[getter]
    fn request_fingerprint(&self) -> String {
        self.inner.request_fingerprint.clone()
    }

    #[getter]
    fn request_reference_count(&self) -> usize {
        self.inner.request_reference_count()
    }
}

/// Rust-owned prepared runtime. It owns a persistent task pool only; immutable
/// request handles remain separately content-addressed by the Python cache.
#[pyclass]
pub(crate) struct NativePreparedEvaluationRuntimeCore {
    inner: Arc<PreparedRuntimeState>,
}

impl Drop for NativePreparedEvaluationRuntimeCore {
    fn drop(&mut self) {
        let _ = self.inner.close();
    }
}

#[pymethods]
impl NativePreparedEvaluationRuntimeCore {
    #[new]
    #[pyo3(signature = (workers=1, max_metric_rows=1_000_000, max_error_rows=64))]
    fn new(workers: usize, max_metric_rows: usize, max_error_rows: usize) -> PyResult<Self> {
        PreparedRuntimeState::new(workers, max_metric_rows, max_error_rows)
            .map(|inner| Self { inner })
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[getter]
    fn runtime_id(&self) -> u64 {
        self.inner.runtime_id
    }

    #[getter]
    fn generation(&self) -> u64 {
        self.inner.generation.load(Ordering::Acquire)
    }

    #[getter]
    fn workers(&self) -> usize {
        self.inner.workers
    }

    #[getter]
    fn closed(&self) -> bool {
        self.inner.closed.load(Ordering::Acquire)
    }

    #[pyo3(signature = (request, workload, candidate_id=0, fold_id=0, scenario_id=0, estimated_cost=1))]
    fn bind(
        &self,
        request: &Bound<'_, PyAny>,
        workload: &str,
        candidate_id: u64,
        fold_id: u32,
        scenario_id: u32,
        estimated_cost: u64,
    ) -> PyResult<NativePreparedEvaluationBindingCore> {
        self.inner
            .ensure_open()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        if estimated_cost == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "prepared evaluation estimated_cost must be positive",
            ));
        }
        let workload = PreparedWorkloadKind::parse(workload)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let (request, fingerprint) = request_from_python(request, workload)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(NativePreparedEvaluationBindingCore {
            inner: PreparedBinding {
                request,
                workload,
                candidate_id,
                fold_id,
                scenario_id,
                estimated_cost,
                runtime_id: self.inner.runtime_id,
                runtime_generation: self.inner.generation.load(Ordering::Acquire),
                request_fingerprint: fingerprint,
            },
        })
    }

    fn execute_score(
        &self,
        py: Python<'_>,
        bindings: Vec<PyRef<'_, NativePreparedEvaluationBindingCore>>,
    ) -> PyResult<NativePreparedEvaluationMatrixCore> {
        self.inner
            .ensure_open()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        if bindings.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "prepared evaluation requires at least one binding",
            ));
        }
        if bindings.len() > self.inner.max_metric_rows {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
                "runtime budget exceeded: {} metric rows requested, limit={}",
                bindings.len(),
                self.inner.max_metric_rows
            )));
        }
        if self
            .inner
            .active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "prepared evaluation runtime already has an active batch",
            ));
        }
        let prepared = bindings
            .iter()
            .map(|binding| binding.inner.clone())
            .collect::<Vec<_>>();
        let runtime = self.inner.clone();
        let matrix = py.detach(move || execute_batch(runtime, prepared));
        self.inner.active.store(false, Ordering::Release);
        matrix
            .map(|inner| NativePreparedEvaluationMatrixCore { inner })
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    fn cancel(&self) {
        self.inner.canceled.store(true, Ordering::Release);
    }

    fn reset(&self) -> PyResult<()> {
        self.inner
            .ensure_open()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)?;
        if self.inner.active.load(Ordering::Acquire) {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "cannot reset a prepared evaluation runtime while work is active",
            ));
        }
        self.inner.canceled.store(false, Ordering::Release);
        self.inner.generation.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    fn close(&self) -> PyResult<()> {
        self.inner
            .close()
            .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    fn diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        payload.set_item("runtime", "native_prepared_evaluation_core_v1")?;
        payload.set_item("runtime_id", self.inner.runtime_id)?;
        payload.set_item(
            "runtime_generation",
            self.inner.generation.load(Ordering::Acquire),
        )?;
        payload.set_item("workers", self.inner.workers)?;
        payload.set_item("closed", self.inner.closed.load(Ordering::Acquire))?;
        payload.set_item(
            "active_batches",
            if self.inner.active.load(Ordering::Acquire) {
                1usize
            } else {
                0usize
            },
        )?;
        payload.set_item(
            "worker_pool_creations",
            self.inner.worker_pool_creations.load(Ordering::Relaxed),
        )?;
        payload.set_item(
            "score_batches",
            self.inner.score_batches.load(Ordering::Relaxed),
        )?;
        payload.set_item(
            "native_entry_calls",
            self.inner.native_entry_calls.load(Ordering::Relaxed),
        )?;
        payload.set_item(
            "failed_rows",
            self.inner.failed_rows.load(Ordering::Relaxed),
        )?;
        payload.set_item("poisoned", self.inner.poisoned.load(Ordering::Acquire))?;
        payload.set_item(
            "poison_recoveries",
            self.inner.poison_recoveries.load(Ordering::Relaxed),
        )?;
        payload.set_item("canceled", self.inner.canceled.load(Ordering::Acquire))?;
        Ok(payload.unbind())
    }
}

fn request_from_python(
    request: &Bound<'_, PyAny>,
    workload: PreparedWorkloadKind,
) -> Result<(PreparedRequestCore, String), String> {
    if let Ok(request) = request.extract::<PyRef<'_, NativeExecutionRequestCore>>() {
        let kind = request.inner.workload_kind().name();
        let accepted = match workload {
            PreparedWorkloadKind::StaticCommand => kind == "command_tape_v5",
            PreparedWorkloadKind::StrategyIr => kind == "strategy_ir_v1",
            PreparedWorkloadKind::PortfolioTarget => kind == "portfolio_target_market_v1",
            PreparedWorkloadKind::BoundedPackage => {
                matches!(kind, "package_atomic_market_v1" | "package_market_v2")
            }
            _ => false,
        };
        if !accepted {
            return Err(format!(
                "prepared evaluation workload={} cannot bind native request workload={kind}",
                workload.name()
            ));
        }
        return Ok((
            PreparedRequestCore::Execution(request.inner.clone()),
            request.inner.fingerprint_hex(),
        ));
    }
    if let Ok(request) = request.extract::<PyRef<'_, NativeTargetExecutionRequestCore>>() {
        let kind = request.inner.kind().name();
        let accepted = matches!(
            (workload, kind),
            (PreparedWorkloadKind::TargetUnits, "target_units_v1")
                | (PreparedWorkloadKind::TargetNotional, "target_notional_v1")
                | (PreparedWorkloadKind::TargetWeight, "target_weight_v1")
                | (
                    PreparedWorkloadKind::TargetEquityFraction,
                    "equity_fraction_v1"
                )
                | (
                    PreparedWorkloadKind::PctEquityTransition,
                    "pct_equity_transition_v1"
                )
        );
        if !accepted {
            return Err(format!(
                "prepared evaluation workload={} cannot bind direct target kind={kind}",
                workload.name()
            ));
        }
        return Ok((
            PreparedRequestCore::DirectTarget(request.inner.clone()),
            request.inner.fingerprint_hex(),
        ));
    }
    if let Ok(request) = request.extract::<PyRef<'_, NativeSharedPortfolioTargetRequestCore>>() {
        if workload != PreparedWorkloadKind::PortfolioTarget {
            return Err(format!(
                "prepared evaluation workload={} cannot bind a shared portfolio target request",
                workload.name()
            ));
        }
        return Ok((
            PreparedRequestCore::SharedPortfolio(request.inner.clone()),
            request.inner.fingerprint_hex(),
        ));
    }
    if let Ok(request) = request.extract::<PyRef<'_, NativeIntrabarRequestCore>>() {
        if workload != PreparedWorkloadKind::Intrabar {
            return Err(format!(
                "prepared evaluation workload={} cannot bind an intrabar request",
                workload.name()
            ));
        }
        return Ok((
            PreparedRequestCore::Intrabar(request.inner.clone()),
            request.inner.fingerprint_hex(),
        ));
    }
    Err("prepared evaluation request must be a certified native request core".to_owned())
}

fn execute_batch(
    runtime: Arc<PreparedRuntimeState>,
    mut bindings: Vec<PreparedBinding>,
) -> Result<PreparedEvaluationMatrix, String> {
    let generation = runtime.generation.load(Ordering::Acquire);
    for binding in &bindings {
        if binding.runtime_id != runtime.runtime_id {
            return Err("prepared evaluation binding belongs to a different runtime".to_owned());
        }
        if binding.runtime_generation != generation {
            return Err(
                "prepared evaluation binding belongs to an earlier runtime generation".to_owned(),
            );
        }
    }
    bindings.sort_by_key(|binding| {
        (
            Reverse(binding.estimated_cost),
            binding.candidate_id,
            binding.fold_id,
            binding.scenario_id,
        )
    });
    let sender = runtime
        .sender
        .lock()
        .map_err(|_| "prepared runtime sender lock poisoned")?
        .clone()
        .ok_or_else(|| "prepared evaluation runtime is closed".to_owned())?;
    let row_count = bindings.len();
    let (response_sender, response_receiver) = mpsc::channel::<WorkerOutcome>();
    for binding in bindings {
        sender
            .send(WorkerMessage::Execute(WorkerTask {
                binding,
                response: response_sender.clone(),
            }))
            .map_err(|_| "prepared evaluation worker pool is unavailable".to_owned())?;
    }
    drop(response_sender);
    runtime.score_batches.fetch_add(1, Ordering::Relaxed);
    let mut outcomes = Vec::with_capacity(row_count);
    for _ in 0..row_count {
        outcomes.push(
            response_receiver.recv().map_err(|_| {
                "prepared evaluation worker exited before returning a row".to_owned()
            })?,
        );
    }
    if runtime.poisoned.swap(false, Ordering::AcqRel)
        && let Err(error) = runtime.recover_workers()
    {
        runtime.closed.store(true, Ordering::Release);
        return Err(format!(
            "prepared evaluation worker recovery failed; runtime closed: {error}"
        ));
    }
    outcomes.sort_by_key(|outcome| {
        (
            outcome.row.candidate_id,
            outcome.row.fold_id,
            outcome.row.scenario_id,
        )
    });
    let mut errors = Vec::new();
    let mut rows = Vec::with_capacity(outcomes.len());
    for mut outcome in outcomes {
        if outcome.row.status == STATUS_FAILED {
            runtime.failed_rows.fetch_add(1, Ordering::Relaxed);
            if errors.len() < runtime.max_error_rows {
                outcome.row.error_slot = errors.len() as u32;
                errors.push(outcome.error.unwrap_or_else(|| {
                    "InternalInvariantFailure: native prepared request failed without detail"
                        .to_owned()
                }));
            }
        }
        rows.push(outcome.row);
    }
    Ok(PreparedEvaluationMatrix { rows, errors })
}

struct PreparedEvaluationMatrix {
    rows: Vec<PreparedRow>,
    errors: Vec<String>,
}

/// Typed scalar SoA output from a complete prepared evaluation batch.
#[pyclass]
pub(crate) struct NativePreparedEvaluationMatrixCore {
    inner: PreparedEvaluationMatrix,
}

#[pymethods]
impl NativePreparedEvaluationMatrixCore {
    #[getter]
    fn rows(&self) -> usize {
        self.inner.rows.len()
    }

    fn as_dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        payload.set_item(
            "candidate_id",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.candidate_id).collect(),
            ),
        )?;
        payload.set_item(
            "fold_id",
            PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.fold_id).collect()),
        )?;
        payload.set_item(
            "scenario_id",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.scenario_id).collect(),
            ),
        )?;
        payload.set_item(
            "status",
            PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.status).collect()),
        )?;
        macro_rules! float_column {
            ($name:literal, $field:ident) => {
                payload.set_item(
                    $name,
                    PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.$field).collect()),
                )?;
            };
        }
        float_column!("final_equity", final_equity);
        float_column!("total_fee", total_fee);
        float_column!("total_funding", total_funding);
        float_column!("turnover", turnover);
        float_column!("total_return", total_return);
        float_column!("sharpe", sharpe);
        float_column!("sortino", sortino);
        float_column!("max_drawdown", max_drawdown);
        float_column!("cagr", cagr);
        float_column!("calmar", calmar);
        float_column!("omega", omega);
        float_column!("profit_factor", profit_factor);
        float_column!("average_gross_exposure", average_gross_exposure);
        payload.set_item(
            "native_metric_contract_version",
            PyArray1::from_vec(
                py,
                self.inner
                    .rows
                    .iter()
                    .map(|row| row.native_metric_contract_version)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "native_metric_annualization_factor",
            PyArray1::from_vec(
                py,
                self.inner
                    .rows
                    .iter()
                    .map(|row| row.native_metric_annualization_factor)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "fill_count",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.fill_count).collect(),
            ),
        )?;
        payload.set_item(
            "report_trade_count",
            PyArray1::from_vec(
                py,
                self.inner
                    .rows
                    .iter()
                    .map(|row| row.report_trade_count)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "event_count",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.event_count).collect(),
            ),
        )?;
        payload.set_item(
            "rejected_count",
            PyArray1::from_vec(
                py,
                self.inner
                    .rows
                    .iter()
                    .map(|row| row.rejected_count)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "canceled_count",
            PyArray1::from_vec(
                py,
                self.inner
                    .rows
                    .iter()
                    .map(|row| row.canceled_count)
                    .collect(),
            ),
        )?;
        payload.set_item(
            "sample_count",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.sample_count).collect(),
            ),
        )?;
        payload.set_item(
            "liquidated",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.liquidated).collect(),
            ),
        )?;
        payload.set_item(
            "request_fingerprint",
            self.inner
                .rows
                .iter()
                .map(|row| row.request_fingerprint.clone())
                .collect::<Vec<_>>(),
        )?;
        payload.set_item(
            "terminal_fingerprint",
            self.inner
                .rows
                .iter()
                .map(|row| row.terminal_fingerprint.clone())
                .collect::<Vec<_>>(),
        )?;
        payload.set_item(
            "error_slot",
            PyArray1::from_vec(
                py,
                self.inner.rows.iter().map(|row| row.error_slot).collect(),
            ),
        )?;
        payload.set_item("errors", self.inner.errors.clone())?;
        Ok(payload.unbind())
    }

    /// Return only the scalar columns needed by hot WFO candidate scoring.
    ///
    /// This intentionally avoids the legacy ``as_dict`` compatibility path,
    /// its string provenance columns and per-row Python adaptation.  The
    /// complete matrix remains available through ``as_dict`` for audit and
    /// compatibility callers.
    fn score_columns(&self, py: Python<'_>) -> PyResult<Py<PyTuple>> {
        Ok(PyTuple::new(
            py,
            [
                PyArray1::from_vec(
                    py,
                    self.inner.rows.iter().map(|row| row.candidate_id).collect(),
                )
                .into_any()
                .unbind(),
                PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.fold_id).collect())
                    .into_any()
                    .unbind(),
                PyArray1::from_vec(
                    py,
                    self.inner.rows.iter().map(|row| row.scenario_id).collect(),
                )
                .into_any()
                .unbind(),
                PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.status).collect())
                    .into_any()
                    .unbind(),
                PyArray1::from_vec(
                    py,
                    self.inner.rows.iter().map(|row| row.total_return).collect(),
                )
                .into_any()
                .unbind(),
                PyArray1::from_vec(py, self.inner.rows.iter().map(|row| row.sharpe).collect())
                    .into_any()
                    .unbind(),
                PyArray1::from_vec(
                    py,
                    self.inner.rows.iter().map(|row| row.max_drawdown).collect(),
                )
                .into_any()
                .unbind(),
                PyArray1::from_vec(
                    py,
                    self.inner
                        .rows
                        .iter()
                        .map(|row| row.profit_factor)
                        .collect(),
                )
                .into_any()
                .unbind(),
                PyArray1::from_vec(
                    py,
                    self.inner
                        .rows
                        .iter()
                        .map(|row| row.report_trade_count)
                        .collect(),
                )
                .into_any()
                .unbind(),
                PyArray1::from_vec(
                    py,
                    self.inner.rows.iter().map(|row| row.error_slot).collect(),
                )
                .into_any()
                .unbind(),
            ],
        )?
        .unbind())
    }

    fn errors(&self) -> Vec<String> {
        self.inner.errors.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn poison_recovery_rebuilds_workers_before_the_next_batch() {
        let runtime = PreparedRuntimeState::new(2, 8, 4).expect("runtime must start");
        assert_eq!(runtime.worker_pool_creations.load(Ordering::Relaxed), 1);
        runtime.poisoned.store(true, Ordering::Release);
        runtime
            .recover_workers()
            .expect("poison recovery must rebuild workers");
        assert!(!runtime.poisoned.load(Ordering::Acquire));
        assert_eq!(runtime.worker_pool_creations.load(Ordering::Relaxed), 2);
        assert_eq!(runtime.poison_recoveries.load(Ordering::Relaxed), 1);
        runtime
            .close()
            .expect("runtime close must join rebuilt workers");
    }
}
