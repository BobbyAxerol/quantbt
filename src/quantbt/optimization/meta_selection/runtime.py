"""One fold selection hook and post-seal observer on existing scalar execution."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import random
from time import perf_counter

import numpy as np
import pandas as pd

from .capture import ISPoolCapture
from .common import MetaRecordError, digest, utc, wire
from .config import MetaHistoryContext
from .descriptors import DescriptorSchema
from .history import SealedTaskRevision
from .model import RidgeLearner
from .observer import PostDecisionObserver, market_signature
from .panel import freeze_panel
from .records import CandidateRoleRef, CompatibilityFamily, MetaTask
from .selection import MetaSelector


@contextmanager
def isolated_observer_rng(seed):
    """Counterfactual work cannot advance the native run's global RNG streams."""
    python_state, numpy_state = random.getstate(), np.random.get_state()
    try:
        random.seed(seed)
        np.random.seed(seed % (2**32))
        yield
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)


class PublicISPoolCapture(ISPoolCapture):
    def capture(self, **kwargs):
        # A centroid can need one additional original IS evaluation. Its global
        # RNG consumption must not perturb the native OOS or next-fold search.
        with isolated_observer_rng(int(kwargs["seed"]) + 104729):
            super().capture(**kwargs)
        if self.pools[-1].auxiliary_is_evaluations:
            completed_at = utc(self.resolved_at(kwargs["folds"][0]))
            pool = self.pools[-1]
            self.pools[-1] = replace(
                pool,
                candidates=tuple(
                    replace(c, resolved_at=completed_at) for c in pool.candidates
                ),
            )


