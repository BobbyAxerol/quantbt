"""C02 R3B witness primitive; public global/meta activation remains forbidden."""

from dataclasses import replace

import numpy as np
import pytest

from quantbt.backends.reactive_wfo import _ReactiveSelectionEngine
from quantbt.core.runtime_governance import RuntimeBudgetError, RuntimeCanceledError
from quantbt.backends.reactive_wfo_batch import ReactiveWfoCandidateBatchSchedulerV1, reactive_wfo_marker_key
from quantbt.optimization.meta_selection.reactive_batch_witness import OriginalReactiveBatchWitnessReducer
from quantbt.strategies.reactive_wfo import prepare_reactive_wfo_strategy
from tests.test_phase76_reactive_wfo import (
    _bars, _endpoint, _config, _TaskStrategy, _CandidateBatchReactiveFactory,
    _CandidateBatchLocalErrorReactiveFactory,
)


def fixture(*, error=False, deadline=None):
    data = _bars()
    factory = (_CandidateBatchLocalErrorReactiveFactory() if error else _CandidateBatchReactiveFactory())
    runtime = _endpoint(data).prepare_reactive_walk_forward(data=data, strategy_factory=factory,
        walkforward_config=_config(mode="mode_4_is_only_robust"), symbols=["BTC"])
    engine = _ReactiveSelectionEngine(runtime=runtime, config=runtime.config)
    folds = engine.build_folds(runtime._prepared_runner.idx)
    runtime._adapter = prepare_reactive_wfo_strategy(strategy_factory=factory, data=runtime.data,
        datetime_index=runtime._prepared_runner.idx, folds=folds, random_seed=17,
        static_config={"schema": "quantbt-reactive-wfo-static-v1"})
    markers = [engine._call_strategy_for_indices(data=runtime.data, params={"direction": direction},
        train_index=folds[0].train_index, test_index=folds[0].test_index, fold=folds[0],
        context="c02-batch-witness") for direction in (-1., 1.)]
    reducer = OriginalReactiveBatchWitnessReducer(adapter=runtime._adapter,
        prepared_runner=runtime._prepared_runner, data=runtime.data, trading_days=365)
    scheduler = ReactiveWfoCandidateBatchSchedulerV1(adapter=runtime._adapter,
        prepared_runner=runtime._prepared_runner, trading_days=365, batch_size=2,
        max_wall_time_ms=deadline, _metric_witness=reducer)
    return runtime, reducer, scheduler, markers


def test_c02_t05_batch_original_paths_score_raw_witness_exact(monkeypatch):
    runtime, reducer, scheduler, markers = fixture()
    originals = []
    original_reduce = reducer.reduce

    def capture(marker, payload, runner):
        originals.append({key: np.asarray(payload[key]).copy() for key in (
            "equity", "positions", "fees", "funding", "turnover", "initial_margin", "maintenance_margin")})
        assert all(not np.asarray(payload[key]).size for key in
                   ("command_bar", "callback_bar", "terminal_active_order_id", "fill_bar", "event_bar"))
        return original_reduce(marker, payload, runner)

    monkeypatch.setattr(reducer, "reduce", capture)
    try:
        rows = scheduler.score_markers(markers)
        for marker, original in zip(markers, originals, strict=True):
            packet, _fingerprint = reducer.execute(marker)
            key = reactive_wfo_marker_key(marker)
            assert scheduler.witnesses[key] == packet
            assert rows[key] == dict(zip(("sharpe", "turnover", "trade_count", "mean_return", "volatility",
                                         "max_drawdown_pct", "profit_factor"), packet.scores, strict=True))
            ordinary = runtime._prepared_runner.run_window(
                _TaskStrategy(task=marker.task, direction=marker.params["direction"]),
                start_bar=marker.task.start_bar, end_bar=marker.task.end_bar, report_level="minimal")
            for key, field in (("equity", "equity"), ("positions", "positions"), ("fees", "fees"),
                               ("funding", "funding"), ("turnover", "turnover"),
                               ("initial_margin", "initial_margin"), ("maintenance_margin", "maintenance_margin")):
                if field == "turnover":
                    values = ordinary.diagnostics[field]
                elif field in {"initial_margin", "maintenance_margin"}:
                    values = ordinary.margin[field]
                else:
                    values = getattr(ordinary, field)
                np.testing.assert_array_equal(original[key].reshape(-1), np.asarray(values).reshape(-1))
        # Reuse is an independent reset, never cross-candidate mutable state.
        first = scheduler.witnesses
        scheduler.score_markers(markers)
        assert scheduler.witnesses == first
        assert scheduler.telemetry.runner_creations == 1
    finally:
        scheduler.close()
        reducer.close()
        runtime.close()
    assert not scheduler.witnesses and reducer.closed


def test_c02_t05_local_batch_error_never_becomes_valid_witness():
    runtime, reducer, scheduler, markers = fixture(error=True)
    try:
        scheduler.score_markers(markers)
        assert reactive_wfo_marker_key(markers[0]) in scheduler.failures
        assert reactive_wfo_marker_key(markers[0]) not in scheduler.witnesses
        assert reactive_wfo_marker_key(markers[1]) in scheduler.witnesses
    finally:
        scheduler.close()
        reducer.close()
        runtime.close()


def test_c02_t05_later_chunk_failure_clears_all_detached_witnesses(monkeypatch):
    runtime, reducer, scheduler, markers = fixture()
    scheduler._batch_size = 1
    original = reducer.reduce
    calls = []

    def fail_later(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("test incomplete chunk")
        return original(*args)

    monkeypatch.setattr(reducer, "reduce", fail_later)
    try:
        with pytest.raises(RuntimeError, match="incomplete"):
            scheduler.score_markers(markers)
        assert not scheduler.witnesses
    finally:
        scheduler.close()
        reducer.close()
        runtime.close()


def test_c02_t06_batch_meta_global_stays_unsupported():
    data = _bars()
    config = replace(_config(mode="mode_4_is_only_robust"), calendar_contract="exact_v2",
        strategy_lifecycle_policy="isolated_v1", scoring_backend="endpoint",
        meta_selection=dict(mode="active", native_batch_policy="reference"))
    with pytest.raises((ValueError, NotImplementedError), match="META_METHODOLOGY_UNSUPPORTED"):
        _endpoint(data).prepare_reactive_walk_forward(data=data,
            strategy_factory=_CandidateBatchReactiveFactory(), walkforward_config=config, symbols=["BTC"])


@pytest.mark.parametrize("kind", ["deadline", "cancel"])
def test_c02_t05_actual_native_batch_abort_has_no_partial_witness(kind, monkeypatch):
    import time
    from tests.test_phase76_reactive_wfo import _CandidateBatchStrategy

    runtime, reducer, scheduler, markers = fixture(deadline=1 if kind == "deadline" else None)
    original = _CandidateBatchStrategy.on_wake_batch

    def abort(self, context, out):
        if kind == "deadline":
            time.sleep(.005)
        else:
            scheduler.cancel_active()
        return original(self, context, out)

    monkeypatch.setattr(_CandidateBatchStrategy, "on_wake_batch", abort)
    try:
        with pytest.raises((RuntimeBudgetError, RuntimeCanceledError)):
            scheduler.score_markers(markers)
        assert not scheduler.witnesses
        assert scheduler._active_runner is None
    finally:
        scheduler.close()
        reducer.close()
        runtime.close()
