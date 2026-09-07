//! Prepared direct-target walk-forward execution.
//!
//! This is intentionally separate from the Strategy-IR WFO runtime. A target
//! matrix is already a typed research output, so lowering it to a signal or a
//! generic command tape would introduce a second execution authority. The
//! runtime owns an immutable market/template, causal fold windows, target
//! ingress, and native direct-delta execution only.

use std::collections::BTreeSet;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use quantbt_execution::target::{
    DirectTargetKindV1, DirectTargetRequestV1, InvalidTargetPolicyV1, PortfolioAdmissionPolicyV1,
    SharedPortfolioTargetRequestV1, TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE,
};
use quantbt_execution::{NativeExecutionTemplateV1, NativeOutputProfileV1};

use super::{
    CandidateStatusCodeV2, FoldPlan, NativeWfoMetricMatrixV2, RuntimeBudgetV1, StableFingerprint,
    WfoCandidateMetricRowV2, WfoErrorTable, hex_bytes,
};

/// Version for the prepared direct-target WFO runtime.
pub const NATIVE_TARGET_WFO_RUNTIME_VERSION_V1: u16 = 1;

/// Immutable target matrix batch owned by Rust after one Python ingress.
///
/// Shared batches use `(candidates, bars, symbols)`. Per-fold batches use
/// `(folds, candidates, bars, symbols)`. Both preserve full parent-tape
/// alignment; only each fold's declared OOS local view is executed.
#[derive(Clone)]
pub struct PreparedWfoTargetBatchV1 {
    candidate_ids: Arc<[u64]>,
    values: Arc<[f64]>,
    rows: usize,
    bars: usize,
    symbols: usize,
    fold_count: usize,
    per_fold: bool,
    fingerprint: [u8; 32],
    ingest_bytes: usize,
}

impl PreparedWfoTargetBatchV1 {
    pub fn shared(
        candidate_ids: Vec<u64>,
        values: Vec<f64>,
        bars: usize,
        symbols: usize,
    ) -> Result<Self, String> {
        Self::new(candidate_ids, values, bars, symbols, 1, false)
    }

    pub fn per_fold(
        candidate_ids: Vec<u64>,
        values: Vec<f64>,
        bars: usize,
        symbols: usize,
        fold_count: usize,
    ) -> Result<Self, String> {
        Self::new(candidate_ids, values, bars, symbols, fold_count, true)
    }

