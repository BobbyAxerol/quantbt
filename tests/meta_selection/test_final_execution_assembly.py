"""Final assembly is opt-in; diagnostics and the financial owner stay intact."""

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.orders import OrderCommand
from quantbt.core.schema import OrderSide, OrderType
from quantbt.walkforward import WalkForwardEngine, WalkForwardFold
from quantbt.wfo_execution import (
    WfoExecutionAssemblyRequest,
    WfoExecutionWindow,
    assemble_final_execution,
    stitch_execution_windows,
)


def market():
    index = pd.date_range("2021-01-01", "2021-04-30", freq="D", tz="UTC")
    close = 100. + np.arange(len(index)) * .1 + np.sin(np.arange(len(index)))
    return pd.DataFrame(dict(open=close, high=close+1., low=close-1., close=close,
        volume=1000.), index=index)


ENTRY = pd.Timestamp("2021-03-30", tz="UTC")
CLOSE = pd.Timestamp("2021-04-02", tz="UTC")


def command(timestamp, *, close=False):
    return OrderCommand(timestamp, symbol="X", side=OrderSide.SELL if close else OrderSide.BUY,
        order_type=OrderType.MARKET, qty=1., reduce_only=close,
        order_id="crossing-close" if close else "crossing-entry")


class Callback:
    def __init__(self, final=False):
        self.final = final

    def on_bar_close(self, context):
        if context.timestamp == ENTRY:
            return (command(context.timestamp),)
        if self.final and context.timestamp == CLOSE and context.positions.get("X", 0.) > 0:
            return (command(context.timestamp, close=True),)
        return ()


def strategy(route, events):
    def generate(data, params, train_index, test_index, fold):
        events.append("generate")
        if route == "event_driven":
            return WfoExecutionWindow(route, test_index, strategy_factory=Callback)
        commands = (command(ENTRY),) if ENTRY in test_index else ()
        return WfoExecutionWindow(route, test_index, commands=commands)
    return generate


def final_window(request):
    if request.route == "event_driven":
        return WfoExecutionWindow(request.route, request.index,
            strategy_factory=lambda: Callback(final=True))
    return WfoExecutionWindow(request.route, request.index,
        commands=(command(ENTRY), command(CLOSE, close=True)))


def financial(route):
    return QuantBTEndpoint.event_driven(input_mode="strategy" if route == "event_driven" else "orders",
        backend="python", profile="audit", symbols=["X"], initial_capital=10000.,
        leverage=2., fee_rate=.001, slippage_bps=0., use_funding=False)


def endpoint(generate, route="order_commands"):
    return QuantBTEndpoint.walk_forward(generate, execution_endpoint=financial(route), target_mode=route,
        split_mode="2021-03-01", split_frequency="monthly", train_window="59D",
        window_mode="rolling", optimization_mode="mode_4_is_only_robust", optuna_trials=0,
        optimization_config=dict(candidate_selection_metric="is_only_robust", is_subperiods=1,
            use_scalar_trial_scoring=False, wfo_execution_reuse="off"))


def assert_account(a, b):
    for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(a, name), getattr(b, name))