class PublicMetaRuntime:
    def __init__(self, engine, context, ranges):
        if not isinstance(context, MetaHistoryContext):
            raise MetaRecordError(
                "META_HISTORY_INCOMPATIBLE: typed meta_history context required"
            )
        if not getattr(engine.scorer, "meta_metric_support", False):
            raise MetaRecordError(
                "META_METRIC_SUPPORT_MISSING: original-result witness required"
            )
        self.engine, self.context, self.config = (
            engine,
            context,
            engine.config.meta_selection,
        )
        self.schema = DescriptorSchema(ranges)
        # Qualification/require failure occurs before market/search/financial calls.
        self.numeric = context.numeric_runtime(self.config.native_batch_policy)
        self.learner = RidgeLearner(
            settings=self.config.ridge_settings(), runtime=self.numeric
        )
        self.selector = MetaSelector(runtime=self.numeric)
        self.capture = PublicISPoolCapture(
            resolved_at=lambda f: self.completed(f, "search"),
            max_pools=self.config.max_folds,
        )
        self.capture.validate(engine.config, engine.scorer)
        self.family = self.compatibility_family(engine, context, self.schema)
        self.records, self.models, self.tasks, self.snapshots = [], {}, [], []
        self.observer = PostDecisionObserver(engine.scorer._meta_adapter)
        self.elapsed = {"snapshot": 0.0, "fit_select": 0.0, "observer": 0.0}

    @staticmethod
    def compatibility_family(engine, context, schema):
        from ...core.wfo_contracts import strategy_fingerprint

        c = engine.config
        scorer = engine.scorer
        anchor_keys = (
            "candidate_selection_metric",
            "top_is_fraction",
            "top_is_k",
            "flat_eps",
            "flat_min_samples",
            "flat_selector",
            "is_subperiods",
            "q25_weight",
            "dispersion_penalty",
            "temporal_weight",
            "plateau_weight",
            "plateau_quantile",
            "plateau_median_weight",
            "plateau_std_penalty",
            "plateau_size_bonus",
            "use_bootstrap_penalty",
            "use_complexity_penalty",
            "min_trades_per_year",
            "trade_penalty_factor",
        )
        return CompatibilityFamily(
            strategy_fingerprint(engine.strategy),
            schema.space.identity,
            schema.schema_id,
            context.instrument_id,
            context.timeframe,
            digest(
                {
                    "window": c.window_mode,
                    "train_window": c.train_window,
                    "test": c.split_frequency,
                    "warmup": c.warmup_policy,
                    "warmup_bars": c.warmup_bars,
                    "purge": c.purge_bars,
                    "embargo": c.embargo_bars,
                    "label_horizon": c.label_horizon_bars,
                }
            ),
            scorer._meta_adapter.contract.metric_id,
            scorer._meta_economics_id,
            "original-endpoint-reset-v1",
            digest(
                {
                    "mode": c.optimization_mode,
                    "schedule": c.optimization_schedule,
                    "policy": {k: getattr(c, k) for k in anchor_keys},
                    "parameter_constraints": strategy_fingerprint(
                        c.parameter_constraints
                    )
                    if c.parameter_constraints is not None
                    else None,
                    "result_constraints": strategy_fingerprint(c.result_constraints)
                    if c.result_constraints is not None
                    else None,
                }
            ),
            digest(
                {
                    "sampler": asdict(c.sampler_config)
                    if c.sampler_config
                    else "legacy_tpe",
                    "seed_policy": "existing_fold_seed_v1",
                    "base_seed": c.random_seed,
                    "budget": c.optuna_trials,
                    "early_stopping": c.optuna_early_stopping,
                    "warm_start": c.sampler_warm_start,
                }
            ),
            digest(
                {
                    "diagnostics": "reset_flat",
                    "final": c.fold_account_policy,
                    "intent": c.intent_contract.metadata(),
                }
            ),
        )

    def validate_market(self, data, idx, folds):
        if not isinstance(data, pd.DataFrame) or len(folds) > self.config.max_folds:
            raise MetaRecordError(
                "META_ROUTE_UNSUPPORTED: bounded single DataFrame tape required"
            )
        if not isinstance(idx, pd.DatetimeIndex) or not idx.is_unique:
            raise MetaRecordError(
                "META_ROUTE_UNSUPPORTED: exact unique calendar required"
            )
        utc(idx[0])
        if len(folds) and any(
            len(f.train_index) < 2 or len(f.test_index) < 2 for f in folds
        ):
            raise MetaRecordError(
                "META_ROUTE_UNSUPPORTED: finite diagnostic windows require >=2 bars"
            )

    def begin_fold(self, fold):
        self.started = perf_counter()
        self._last_completion = utc(fold.train_index[-1])
        started = perf_counter()
        self.snapshot = self.context.history.snapshot(
            family_id=self.family.family_id,
            authorized_corpora=self.context.authorized_corpora,
            outcome_origins=self.context.outcome_origins,
            research_exposures=self.context.research_exposures,
            information_as_of=fold.train_index[-1],
        )
        self.snapshots.append(self.snapshot)
        self.elapsed["snapshot"] += perf_counter() - started

    def completed(self, fold, stage):
        elapsed = perf_counter() - self.started
        now = (
            self.context.clock(fold, stage, elapsed)
            if self.context.clock is not None
            else utc(fold.train_index[-1]) + pd.Timedelta(seconds=elapsed)
        )
        now = utc(now)
        if now < self._last_completion or now >= utc(fold.test_index[0]):
            raise MetaRecordError(
                "META_CLOCK_UNSUPPORTED: replay completion must be monotone and before forward action; no automatic target shift/backdating"
            )
        self._last_completion = now
        return now

    def task_from_pool(self, fold, pool, seal):
        return MetaTask(
            self.family,
            self.context.corpus_id,
            self.context.run_id,
            fold.train_index[-1],
            fold.train_index[0],
            fold.train_index[-1],
            fold.test_index[0],
            fold.test_index[-1],
            fold.train_index[-1],
            pool.seed,
            pool.candidates,
            pool.anchor_evaluation_id,
            (
                CandidateRoleRef(
                    "native_anchor",
                    self.family.anchor_policy_id,
                    pool.anchor_evaluation_id,
                ),
            ),
            pool.candidates[0].resolved_at,
            pool.candidates[0].resolved_at,
            seal,
            fold.test_index[0],
            pd.Timestamp.now(tz="UTC"),
            "historical_replay",
            "historical_counterfactual",
            "research_only",
            {
                "study_id": pool.study_id,
                "seed": pool.seed,
                "budget": self.engine.config.optuna_trials,
                "auxiliary_is_evaluations": pool.auxiliary_is_evaluations,
                "schema": "qms-public-is-pool-v1",
            },
        )

    def select(self, fold, native):
        started = perf_counter()
        pool = self.capture.pools.pop()
        if (
            pool.fold_id != fold.fold_id
            or pool.schema.schema_id != self.schema.schema_id
        ):
            raise MetaRecordError("META_FEATURE_SCHEMA_MISMATCH: captured current pool")
        fit = self.learner.fit(self.schema, self.snapshot)
        # Learner wall time is separate from this historical replay completion.
        fit_time = self.completed(fold, "fit")
        if fit.model is not None:
            fit = replace(fit, model=replace(fit.model, fit_completed_at=fit_time))
        task = self.task_from_pool(fold, pool, fit_time)
        proposal = self.selector.propose(
            task,
            fit,
            schema=self.schema,
            mode="shadow" if self.config.mode == "shadow" else "proposal",
            full_ranking=self.config.full_ranking,
        )
        sealed = self.completed(fold, "seal")
        task = replace(task, decision_sealed_at=sealed)
        proposal = replace(proposal, decision_sealed_at=sealed, ready_at=sealed)
        actual_id = (
            proposal.proposed_evaluation_id
            if self.config.mode == "active"
            else pool.anchor_evaluation_id
        )
        if self.config.mode == "active":
            proposal = replace(proposal, mode="active", actual_evaluation_id=actual_id)
        current = {c.evaluation_id: c for c in pool.candidates}
        chosen = current[actual_id]
        learned = proposal.status == "META_MODEL_PROPOSAL"
        active_learned = self.config.mode == "active" and learned
        sidecar = {
            "fold_id": int(fold.fold_id),
            "task_id": task.task_id,
            "native_optimization_mode": self.engine.config.optimization_mode,
            "native_selection_policy": self.family.anchor_policy_id,
            "native_selection_information_scope": "current_IS_only",
            "final_selection_policy": "relative_sharpe_decay_v1"
            if active_learned
            else "native",
            "current_outer_oos_used_for_selection": False,
            "past_matured_forward_used_for_selection": active_learned,
            "meta_proposal_uses_past_matured_forward": learned,
            "native_selected_candidate_id": task.anchor.candidate_id,
            "native_selected_evaluation_id": task.anchor.evaluation_id,
            "native_selected_params": wire(task.anchor.effective_params),
            "native_objective": float(native.objective),
            "native_raw_is_sharpe": task.anchor.observation.raw_sharpe,
            "raw_best_evaluation_id": proposal.raw_best_evaluation_id,
            "meta_proposed_candidate_id": current[
                proposal.proposed_evaluation_id
            ].candidate_id,
            "meta_proposed_evaluation_id": proposal.proposed_evaluation_id,
            "selected_candidate_id": chosen.candidate_id,
            "selected_evaluation_id": actual_id,
            "selected_params": wire(chosen.effective_params),
            "selected_trial_id": chosen.native_trial_id,
            "information_as_of": wire(task.data_cutoff),
            "search_completed_at": wire(task.search_completed_at),
            "fit_completed_at": wire(proposal.fit_completed_at),
            "decision_sealed_at": wire(sealed),
            "ready_at": wire(sealed),
            "effective_at": wire(task.first_forward_action_at),
            "wall_generated_at": wire(task.wall_generated_at),
            "clock_mode": "historical_replay",
            "live_equivalence_claim": False,
            "training_snapshot_id": self.snapshot.snapshot_id,
            "training_revision_ids": tuple(
                r.revision_id for r in self.snapshot.revisions
            ),
            "matured_origins": self.snapshot.origin_count,
            "family_id": self.family.family_id,
            "eligible_is_pool_size": len(pool.candidates),
            "auxiliary_is_evaluations": pool.auxiliary_is_evaluations,
            "final_selection_reason": proposal.status,
            "proposal": proposal,
            "numeric_backend": self.numeric.metadata,
        }
        self.panel = freeze_panel(
            task,
            self.schema,
            required_winners=(proposal.proposed_evaluation_id, actual_id),
            sealed_at=sealed,
        )
        sidecar.update(
            panel_id=self.panel.panel_id,
            panel_members=self.panel.members,
            panel_extra_union_members=self.panel.extra_union_members,
        )
        self.tasks.append(task)
        self.records.append(sidecar)
        if fit.model is not None:
            self.models[fit.model.model_id] = fit.model
        self.elapsed["fit_select"] += perf_counter() - started
        if self.config.mode == "shadow" or actual_id == pool.anchor_evaluation_id:
            return native
        # Keep native trial/candidate ledgers intact; final record has actual IS objective.
        required = self.engine._required_trades(fold.train_index)
        from ...walkforward import trade_frequency_penalty

        factor = (
            1.0
            if self.engine.config.trade_penalty_factor is None
            else self.engine.config.trade_penalty_factor
        )
        penalty = trade_frequency_penalty(
            chosen.observation.activity_count, required, factor
        )
        return replace(
            native,
            params=dict(chosen.effective_params),
            trial_id=chosen.native_trial_id,
            objective=chosen.objective,
            mean_is_sharpe=chosen.observation.raw_sharpe - penalty,
            selection_metadata={
                **native.selection_metadata,
                "stage": "meta_actual_selection",
                "meta_actual_selection": True,
                "native_trial_id": native.trial_id,
                "native_objective": native.objective,
            },
        )

    def observe(self, data, fold):
        if not self.config.label_observer:
            return
        started = perf_counter()
        task, panel = self.tasks[-1], self.panel
        from ...endpoint import QuantBTEndpoint
        from ...walkforward import WalkForwardEngine

        # Existing lifecycle owns fresh strategy instances; no optimizer/prepared
        # strategy session or mutable scorer/account is shared with the observer.
        cfg = replace(self.engine.config, meta_selection=None)
        auxiliary = WalkForwardEngine(
            self.engine.strategy, cfg, scorer=self.engine.scorer
        )
        auxiliary._prepared_context = self.engine._prepared_context
        auxiliary._strategy_market_fingerprints = {}
        auxiliary._lifecycle_records, auxiliary._lifecycle_records_dropped = [], 0

        def evaluate(candidate):
            with isolated_observer_rng(
                task.resolved_fold_seed + candidate.native_trial_id + 1
            ):
                output = auxiliary._call_strategy(
                    data, dict(candidate.effective_params), fold
                )
                prefix = data.loc[: fold.test_index[-1]]
                diagnostic = QuantBTEndpoint(self.engine.scorer.score_config)
                result = diagnostic.backtest(
                    data=prefix.loc[fold.test_index],
                    signal=output,
                    symbols=self.engine.scorer.symbols,
                )
                return result, market_signature(
                    prefix, fold.test_index, config=self.engine.scorer.score_config
                )

        # Physical outcomes are already on disk in replay, but stay inaccessible
        # to selection until their declared terminal/publication time.
        available = task.forward_end + pd.Timedelta(
            seconds=self.config.reporting_lag_seconds
        )
        outcomes = self.observer.observe(
            task=task,
            panel=panel,
            evaluate=evaluate,
            expected_index=fold.test_index,
            label_available_at=available,
            reporting_lag_seconds=self.config.reporting_lag_seconds,
        )
        elapsed = perf_counter() - started
        actual_available = available + pd.Timedelta(seconds=elapsed)
        outcomes = tuple(
            replace(o, label_available_at=actual_available) for o in outcomes
        )
        revision = SealedTaskRevision(task, panel, outcomes, actual_available)
        self.context.history.append(revision)
        self.records[-1].update(
            observer_revision_id=revision.revision_id,
            observer_label_available_at=wire(actual_available),
            observer_evaluations=len(outcomes),
            observer_seconds=elapsed,
            observer_lifecycle=tuple(auxiliary._lifecycle_records),
            observer_reset_accounts=True,
        )
        self.elapsed["observer"] += elapsed

    def finalize(self, result):
        learned = any(
            r["past_matured_forward_used_for_selection"] for r in self.records
        )
        result.metadata["meta_selection"] = {
            "schema": "qms-public-run-v1",
            "config": asdict(self.config),
            "config_digest": digest(asdict(self.config)),
            "records": tuple(self.records),
            "models": dict(self.models),
            "tasks": tuple(self.tasks),
            "elapsed_seconds": dict(self.elapsed),
            "observer_attempts": self.observer.attempts,
            "observer_failures": self.observer.failures,
            "current_outer_oos_used_for_selection": False,
            "past_matured_forward_used_for_selection": learned,
            "meta_proposal_uses_past_matured_forward": any(
                r["meta_proposal_uses_past_matured_forward"] for r in self.records
            ),
            "account_authority": "existing_continuous_stitched_target_account",
            "observer_account_scope": "independent_reset_counterfactual_diagnostics",
        }
        if self.config.mode == "active":
            fields = (
                "native_selection_information_scope",
                "final_selection_policy",
                "current_outer_oos_used_for_selection",
                "past_matured_forward_used_for_selection",
                "native_selected_evaluation_id",
                "meta_proposed_evaluation_id",
                "selected_evaluation_id",
            )
            table = result.metadata["fold_selection_table"].copy()
            by_fold = {r["fold_id"]: r for r in self.records}
            table["native_causality_claim"] = table["causality_claim"]
            for field in fields:
                table[field] = [by_fold[int(f)][field] for f in table["fold_id"]]
            table["causality_claim"] = [
                "current_outer_oos_excluded_past_forward_adaptive"
                if by_fold[int(f)]["past_matured_forward_used_for_selection"]
                else native
                for f, native in zip(table["fold_id"], table["native_causality_claim"])
            ]
            result.metadata["fold_selection_table"] = table
            last = self.records[-1]
            selected_metadata = dict(result.best_trial["selection_metadata"])
            selected_metadata["native_causality_claim"] = selected_metadata[
                "causality_claim"
            ]
            selected_metadata.update({k: last[k] for k in fields})
            if last["past_matured_forward_used_for_selection"]:
                selected_metadata["causality_claim"] = (
                    "current_outer_oos_excluded_past_forward_adaptive"
                )
            result.best_trial["selection_metadata"] = selected_metadata
        if learned:
            result.metadata.update(
                validation_claim="chronological_adaptive_meta_selection",
                chronological_validation_claim="outer_oos_after_frozen_past_forward_adaptive_selection",
                causality_claim="current_outer_oos_excluded_past_forward_adaptive",
            )