    fn new(
        candidate_ids: Vec<u64>,
        values: Vec<f64>,
        bars: usize,
        symbols: usize,
        fold_count: usize,
        per_fold: bool,
    ) -> Result<Self, String> {
        if candidate_ids.is_empty() || bars == 0 || symbols == 0 || fold_count == 0 {
            return Err("prepared WFO target batch dimensions must be non-zero".to_owned());
        }
        let rows = candidate_ids.len();
        let matrices = if per_fold { fold_count } else { 1 };
        let expected = matrices
            .checked_mul(rows)
            .and_then(|value| value.checked_mul(bars))
            .and_then(|value| value.checked_mul(symbols))
            .ok_or_else(|| "prepared WFO target matrix size overflow".to_owned())?;
        if values.len() != expected || values.iter().any(|value| !value.is_finite()) {
            return Err(
                "prepared WFO target matrix has an invalid shape or non-finite value".to_owned(),
            );
        }
        let mut unique = BTreeSet::new();
        if candidate_ids
            .iter()
            .any(|candidate| !unique.insert(*candidate))
        {
            return Err("prepared WFO target candidate IDs must be unique".to_owned());
        }
        let mut writer = StableFingerprint::new(b"quantbt-prepared-wfo-target-v1");
        writer.usize(rows);
        writer.usize(bars);
        writer.usize(symbols);
        writer.usize(fold_count);
        writer.u8(u8::from(per_fold));
        for candidate in &candidate_ids {
            writer.u64(*candidate);
        }
        for value in &values {
            writer.f64(*value);
        }
        let fingerprint = writer.finish();
        let ingest_bytes = values
            .len()
            .saturating_mul(std::mem::size_of::<f64>())
            .saturating_add(
                candidate_ids
                    .len()
                    .saturating_mul(std::mem::size_of::<u64>()),
            );
        Ok(Self {
            candidate_ids: candidate_ids.into(),
            values: values.into(),
            rows,
            bars,
            symbols,
            fold_count,
            per_fold,
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
    pub const fn symbols(&self) -> usize {
        self.symbols
    }

    #[must_use]
    pub const fn fold_count(&self) -> usize {
        self.fold_count
    }

    #[must_use]
    pub const fn is_per_fold(&self) -> bool {
        self.per_fold
    }

    #[must_use]
    pub const fn ingest_bytes(&self) -> usize {
        self.ingest_bytes
    }

    #[must_use]
    pub fn fingerprint(&self) -> [u8; 32] {
        self.fingerprint
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        hex_bytes(&self.fingerprint)
    }

    fn candidate_id(&self, candidate_index: usize) -> u64 {
        self.candidate_ids[candidate_index]
    }

    fn target(&self, fold_index: usize, candidate_index: usize) -> &[f64] {
        let matrix = if self.per_fold { fold_index } else { 0 };
        let width = self.bars * self.symbols;
        let start = (matrix * self.rows + candidate_index) * width;
        &self.values[start..start + width]
    }
}

/// Immutable direct-target WFO plan. Its fold templates are zero-copy views of
/// the shared Rust market owner; no candidate owns a market or account state.
#[derive(Clone)]
pub struct NativeTargetWfoPlanV1 {
    base_template: Arc<NativeExecutionTemplateV1>,
    fold_templates: Arc<[Arc<NativeExecutionTemplateV1>]>,
    folds: Arc<[FoldPlan]>,
    kind: DirectTargetKindV1,
    timing: u8,
    invalid_target_policy: InvalidTargetPolicyV1,
    tradable: Arc<[bool]>,
    stale: Arc<[bool]>,
    qty_step: Arc<[f64]>,
    min_qty: Arc<[f64]>,
    min_notional: Arc<[f64]>,
    equity_fraction: Arc<[f64]>,
    /// `None` preserves the single-symbol direct-target contract. A policy
    /// selects the explicit shared-account portfolio executor and permits a
    /// multi-symbol prepared target matrix without a second Python bridge.
    admission_policy: Option<PortfolioAdmissionPolicyV1>,
    budget: RuntimeBudgetV1,
    fingerprint: [u8; 32],
}

impl NativeTargetWfoPlanV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        base_template: Arc<NativeExecutionTemplateV1>,
        folds: Vec<FoldPlan>,
        kind: DirectTargetKindV1,
        timing: u8,
        invalid_target_policy: InvalidTargetPolicyV1,
        tradable: Vec<bool>,
        stale: Vec<bool>,
        qty_step: Vec<f64>,
        min_qty: Vec<f64>,
        min_notional: Vec<f64>,
        equity_fraction: Vec<f64>,
        admission_policy: Option<PortfolioAdmissionPolicyV1>,
        budget: RuntimeBudgetV1,
    ) -> Result<Self, String> {
        let budget = budget.validate()?;
        if timing != TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE {
            return Err(
                "native target WFO currently certifies only close_target_v2_same_close".to_owned(),
            );
        }
        // WFO optimization must fail before objective comparison when a target
        // row is invalid. Hold/skip/flatten policies have explicit direct-run
        // contracts but are intentionally not mixed into certified selection.
        if invalid_target_policy != InvalidTargetPolicyV1::RejectRun {
            return Err(
                "native target WFO certifies only invalid_target_policy='reject_run'".to_owned(),
            );
        }
        if folds.is_empty() {
            return Err("native target WFO plan requires at least one causal fold".to_owned());
        }
        RuntimeBudgetV1::check_optional(budget.max_bars, base_template.bar_count(), "bar")?;
        RuntimeBudgetV1::check_optional(
            budget.max_native_memory_bytes,
            base_template.source_market_bytes(),
            "native memory",
        )?;
        let bars = base_template.bar_count();
        let symbols = base_template.n_symbols();
        if symbols != 1 && admission_policy.is_none() {
            return Err(
                "native target WFO without admission_policy is single-symbol only; shared-account multi-symbol target WFO requires an explicit portfolio admission policy"
                    .to_owned(),
            );
        }
        let width = bars
            .checked_mul(symbols)
            .ok_or_else(|| "native target WFO dimensions overflow".to_owned())?;
        if tradable.len() != width
            || stale.len() != width
            || qty_step.len() != symbols
            || min_qty.len() != symbols
            || min_notional.len() != symbols
            || equity_fraction.len() != symbols
            || qty_step
                .iter()
                .chain(min_qty.iter())
                .chain(min_notional.iter())
                .chain(equity_fraction.iter())
                .any(|value| !value.is_finite() || *value < 0.0)
        {
            return Err(
                "native target WFO constraints do not match the prepared template".to_owned(),
            );
        }
        let mut seen = BTreeSet::new();
        let mut fold_templates = Vec::with_capacity(folds.len());
        for fold in &folds {
            fold.validate(bars)?;
            if !seen.insert(fold.fold_id) {
                return Err("native target WFO fold IDs must be unique".to_owned());
            }
            let range = fold.test_range();
            fold_templates.push(Arc::new(base_template.window(range.start, range.end)?));
        }
        let fingerprint = target_wfo_plan_fingerprint(
            &base_template,
            &folds,
            kind,
            timing,
            invalid_target_policy,
            &tradable,
            &stale,
            &qty_step,
            &min_qty,
            &min_notional,
            &equity_fraction,
            admission_policy,
            budget,
        );
        Ok(Self {
            base_template,
            fold_templates: fold_templates.into(),
            folds: folds.into(),
            kind,
            timing,
            invalid_target_policy,
            tradable: tradable.into(),
            stale: stale.into(),
            qty_step: qty_step.into(),
            min_qty: min_qty.into(),
            min_notional: min_notional.into(),
            equity_fraction: equity_fraction.into(),
            admission_policy,
            budget,
            fingerprint,
        })
    }

    #[must_use]
    pub const fn version(&self) -> u16 {
        NATIVE_TARGET_WFO_RUNTIME_VERSION_V1
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
    pub fn folds(&self) -> &[FoldPlan] {
        &self.folds
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
    pub fn bar_count(&self) -> usize {
        self.base_template.bar_count()
    }

    #[must_use]
    pub fn symbol_count(&self) -> usize {
        self.base_template.n_symbols()
    }

    #[must_use]
    pub const fn budget(&self) -> RuntimeBudgetV1 {
        self.budget
    }

    #[must_use]
    pub const fn admission_policy(&self) -> Option<PortfolioAdmissionPolicyV1> {
        self.admission_policy
    }

    #[must_use]
    pub fn market_bytes(&self) -> usize {
        self.base_template.source_market_bytes()
    }

    fn request_for(
        &self,
        fold_index: usize,
        full_targets: &[f64],
        output: NativeOutputProfileV1,
    ) -> Result<(TargetWfoRequestV1, usize), String> {
        let fold = self
            .folds
            .get(fold_index)
            .copied()
            .ok_or_else(|| "native target WFO fold index is outside plan".to_owned())?;
        let symbols = self.symbol_count();
        let expected = self
            .bar_count()
            .checked_mul(symbols)
            .ok_or_else(|| "native target WFO target dimensions overflow".to_owned())?;
        if full_targets.len() != expected {
            return Err(
                "prepared native target WFO targets differ from plan market dimensions".to_owned(),
            );
        }
        let range = fold.test_range();
        let start = range.start * symbols;
        let end = range.end * symbols;
        let local_targets = full_targets[start..end].to_vec();
        let local_tradable = self.tradable[start..end].to_vec();
        let local_stale = self.stale[start..end].to_vec();
        let copied_bytes = local_targets
            .len()
            .saturating_mul(std::mem::size_of::<f64>())
            .saturating_add(
                local_tradable
                    .len()
                    .saturating_mul(std::mem::size_of::<bool>()),
            )
            .saturating_add(
                local_stale
                    .len()
                    .saturating_mul(std::mem::size_of::<bool>()),
            )
            .saturating_add(
                (self.qty_step.len()
                    + self.min_qty.len()
                    + self.min_notional.len()
                    + self.equity_fraction.len())
                .saturating_mul(std::mem::size_of::<f64>()),
            );
        let template = self
            .fold_templates
            .get(fold_index)
            .cloned()
            .ok_or_else(|| "native target WFO template is outside plan".to_owned())?;
        let request = match self.admission_policy {
            Some(admission_policy) => {
                TargetWfoRequestV1::Shared(SharedPortfolioTargetRequestV1::from_template(
                    template,
                    local_targets,
                    self.kind,
                    self.timing,
                    self.invalid_target_policy,
                    local_tradable,
                    local_stale,
                    self.qty_step.to_vec(),
                    self.min_qty.to_vec(),
                    self.min_notional.to_vec(),
                    self.equity_fraction.to_vec(),
                    admission_policy,
                    output,
                )?)
            }
            None => TargetWfoRequestV1::Direct(DirectTargetRequestV1::from_template(
                template,
                local_targets,
                self.kind,
                self.timing,
                self.invalid_target_policy,
                local_tradable,
                local_stale,
                self.qty_step.to_vec(),
                self.min_qty.to_vec(),
                self.min_notional.to_vec(),
                self.equity_fraction.to_vec(),
                output,
            )?),
        };
        Ok((request, copied_bytes))
    }
}

enum TargetWfoRequestV1 {
    Direct(DirectTargetRequestV1),
    Shared(SharedPortfolioTargetRequestV1),
}

struct TargetWfoSuccessV1 {
    final_equity: f64,
    fold_return: f64,
    fold_sharpe: f64,
    fold_sortino: f64,
    max_drawdown: f64,
    turnover: f64,
    total_fee: f64,
    total_funding: f64,
    fill_count: u64,
    rejected_count: u64,
    liquidated: bool,
    command_count: usize,
    request_fingerprint: [u8; 32],
    terminal_fingerprint: [u8; 32],
}

/// Snapshot counters for the direct target WFO runtime. There is no command
/// arena or event-session worker pool; one detached Rust batch loop owns all
/// direct delta runs, so worker-pool counters remain explicitly zero.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NativeTargetWfoRuntimeStatsV1 {
    pub score_batches: u64,
    pub audit_batches: u64,
    pub completed_tasks: u64,
}

/// Persistent target WFO owner. It owns only immutable plans and score/audit
/// counters; every candidate/fold starts a fresh direct target account.
pub struct NativeTargetWfoRuntimeV2 {
    plan: Arc<NativeTargetWfoPlanV1>,
    closed: AtomicBool,
    running: AtomicBool,
    cancellation: AtomicBool,
    generation: AtomicU64,
    counters: Mutex<NativeTargetWfoRuntimeStatsV1>,
}

impl NativeTargetWfoRuntimeV2 {
    pub fn new(plan: Arc<NativeTargetWfoPlanV1>) -> Result<Self, String> {
        Ok(Self {
            plan,
            closed: AtomicBool::new(false),
            running: AtomicBool::new(false),
            cancellation: AtomicBool::new(false),
            generation: AtomicU64::new(1),
            counters: Mutex::new(NativeTargetWfoRuntimeStatsV1::default()),
        })
    }

    #[must_use]
    pub fn plan(&self) -> &NativeTargetWfoPlanV1 {
        &self.plan
    }

    #[must_use]
    pub fn closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }

    #[must_use]
    pub fn stats(&self) -> NativeTargetWfoRuntimeStatsV1 {
        self.counters
            .lock()
            .expect("native target WFO counter lock poisoned")
            .clone()
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

    pub fn reset(&self) -> Result<(), String> {
        if self.closed() {
            return Err("native target WFO runtime is closed".to_owned());
        }
        if self.running.load(Ordering::Acquire) {
            return Err("native target WFO runtime cannot reset during a score batch".to_owned());
        }
        self.clear_cancellation();
        self.generation.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }

    pub fn close(&self) -> Result<(), String> {
        if self.running.load(Ordering::Acquire) {
            return Err("native target WFO runtime cannot close during a score batch".to_owned());
        }
        self.closed.store(true, Ordering::Release);
        Ok(())
    }

    pub fn score(
        &self,
        batch: Arc<PreparedWfoTargetBatchV1>,
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        self.run(batch, NativeOutputProfileV1::Score, None)
    }

    pub fn audit_selected(
        &self,
        batch: Arc<PreparedWfoTargetBatchV1>,
        candidate_ids: &[u64],
        expected_intent_fingerprint: [u8; 32],
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        if batch.fingerprint() != expected_intent_fingerprint {
            return Err(
                "native target WFO audit batch fingerprint differs from the scored prepared intent"
                    .to_owned(),
            );
        }
        let selected = candidate_ids.iter().copied().collect::<BTreeSet<_>>();
        if selected.is_empty() {
            return Err(
                "native target WFO audit requires at least one selected candidate".to_owned(),
            );
        }
        if selected
            .iter()
            .any(|candidate| !batch.candidate_ids.contains(candidate))
        {
            return Err(
                "native target WFO audit candidate was not present in the scored prepared intent"
                    .to_owned(),
            );
        }
        self.run(batch, NativeOutputProfileV1::Audit, Some(selected))
    }

    fn run(
        &self,
        batch: Arc<PreparedWfoTargetBatchV1>,
        output: NativeOutputProfileV1,
        selected: Option<BTreeSet<u64>>,
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        if self.closed() {
            return Err("native target WFO runtime is closed".to_owned());
        }
        if batch.bars() != self.plan.bar_count() || batch.symbols() != self.plan.symbol_count() {
            return Err(
                "prepared native target WFO batch differs from immutable plan dimensions"
                    .to_owned(),
            );
        }
        if batch.is_per_fold() && batch.fold_count() != self.plan.folds().len() {
            return Err(
                "prepared per-fold native target batch differs from plan fold count".to_owned(),
            );
        }
        let candidate_count = selected
            .as_ref()
            .map_or_else(|| batch.rows(), BTreeSet::len);
        let expected_rows = candidate_count
            .checked_mul(self.plan.folds().len())
            .ok_or_else(|| "native target WFO metric row count overflow".to_owned())?;
        if expected_rows > self.plan.budget().max_metric_rows {
            return Err("native target WFO metric row budget exceeded before execution".to_owned());
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
            .map_err(|_| {
                "native target WFO runtime already has an active score batch".to_owned()
            })?;
        let result = self.run_active(batch, output, selected);
        self.running.store(false, Ordering::Release);
        result
    }

    fn run_active(
        &self,
        batch: Arc<PreparedWfoTargetBatchV1>,
        output: NativeOutputProfileV1,
        selected: Option<BTreeSet<u64>>,
    ) -> Result<NativeWfoMetricMatrixV2, String> {
        let mut errors = WfoErrorTable::with_limit(self.plan.budget().max_error_rows);
        let mut rows = Vec::new();
        let mut copied_bytes = 0_usize;
        let deadline = self.plan.budget().deadline();
        for (fold_index, fold) in self.plan.folds().iter().enumerate() {
            for candidate_index in 0..batch.rows() {
                let candidate_id = batch.candidate_id(candidate_index);
                if selected
                    .as_ref()
                    .is_some_and(|ids| !ids.contains(&candidate_id))
                {
                    continue;
                }
                if self.cancellation.load(Ordering::Acquire) {
                    rows.push(WfoCandidateMetricRowV2::canceled(
                        candidate_id,
                        fold.fold_id,
                        0,
                    ));
                    continue;
                }
                if deadline.is_some_and(|value| Instant::now() >= value) {
                    rows.push(WfoCandidateMetricRowV2::budget_exceeded(
                        candidate_id,
                        fold.fold_id,
                        0,
                    ));
                    continue;
                }
                let (row, bytes) = self.execute_one(
                    &batch,
                    fold_index,
                    candidate_index,
                    *fold,
                    output,
                    &mut errors,
                );
                copied_bytes = copied_bytes.saturating_add(bytes);
                rows.push(row);
            }
        }
        rows.sort_by(|left, right| {
            left.candidate_id
                .cmp(&right.candidate_id)
                .then_with(|| left.fold_id.cmp(&right.fold_id))
                .then_with(|| left.scenario_id.cmp(&right.scenario_id))
        });
        let mut counters = self
            .counters
            .lock()
            .expect("native target WFO counter lock poisoned");
        if output == NativeOutputProfileV1::Audit {
            counters.audit_batches = counters.audit_batches.saturating_add(1);
        } else {
            counters.score_batches = counters.score_batches.saturating_add(1);
        }
        counters.completed_tasks = counters.completed_tasks.saturating_add(rows.len() as u64);
        Ok(NativeWfoMetricMatrixV2 {
            rows,
            errors: errors.values,
            errors_dropped: errors.dropped,
            plan_fingerprint: self.plan.fingerprint(),
            intent_fingerprint: batch.fingerprint(),
            audit: output == NativeOutputProfileV1::Audit,
            worker_count: 1,
            active_worker_count: 1,
            worker_tasks: vec![counters.completed_tasks],
            market_copy_bytes: 0,
            candidate_execution_copy_bytes: copied_bytes,
            intent_ingest_bytes: batch.ingest_bytes(),
            worker_pool_creations: 0,
            worker_pool_batches: 0,
            poison_recoveries: 0,
        })
    }

    fn execute_one(
        &self,
        batch: &PreparedWfoTargetBatchV1,
        fold_index: usize,
        candidate_index: usize,
        fold: FoldPlan,
        output: NativeOutputProfileV1,
        errors: &mut WfoErrorTable,
    ) -> (WfoCandidateMetricRowV2, usize) {
        let candidate_id = batch.candidate_id(candidate_index);
        let request = self.plan.request_for(
            fold_index,
            batch.target(fold_index, candidate_index),
            output,
        );
        let (request, copied_bytes) = match request {
            Ok(value) => value,
            Err(error) => {
                let slot = errors.retain(error);
                return (
                    WfoCandidateMetricRowV2::failed(
                        candidate_id,
                        fold.fold_id,
                        0,
                        CandidateStatusCodeV2::InvalidIntent,
                        slot,
                    ),
                    0,
                );
            }
        };
        let execution = match request {
            TargetWfoRequestV1::Direct(request) => request.execute().map(|result| {
                let score = result.output.score();
                let metrics = score.metrics_v2.as_ref();
                TargetWfoSuccessV1 {
                    final_equity: score.final_equity,
                    fold_return: metrics.total_return,
                    fold_sharpe: metrics.sharpe,
                    fold_sortino: metrics.sortino,
                    max_drawdown: metrics.max_drawdown,
                    turnover: score.total_turnover,
                    total_fee: score.total_fee,
                    total_funding: score.total_funding,
                    fill_count: score.fill_count.max(0) as u64,
                    rejected_count: score.rejected_count.max(0) as u64,
                    liquidated: score.liquidated,
                    command_count: result.command_count,
                    request_fingerprint: result.request_fingerprint,
                    terminal_fingerprint: result.terminal_fingerprint,
                }
            }),
            TargetWfoRequestV1::Shared(request) => request.execute().map(|result| {
                let score = result.output.score();
                let metrics = score.metrics_v2.as_ref();
                TargetWfoSuccessV1 {
                    final_equity: score.final_equity,
                    fold_return: metrics.total_return,
                    fold_sharpe: metrics.sharpe,
                    fold_sortino: metrics.sortino,
                    max_drawdown: metrics.max_drawdown,
                    turnover: score.total_turnover,
                    total_fee: score.total_fee,
                    total_funding: score.total_funding,
                    fill_count: score.fill_count.max(0) as u64,
                    rejected_count: score.rejected_count.max(0) as u64,
                    liquidated: score.liquidated,
                    command_count: result.command_count,
                    request_fingerprint: result.request_fingerprint,
                    terminal_fingerprint: result.terminal_fingerprint,
                }
            }),
        };
        match execution {
            Ok(result) => {
                let status = if result.liquidated {
                    CandidateStatusCodeV2::Liquidated
                } else {
                    CandidateStatusCodeV2::Success
                };
                let fill_rate = if result.command_count == 0 {
                    1.0
                } else {
                    (result.fill_count as f64 / result.command_count as f64).min(1.0)
                };
                (
                    WfoCandidateMetricRowV2 {
                        candidate_id,
                        fold_id: fold.fold_id,
                        scenario_id: 0,
                        status,
                        final_equity: result.final_equity,
                        fold_return: result.fold_return,
                        fold_sharpe: result.fold_sharpe,
                        fold_sortino: result.fold_sortino,
                        max_drawdown: result.max_drawdown,
                        turnover: result.turnover,
                        total_fee: result.total_fee,
                        total_funding: result.total_funding,
                        fill_rate,
                        fill_count: result.fill_count,
                        rejected_count: result.rejected_count,
                        liquidated: result.liquidated,
                        request_fingerprint: result.request_fingerprint,
                        terminal_fingerprint: result.terminal_fingerprint,
                        error_slot: u32::MAX,
                    },
                    copied_bytes,
                )
            }
            Err(error) => {
                let slot = errors.retain(error);
                (
                    WfoCandidateMetricRowV2::failed(
                        candidate_id,
                        fold.fold_id,
                        0,
                        CandidateStatusCodeV2::InternalInvariantFailure,
                        slot,
                    ),
                    copied_bytes,
                )
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn target_wfo_plan_fingerprint(
    template: &NativeExecutionTemplateV1,
    folds: &[FoldPlan],
    kind: DirectTargetKindV1,
    timing: u8,
    invalid_target_policy: InvalidTargetPolicyV1,
    tradable: &[bool],
    stale: &[bool],
    qty_step: &[f64],
    min_qty: &[f64],
    min_notional: &[f64],
    equity_fraction: &[f64],
    admission_policy: Option<PortfolioAdmissionPolicyV1>,
    budget: RuntimeBudgetV1,
) -> [u8; 32] {
    let mut writer = StableFingerprint::new(b"quantbt-native-target-wfo-plan-v1");
    writer.bytes(&template.fingerprint());
    writer.u8(kind as u8);
    writer.u8(timing);
    writer.u8(invalid_target_policy as u8);
    match admission_policy {
        Some(policy) => {
            writer.u8(1);
            writer.u8(policy as u8);
        }
        None => writer.u8(0),
    }
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
    for values in [tradable, stale] {
        writer.usize(values.len());
        for value in values {
            writer.u8(u8::from(*value));
        }
    }
    for values in [qty_step, min_qty, min_notional, equity_fraction] {
        writer.usize(values.len());
        for value in values {
            writer.f64(*value);
        }
    }
    writer.finish()
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use quantbt_engine::FullMarketData;
    use quantbt_execution::{AccountModelV1, ExecutionContractV1, InstrumentTableV1};

    use super::*;

    fn plan() -> Arc<NativeTargetWfoPlanV1> {
        let market = Arc::new(
            FullMarketData::new(
                (0..10).collect(),
                vec![100.0; 10],
                vec![102.0; 10],
                vec![98.0; 10],
                vec![
                    100.0, 101.0, 102.0, 101.0, 103.0, 104.0, 103.0, 105.0, 106.0, 107.0,
                ],
                vec![1.0; 10],
                vec![0.0; 10],
                vec![false; 10],
                1,
            )
            .unwrap(),
        );
        let template = Arc::new(
            NativeExecutionTemplateV1::new(
                market,
                InstrumentTableV1::sequential(vec![1.0], vec![2.0], vec![0.0005]).unwrap(),
                AccountModelV1::new(10_000.0, 0.005, 0.0002, false).unwrap(),
                ExecutionContractV1::new(2).unwrap(),
            )
            .unwrap(),
        );
        Arc::new(
            NativeTargetWfoPlanV1::new(
                template,
                vec![
                    FoldPlan {
                        fold_id: 10,
                        warmup_start: 0,
                        train_start: 0,
                        train_end: 3,
                        test_start: 3,
                        test_end: 6,
                    },
                    FoldPlan {
                        fold_id: 20,
                        warmup_start: 0,
                        train_start: 0,
                        train_end: 6,
                        test_start: 6,
                        test_end: 10,
                    },
                ],
                DirectTargetKindV1::Units,
                TARGET_TIMING_CLOSE_TARGET_V2_SAME_CLOSE,
                InvalidTargetPolicyV1::RejectRun,
                vec![true; 10],
                vec![false; 10],
                vec![0.0],
                vec![0.0],
                vec![0.0],
                vec![1.0],
                None,
                RuntimeBudgetV1::default(),
            )
            .unwrap(),
        )
    }

    #[test]
    fn prepared_target_runtime_resets_each_fold_and_replays_audit() {
        let runtime = NativeTargetWfoRuntimeV2::new(plan()).unwrap();
        let candidates = vec![11, 22];
        let first = vec![0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, -1.0, -1.0, 0.0];
        let second = vec![0.0, -1.0, -1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0];
        let batch = Arc::new(
            PreparedWfoTargetBatchV1::shared(candidates, [first, second].concat(), 10, 1).unwrap(),
        );
        let score = runtime.score(batch.clone()).unwrap();
        assert_eq!(score.rows.len(), 4);
        assert!(
            score
                .rows
                .iter()
                .all(|row| row.status == CandidateStatusCodeV2::Success)
        );
        let audit = runtime
            .audit_selected(batch, &[22], score.intent_fingerprint)
            .unwrap();
        assert_eq!(audit.rows.len(), 2);
        for row in &audit.rows {
            let expected = score
                .rows
                .iter()
                .find(|candidate| {
                    candidate.candidate_id == row.candidate_id && candidate.fold_id == row.fold_id
                })
                .unwrap();
            assert_eq!(row.terminal_fingerprint, expected.terminal_fingerprint);
        }
    }
}