@pytest.mark.parametrize("route", ("order_commands", "event_driven"))
def test_public_final_hook_preserves_crossing_close_in_one_original_account(monkeypatch, route):
    import quantbt.wfo_execution as execution

    data, events, accounts, requests = market(), [], [], []
    generate = strategy(route, events)
    original_execute = execution.execute_window
    original_validate = WalkForwardEngine._validate_proxy_screening

    def execute(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        accounts.append((args[2], result))
        events.append("final_account" if args[2].index.equals(data.index) else "diagnostic")
        return result

    def validate(self, **kwargs):
        original_validate(self, **kwargs)
        events.append("decisions_complete")

    monkeypatch.setattr(execution, "execute_window", execute)
    monkeypatch.setattr(WalkForwardEngine, "_validate_proxy_screening", validate)
    params = {"size": 1., "nested": {"levels": [1, 2]}}
    baseline = endpoint(generate, route).backtest(data=data, params=params)
    old = baseline.metadata["walk_forward_result"]
    assert len(old.folds) == 2
    expected_stitch = stitch_execution_windows(old.oos_output.parts, data.index)
    assert old.oos_output.commands == expected_stitch.commands
    assert old.oos_output.parts == expected_stitch.parts
    assert "wfo_execution_assembly" not in old.metadata
    assert_account(baseline, original_execute(financial(route).config, data, expected_stitch))
    diagnostics = [result for window, result in accounts if not window.index.equals(data.index)]
    events.clear()
    accounts.clear()

    def assemble(request):
        assert isinstance(request, WfoExecutionAssemblyRequest)
        assert events[-1] == "decisions_complete"
        assert len(request.folds) == len(request.windows) == 2
        assert request.index.equals(data.index)
        assert set(request.params_by_fold) == {fold.fold_id for fold in request.folds}
        for fold in request.folds:
            with pytest.raises(TypeError):
                request.params_by_fold[fold.fold_id]["size"] = 999.
            with pytest.raises(TypeError):
                request.params_by_fold[fold.fold_id]["nested"]["levels"][0] = 999
            with pytest.raises(ValueError):
                fold.test_index.values[0] = fold.test_index.values[-1]
            fold.test_index.name = "adapter-only"
        with pytest.raises(ValueError):
            request.index.values[0] = request.index.values[-1]
        request.index.name = "adapter-only"
        request.data.iloc[0, 0] = -999.
        requests.append(request)
        events.append("assemble")
        return final_window(request)

    generate.assemble_wfo_execution = assemble
    assembled = endpoint(generate, route).backtest(data=data, params=params)
    current = assembled.metadata["walk_forward_result"]
    assert len(requests) == 1
    assert events[-3:] == ["decisions_complete", "assemble", "final_account"]
    assert sum(window.index.equals(data.index) for window, _ in accounts) == 1
    new_diagnostics = [result for window, result in accounts if not window.index.equals(data.index)]
    assert len(diagnostics) == len(new_diagnostics) > 0
    for a, b in zip(diagnostics, new_diagnostics, strict=True):
        assert_account(a, b)
    assert current.params == old.params == params
    pd.testing.assert_frame_equal(current.trial_table, old.trial_table)
    assert all(fold.test_index.name is None for fold in current.folds)
    assert data.index.name is None and data.iloc[0, 0] > 0.
    assert current.metadata["wfo_execution_assembly"]["scope"] == "final_only"
    assert current.metadata["wfo_execution_assembly"]["adapter_identity"].endswith(".assemble")
    assert np.any(np.asarray(baseline.positions)[-1] != 0.)
    assert np.all(np.asarray(assembled.positions)[-1] == 0.)
    boundary = data.index.get_loc(pd.Timestamp("2021-04-01", tz="UTC"))
    assert np.any(np.asarray(assembled.positions)[boundary] != 0.)
    assert not current.oos_output.parts
    expected = original_execute(financial(route).config, data, final_window(requests[0]))
    assert_account(assembled, expected)


def test_public_hook_runs_once_after_all_real_causal_selections_and_observers(monkeypatch):
    from examples.wfo_meta_execution import make_endpoint
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory
    from quantbt.optimization.meta_selection.runtime import PublicMetaRuntime

    events, requests = [], []
    original_select, original_observe = PublicMetaRuntime.select, PublicMetaRuntime.observe

    def select(self, fold, native):
        result = original_select(self, fold, native)
        events.append(("select", fold.fold_id))
        return result

    def observe(self, data, fold):
        original_observe(self, data, fold)
        events.append(("observe", fold.fold_id))

    monkeypatch.setattr(PublicMetaRuntime, "select", select)
    monkeypatch.setattr(PublicMetaRuntime, "observe", observe)

    def context():
        return MetaHistoryContext(MetaHistory(), "synthetic-final-assembly", "SYNTHETIC-orders",
            "1D", "final-assembly", clock=lambda fold, stage, elapsed:
            fold.train_index[-1] + pd.Timedelta(seconds={"search": 10, "fit": 20, "seal": 30}[stage]))

    reference_endpoint = make_endpoint("order_commands", mode="shadow", support=1, trials=2)
    reference = reference_endpoint.backtest(data=market(), param_ranges={"window": (3, 5, 2)},
        meta_history=context())
    events.clear()

    def assemble(request):
        assert events == [(stage, fold.fold_id) for fold in request.folds for stage in ("select", "observe")]
        requests.append(request)
        events.append(("assemble", None))
        return WfoExecutionWindow(request.route, request.index,
            commands=tuple(c for window in request.windows for c in window.commands))

    target = make_endpoint("order_commands", mode="shadow", support=1, trials=2)
    target.config.strategy_class.assemble_wfo_execution = assemble
    result = target.backtest(data=market(), param_ranges={"window": (3, 5, 2)}, meta_history=context())
    assert len(requests) == 1 and len(requests[0].folds) == 2
    assert events[-1] == ("assemble", None)
    wf, prior = result.metadata["walk_forward_result"], reference.metadata["walk_forward_result"]
    assert requests[0].params_by_fold == wf.metadata["params_by_fold"] == prior.metadata["params_by_fold"]
    pd.testing.assert_frame_equal(wf.trial_table, prior.trial_table)
    assert wf.metadata["meta_selection"]["observer_attempts"] > 0
    assert wf.metadata["meta_selection"]["observer_failures"] == 0
    assert_account(result, reference)


def request_values():
    data = market().iloc[:8]
    idx = data.index
    folds = tuple(WalkForwardFold(i, idx[0], idx[stop-3], idx[stop-2], idx[stop-1],
        idx[:stop-2], idx[stop-2:stop]) for i, stop in enumerate((6, 8)))
    windows = tuple(WfoExecutionWindow("order_commands", fold.test_index) for fold in folds)
    return dict(route="order_commands", index=idx, folds=folds, windows=windows,
        params_by_fold={fold.fold_id: {"nested": {"levels": [1, 2]}, "array": np.arange(3)}
            for fold in folds}, data=data)


def test_request_clones_and_freezes_parameter_containers_and_calendars():
    values = request_values()
    request = WfoExecutionAssemblyRequest(**values)
    params = request.params_by_fold[0]
    with pytest.raises(FrozenInstanceError):
        request.route = "intrabar"
    with pytest.raises(TypeError):
        request.params_by_fold[0] = {}
    with pytest.raises(TypeError):
        params["nested"]["levels"] = ()
    with pytest.raises(ValueError):
        params["array"].setflags(write=True)
    with pytest.raises(ValueError):
        request.index.values.setflags(write=True)
    with pytest.raises(ValueError):
        request.folds[0].test_index.values.setflags(write=True)
    shifted = replace(request, index=request.index.tz_convert("Asia/Bangkok"))
    assert shifted.index.equals(request.index.tz_convert("Asia/Bangkok"))
    with pytest.raises(ValueError):
        shifted.index.values.setflags(write=True)
    values["params_by_fold"][0]["array"][0] = 99
    values["params_by_fold"][0]["nested"]["levels"][0] = 99
    assert params["array"][0] == 0
    assert params["nested"]["levels"] == (1, 2)


@pytest.mark.parametrize("defect", ("route", "reverse", "naive", "duplicate", "fold_order",
    "window_route", "window_index", "missing_params", "object_array"))
def test_request_rejects_malformed_route_schedule_and_index(defect):
    values = request_values()
    if defect == "route":
        values["route"] = "signal_notional"
    elif defect == "reverse":
        values["index"] = values["index"][::-1]
    elif defect == "naive":
        values["index"] = values["index"].tz_localize(None)
    elif defect == "duplicate":
        values["index"] = values["index"].append(values["index"][-1:])
    elif defect == "fold_order":
        values["folds"], values["windows"] = values["folds"][::-1], values["windows"][::-1]
    elif defect == "window_route":
        values["windows"] = (replace(values["windows"][0], route="delivery_arbitrage"), values["windows"][1])
    elif defect == "window_index":
        values["windows"] = (replace(values["windows"][0], index=values["index"][:2]), values["windows"][1])
    elif defect == "missing_params":
        values["params_by_fold"].pop(0)
    else:
        values["params_by_fold"][0]["array"] = np.array([{}], dtype=object)
    with pytest.raises((ValueError, TypeError)):
        WfoExecutionAssemblyRequest(**values)


@pytest.mark.parametrize("defect", ("proxy", "route", "partial_index", "extra_index", "not_callable"))
def test_final_hook_rejects_invalid_return_without_fallback(defect):
    values = request_values()

    def assemble(request):
        if defect == "proxy":
            return pd.Series(1., index=request.index)
        route = "delivery_arbitrage" if defect == "route" else request.route
        index = request.index[:-1] if defect == "partial_index" else request.index
        if defect == "extra_index":
            index = index.append(index[-1:] + pd.Timedelta(days=1))
        return WfoExecutionWindow(route, index)

    adapter = SimpleNamespace(assemble_wfo_execution=0 if defect == "not_callable" else assemble)
    with pytest.raises((TypeError, ValueError)):
        assemble_final_execution(adapter, **values)


def test_final_callback_requires_its_own_full_window_factory_not_diagnostic_parts():
    values = request_values()
    values["route"] = "event_driven"
    values["windows"] = tuple(WfoExecutionWindow("event_driven", fold.test_index,
        strategy_factory=Callback) for fold in values["folds"])
    adapter = SimpleNamespace(assemble_wfo_execution=lambda request:
        stitch_execution_windows(request.windows, request.index))
    with pytest.raises(ValueError, match="diagnostic parts"):
        assemble_final_execution(adapter, **values)
