"""Phase 65 prepared native WFO runtime contract tests.

The tests deliberately keep generic pandas/callback WFO outside this surface.
They certify only the bounded Strategy-IR prepared signal path: immutable
market/fold ownership, fresh OOS accounts, scalar score rows, deterministic
worker scheduling, and selected-candidate audit replay.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    NativeIRFold,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
    RustNativeIRRunner,
)
from quantbt.backends.native_wfo import NativeWfoRuntimeV2, _concat_metric_matrices
from quantbt.optimization.space import suggest_params


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _frame(n: int = 24) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    base = 100.0 + np.cumsum(np.where(np.arange(n) % 5 < 3, 0.45, -0.30))
    return pd.DataFrame(
        {
            "open": np.r_[base[0], base[:-1]],
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base,
            "volume": 1_000.0,
        },
        index=index,
    )


def _runtime(*, workers: int, schedule: str = "certified_sequential_v1"):
    frame = _frame()
    backend = NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
        )
    )
    full_runner = backend.prepare_rust_batched_runner(
        frame.index,
        closes={"BTC": frame["close"]},
        highs={"BTC": frame["high"]},
        lows={"BTC": frame["low"]},
        opens={"BTC": frame["open"]},
        symbols=["BTC"],
        contract_size=1.0,
    )
    program = NativeStrategyIR(
        NativeStrategyKind.SIGNAL_TARGET,
        "BTC",
        parameters=NativeStrategyParameters(quantity=1.0),
    )
    ir_runner = RustNativeIRRunner(full_runner, program)
    folds = (
        NativeIRFold(10, 0, 0, 8, 8, 16),
        NativeIRFold(20, 0, 0, 16, 16, len(frame)),
    )
    return ir_runner, folds, NativeWfoRuntimeV2(
        ir_runner,
        folds,
        workers=workers,
        optimizer_schedule=schedule,
    )


def _signals(n: int = 24) -> tuple[np.ndarray, np.ndarray]:
    base = np.where(np.arange(n) % 7 < 3, 1.0, np.where(np.arange(n) % 7 < 5, -1.0, 0.0))
    matrix = np.ascontiguousarray(np.vstack((base, -base, np.roll(base, 2))), dtype=np.float64)
    parameters = np.ascontiguousarray(
        [[1.0, 0.0, 0.0, 0.0], [0.5, 0.0, 0.0, 0.0], [1.5, 0.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    return matrix, parameters


def test_native_wfo_matches_existing_fold_oracle_and_is_worker_count_invariant():
    ir_runner, folds, one_runtime = _runtime(workers=1)
    _, _, many_runtime = _runtime(workers=3)
    signals, parameters = _signals()
    ids = np.asarray([101, 202, 303], dtype=np.uint64)
    try:
        one = one_runtime.score_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        many = many_runtime.score_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        np.testing.assert_array_equal(one.candidate_id, many.candidate_id)
        np.testing.assert_array_equal(one.fold_id, many.fold_id)
        np.testing.assert_array_equal(one.status, many.status)
        np.testing.assert_allclose(one.final_equity, many.final_equity, rtol=0.0, atol=1e-12)
        assert one.terminal_fingerprint == many.terminal_fingerprint
        assert one.metadata["market_copy_bytes"] == 0
        assert one.metadata["candidate_execution_copy_bytes"] == 0
        assert one.metadata["worker_pool_creations"] == 1

        for fold in folds:
            oracle = ir_runner.run_fold_batch_score(
                signals,
                fold,
                parameter_matrix=parameters,
                workers=1,
            )
            mask = one.fold_id == fold.fold_id
            np.testing.assert_allclose(one.final_equity[mask], oracle.final_equity, rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(one.total_fee[mask], oracle.total_fee, rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(one.turnover[mask], oracle.turnover, rtol=0.0, atol=1e-12)
            np.testing.assert_array_equal(one.fill_count[mask], oracle.fill_count)
            np.testing.assert_array_equal(one.rejected_count[mask], oracle.rejected_count)
    finally:
        one_runtime.close()
        many_runtime.close()


def test_native_wfo_selected_audit_replays_score_and_pool_is_reused():
    _, _, runtime = _runtime(workers=2)
    signals, parameters = _signals()
    ids = np.asarray([101, 202, 303], dtype=np.uint64)
    try:
        score = runtime.score_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        second = runtime.score_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        assert score.terminal_fingerprint == second.terminal_fingerprint
        assert second.metadata["worker_pool_creations"] == 1
        assert second.metadata["worker_pool_batches"] == 2
        audit = runtime.audit_shared(
            signals,
            candidate_ids=ids,
            selected_candidate_ids=np.asarray([202], dtype=np.uint64),
            expected_intent_fingerprint=score.intent_fingerprint,
            parameter_matrix=parameters,
        )
        audit.assert_audit_parity(score)
        assert audit.audit is True
        assert len(audit.candidate_id) == len(runtime.folds)
        with pytest.raises(ValueError, match="not present"):
            runtime.audit_shared(
                signals,
                candidate_ids=ids,
                selected_candidate_ids=np.asarray([999], dtype=np.uint64),
                expected_intent_fingerprint=score.intent_fingerprint,
                parameter_matrix=parameters,
            )
    finally:
        runtime.close()


def test_native_wfo_prepared_batch_has_one_ingest_boundary_and_is_plan_bound():
    _, _, runtime = _runtime(workers=2)
    _, _, incompatible_runtime = _runtime(workers=1, schedule="throughput_batch_v1")
    signals, parameters = _signals()
    ids = np.asarray([101, 202, 303], dtype=np.uint64)
    try:
        batch = runtime.prepare_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        assert batch.rows == len(ids)
        assert batch.bars == signals.shape[1]
        assert batch.per_fold is False
        assert batch.intent_ingest_bytes > 0
        score = runtime.score_prepared_batch(batch)
        repeated = runtime.score_prepared_batch(batch)
        assert score.intent_fingerprint == batch.intent_fingerprint
        assert repeated.intent_fingerprint == batch.intent_fingerprint
        assert repeated.metadata["candidate_execution_copy_bytes"] == 0
        audit = runtime.audit_prepared_batch(
            batch,
            selected_candidate_ids=np.asarray([202], dtype=np.uint64),
            expected_intent_fingerprint=batch.intent_fingerprint,
        )
        audit.assert_audit_parity(score)
        with pytest.raises(ValueError, match="different immutable runtime plan"):
            incompatible_runtime.score_prepared_batch(batch)
    finally:
        runtime.close()
        incompatible_runtime.close()


class _W1Strategy:
    def __init__(self, bars: int) -> None:
        self.base = np.where(np.arange(bars) % 6 < 3, 1.0, -1.0)

    def generate(self, *, params, fold_id: int):
        return self.base * float(params["side"])


class _W2Strategy(_W1Strategy):
    def generate_batch(self, *, params_matrix, fold_id: int):
        return np.vstack([self.base * float(params["side"]) for params in params_matrix])


def _final_equity_objective(matrix):
    return {
        candidate_id: float(np.mean(matrix.final_equity[matrix.candidate_id == candidate_id]))
        for candidate_id in np.unique(matrix.candidate_id)
    }


def _legacy_sequential_fold_oracle(ir_runner, folds, prepared, *, param_ranges, trials, seed):
    """Reference ask/evaluate/tell lifecycle over the prior fold primitive."""

    import optuna

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        pruner=optuna.pruners.NopPruner(),
    )
    for _ in range(trials):
        trial = study.ask()
        params = suggest_params(trial, param_ranges, fixed_params=None)
        values = []
        for fold in folds:
            signal = prepared.generate_batch(params_matrix=[params], fold_id=int(fold.fold_id))
            score = ir_runner.run_fold_batch_score(signal, fold, workers=1)
            values.append(float(score.final_equity[0]))
        value = float(np.mean(values))
        trial.report(value, step=0)
        assert not trial.should_prune()
        study.tell(trial, value)
    return study


def test_native_wfo_w1_w2_and_optimizer_schedules_are_explicit_and_deterministic():
    params = [{"side": 1.0}, {"side": -1.0}, {"side": 1.0}]
    _, _, runtime = _runtime(workers=2, schedule="certified_sequential_v1")
    try:
        w1 = runtime.score_prepared(_W1Strategy(24), params, adapter="w1")
        w2 = runtime.score_prepared(_W2Strategy(24), params, adapter="w2")
        np.testing.assert_allclose(w1.final_equity, w2.final_equity, rtol=0.0, atol=1e-12)
        np.testing.assert_array_equal(w1.status, w2.status)

        left = runtime.optimize_prepared(
            _W2Strategy(24),
            param_ranges={"side": [-1.0, 1.0]},
            n_trials=6,
            seed=42,
            top_k_audit=1,
        )
        _, _, reference_runtime = _runtime(workers=1, schedule="certified_sequential_v1")
        try:
            right = reference_runtime.optimize_prepared(
                _W2Strategy(24),
                param_ranges={"side": [-1.0, 1.0]},
                n_trials=6,
                seed=42,
                top_k_audit=1,
            )
            assert [trial.params for trial in left.study.trials] == [trial.params for trial in right.study.trials]
            assert [trial.value for trial in left.study.trials] == [trial.value for trial in right.study.trials]
            assert left.best_params == right.best_params
            assert left.audit_matrix is not None
            assert left.metadata["candidate_sequence_equivalent_to_sequential"] is True
            assert left.metadata["pruner_contract"] == "nop_pruner_complete_fold_scalar_v1"
        finally:
            reference_runtime.close()
    finally:
        runtime.close()

    _, _, first = _runtime(workers=2, schedule="throughput_batch_v1")
    _, _, second = _runtime(workers=1, schedule="throughput_batch_v1")
    try:
        first_result = first.optimize_prepared(
            _W2Strategy(24),
            param_ranges={"side": [-1.0, 1.0]},
            n_trials=6,
            seed=11,
            batch_size=3,
        )
        second_result = second.optimize_prepared(
            _W2Strategy(24),
            param_ranges={"side": [-1.0, 1.0]},
            n_trials=6,
            seed=11,
            batch_size=3,
            reference_best_objective=first_result.best_value + 1.0,
        )
        assert [trial.params for trial in first_result.study.trials] == [
            trial.params for trial in second_result.study.trials
        ]
        assert first_result.objective_by_candidate == second_result.objective_by_candidate
        assert first_result.metadata["candidate_sequence_equivalent_to_sequential"] is False
        assert first_result.metadata["quality_reference_status"] == "not_evaluated_without_explicit_reference"
        assert first_result.metadata["quality_regret_vs_reference"] is None
        assert second_result.metadata["quality_reference_status"] == "evaluated_against_explicit_reference"
        assert second_result.metadata["quality_regret_vs_reference"] == pytest.approx(1.0, abs=1e-12)
    finally:
        first.close()
        second.close()


def test_native_wfo_certified_sequential_matches_prior_fold_oracle_lifecycle():
    ir_runner, folds, runtime = _runtime(workers=2, schedule="certified_sequential_v1")
    prepared = _W2Strategy(24)
    ranges = {"side": [-1.0, 1.0]}
    try:
        reference = _legacy_sequential_fold_oracle(
            ir_runner,
            folds,
            prepared,
            param_ranges=ranges,
            trials=8,
            seed=91,
        )
        native = runtime.optimize_prepared(
            prepared,
            param_ranges=ranges,
            n_trials=8,
            seed=91,
            objective=_final_equity_objective,
        )
        assert [trial.params for trial in native.study.trials] == [trial.params for trial in reference.trials]
        np.testing.assert_allclose(
            [trial.value for trial in native.study.trials],
            [trial.value for trial in reference.trials],
            rtol=0.0,
            atol=1e-12,
        )
        assert native.best_params == reference.best_params
        assert native.best_value == pytest.approx(reference.best_value, abs=1e-12)
        assert [trial.state for trial in native.study.trials] == [trial.state for trial in reference.trials]
        assert all(trial.state.name == "COMPLETE" for trial in native.study.trials)
    finally:
        runtime.close()


class _UnstableAuditStrategy(_W2Strategy):
    """A deliberately invalid prepared adapter: replay must reject its drift."""

    def __init__(self, bars: int) -> None:
        super().__init__(bars)
        self.calls = 0

    def generate_batch(self, *, params_matrix, fold_id: int):
        self.calls += 1
        values = super().generate_batch(params_matrix=params_matrix, fold_id=fold_id)
        return values if self.calls <= 2 else -values


def test_native_wfo_top_k_audit_reuses_exact_source_batch_and_rejects_generator_drift():
    _, _, runtime = _runtime(workers=2, schedule="certified_sequential_v1")
    try:
        stable = runtime.optimize_prepared(
            _W2Strategy(24),
            param_ranges={"side": [-1.0, 1.0]},
            n_trials=4,
            seed=12,
            top_k_audit=4,
        )
        assert stable.audit_matrix is not None
        assert stable.audit_matrix.metadata["intent_fingerprint_scope"] == "aggregate_batches"
        assert len(stable.audit_matrix.metadata["intent_fingerprints"]) == 4
        stable.audit_matrix.assert_audit_parity(stable.score_matrix)

        with pytest.raises(AssertionError, match="different source intent"):
            runtime.optimize_prepared(
                _UnstableAuditStrategy(24),
                param_ranges={"side": [-1.0, 1.0]},
                n_trials=2,
                seed=12,
                top_k_audit=1,
            )
    finally:
        runtime.close()


def test_native_wfo_concatenation_remaps_bounded_error_side_tables_and_rejects_invalid_ids():
    _, _, runtime = _runtime(workers=1)
    signals, parameters = _signals()
    try:
        score = runtime.score_shared(
            signals,
            candidate_ids=np.asarray([101, 202, 303], dtype=np.uint64),
            parameter_matrix=parameters,
        )
        sentinel = np.iinfo(np.uint32).max
        left_slots = np.full(score.error_slot.shape, sentinel, dtype=np.uint32)
        right_slots = np.full(score.error_slot.shape, sentinel, dtype=np.uint32)
        left_slots[0] = 0
        right_slots[0] = 0
        left = replace(score, error_slot=left_slots, errors=("left error",))
        right = replace(score, error_slot=right_slots, errors=("right error",))
        combined = _concat_metric_matrices((left, right))
        assert combined.errors == ("left error", "right error")
        assert combined.error_slot[0] == 0
        assert combined.error_slot[len(score.error_slot)] == 1

        with pytest.raises(ValueError, match="non-negative integer"):
            runtime.score_shared(signals, candidate_ids=[-1, 2, 3], parameter_matrix=parameters)
        with pytest.raises(ValueError, match="non-negative integer"):
            runtime.score_shared(signals, candidate_ids=[1.5, 2.0, 3.0], parameter_matrix=parameters)
    finally:
        runtime.close()


def test_native_wfo_cancel_reset_and_unsupported_intent_fail_closed():
    import _quantbt_native

    ir_runner, folds, runtime = _runtime(workers=1)
    signals, parameters = _signals()
    ids = np.asarray([101, 202, 303], dtype=np.uint64)
    try:
        runtime.cancel()
        canceled = runtime.score_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        assert set(canceled.status.tolist()) == {7}
        runtime.clear_cancellation()
        runtime.reset()
        recovered = runtime.score_shared(signals, candidate_ids=ids, parameter_matrix=parameters)
        assert set(recovered.status.tolist()) == {0}

        fold_array = np.asarray(
            [
                [
                    fold.fold_id,
                    fold.warmup_start,
                    fold.train_start,
                    fold.train_end,
                    fold.test_start,
                    fold.test_end,
                ]
                for fold in folds
            ],
            dtype=np.uint32,
        )
        with pytest.raises(ValueError, match="not certified"):
            _quantbt_native.NativeWfoRuntimeV2.from_template(
                ir_runner.full_runner._typed_template,
                ir_runner._core,
                fold_array,
                intent_kind="target_units_v2",
            )
    finally:
        runtime.close()
