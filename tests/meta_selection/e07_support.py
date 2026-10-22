"""Own-family event/W3 fixtures; no private alpha, signal proxy or new engine."""

from dataclasses import replace
from types import SimpleNamespace

from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from examples.wfo_meta_reactive_grid import FillFeedbackGrid, GridFactory
from tests.meta_selection import pre_e06_02_support as shared

CASES = (("event_driven", "python"), ("event_driven", "rust"),
         ("order_commands", "python"), ("order_commands", "rust"),
         ("reactive_reset", "rust"))


def make(case, mode, *, data, start="2022-05-01", variant=True, process=False):
    route, backend = case
    numeric = "require" if variant or route != "reactive_reset" else "reference"
    original = shared.endpoint(route, data, mode, start=start, numeric=numeric,
                               witness=variant if route != "reactive_reset" else True)
    if route == "reactive_reset":
        from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1
        financial, config = original.endpoint, original.config
        original.close()
        return financial.prepare_reactive_walk_forward(data=data, strategy_factory=GridFactory(),
            walkforward_config=config, symbols=["X"], runtime_config=ReactiveWfoRuntimeConfigV1(
                worker_mode="process" if process else "inprocess"))
    config = original.config
    financial = config.wfo_execution_config
    metadata = dict(financial.metadata)
    metadata["event_driven_facade"] = {**metadata["event_driven_facade"], "backend": backend}
    return QuantBTEndpoint(replace(config, wfo_execution_config=replace(financial,
        native_backend=backend, metadata=metadata)))


def prepare_run(case, mode="active", *, data=None, history=None, start="2022-05-01",
        variant=True, process=False, clock=shared.replay_clock):
    route, _ = case
    data = shared.tape(route, end="2022-05-31") if data is None else data
    bt = make(case, mode, data=data, start=start, variant=variant, process=process)
    context = MetaHistoryContext(history if history is not None else MetaHistory(),
        "e07-public-synthetic", "E07-" + route, "1D", "e07-software-v1", clock=clock)
    kwargs = dict(param_ranges=shared.RANGES)
    if route != "reactive_reset":
        kwargs["data"] = data
    if mode != "off":
        kwargs["meta_history"] = context
    return route, bt, context, data, kwargs


def execute(prepared):
    route, bt, context, data, kwargs = prepared
    try:
        result = bt.backtest(**kwargs)
    finally:
        if route == "reactive_reset":
            bt.close()
    return shared.Run(route, bt, result, context, data)


def run(case, mode="active", **kwargs):
    return execute(prepare_run(case, mode, **kwargs))


def independent(value, task, candidate, *, forward=False):
    if value.route != "reactive_reset":
        return shared.independent(value, task, candidate, forward=forward)
    a, b = (task.forward_start, task.forward_end) if forward else (task.is_start, task.is_end)
    start = value.data.index.get_loc(a)
    marker = SimpleNamespace(start_bar=start, end_bar=value.data.index.get_loc(b)+1,
                             seed=task.resolved_fold_seed)
    return segment(value, marker, candidate.effective_params)


def segment(value, marker, params):
    prepared = value.endpoint.endpoint.prepare_native_event_strategy(data=value.data, symbols=["X"])
    try:
        return prepared.run_window(FillFeedbackGrid(task=marker, window=params["window"]),
            start_bar=marker.start_bar, end_bar=marker.end_bar, report_level="audit")
    finally:
        prepared.backend.clear_prepared_caches()


def rebuild(value):
    if value.route != "reactive_reset":
        shared.account_equal(value.result, shared.rebuild_final(value))
        return
    for fold in value.result.fold_results:
        shared.account_equal(fold.result, segment(value, fold.task, fold.params))


def output(value):
    return value.result.metadata if value.route == "reactive_reset" else value.result.metadata["walk_forward"]
