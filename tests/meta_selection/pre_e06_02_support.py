"""Preregistered public synthetic conformance, never alpha/edge evidence."""

from dataclasses import dataclass, replace
from functools import partial

import numpy as np
import pandas as pd

from quantbt import ExecutionConfig, QuantBTEndpoint, StrategyContextRequirements
from quantbt.core.delivery_lifecycle import DeliveryContract, DeliveryLifecycle
from quantbt.core.orders import OrderAction, OrderCommand
from quantbt.core.schema import OrderSide, OrderType
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.strategies.reactive_wfo import STRICT_CAUSAL_CACHE_CONTRACT_V1
from quantbt.wfo_execution import WfoExecutionWindow, execute_window
from examples import wfo_meta_execution as execution
from examples import wfo_meta_package as package
from examples import wfo_meta_portfolio as portfolio
from examples import wfo_meta_scalar as scalar


ROUTES = ("signal_notional", "notional", "unit", "pct_equity", "dca_ladder",
          "portfolio", "basket", "arbitrage", "intrabar", "event_driven",
          "order_commands", "delivery_arbitrage", "reactive_reset")
CUTOFFS = tuple(pd.Timestamp(s, tz="UTC") for s in
                ("2022-04-30", "2023-04-30", "2024-04-30"))
RANGES = {"window": (3, 9, 2)}
DELIVERY = ("SYNTH-A", "QUARTER-1", "QUARTER-2", "QUARTER-3")


def tape(route, *, end="2024-06-30", hourly=False):
    index = pd.date_range("2023-01-01" if hourly else "2020-01-01",
                          "2023-01-31 23:00" if hourly else end,
                          freq="h" if hourly else "D", tz="UTC")
    t = np.arange(len(index), dtype=float) / (24 if hourly else 1)
    frames = {}
    for symbol, base, drift, a, p, b, q in (
        ("SYNTH-A", 100, .00015, .025, 11, .01, 5),
        ("SYNTH-B", 80, .00010, .021, 13, .012, 7),
    ):
        close = base*np.exp(drift*t+a*np.sin(t/p)+b*np.cos(t/q))
        opening = np.r_[close[0], close[:-1]]
        frames[symbol] = pd.DataFrame(dict(open=opening,
            high=np.maximum(opening, close)*1.005,
            low=np.minimum(opening, close)*.995, close=close,
            volume=1000+50*np.cos(t/7),
            funding_rate=np.where(np.arange(len(t)) % 8 == 0, .0001, 0.)), index=index)
    if route == "delivery_arbitrage":
        for j, s in enumerate(DELIVERY[1:]):
            frames[s] = frames["SYNTH-B"].copy()
            frames[s].loc[:, ["open", "high", "low", "close"]] *= 1+j*.015
            frames[s]["funding_rate"] = 0.
        del frames["SYNTH-B"]
    return frames if route in {"portfolio", "basket", "arbitrage", "delivery_arbitrage"} else frames["SYNTH-A"]


def catalog():
    return DeliveryLifecycle(tuple(DeliveryContract(s,
        pd.Timestamp(date, tz="UTC"), pd.Timestamp(date, tz="UTC")-pd.Timedelta(days=1),
        "pre-e06-synthetic-quarterly-v1") for s, date in zip(DELIVERY[1:],
        ("2022-03-31", "2023-03-31", "2025-03-31"))))


def generate(route, data, params, index):
    if route == "portfolio":
        return portfolio.strategy(data, params, index, index, None)
    if route in {"basket", "arbitrage"}:
        return package.strategy(data, params, index, index, None)
    if route == "dca_ladder":
        h = data.loc[:index[-1]]
        return (np.sign(h.close.rolling(int(params["window"])).mean()-h.close)*3).reindex(index).fillna(0.)
    if route in scalar_targets():
        return scalar.strategy(data, params, index, index, None)
    if route == "delivery_arbitrage":
        commands = []
        for i in range(0, len(index)-3, int(params["window"])):
            entry, exit_at = index[i+1], index[i+3]
            leg = next(c.symbol for c in catalog().contracts if exit_at < c.flatten_at)
            for symbol, side in ((leg, OrderSide.BUY), (DELIVERY[0], OrderSide.SELL)):
                ident = f"pre02:{symbol}:{entry.value}"
                commands.extend((OrderCommand(entry, symbol=symbol, side=side,
                    order_type=OrderType.LIMIT, qty=.5, price=float(data[symbol].close.loc[index[i]])*.998,
                    order_id=ident), OrderCommand(exit_at, OrderAction.CANCEL, target_order_id=ident),
                    OrderCommand(exit_at, symbol=symbol, side=OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY,
                    order_type=OrderType.MARKET, qty=.5, reduce_only=True, order_id=ident+":close")))
        return WfoExecutionWindow(route, index, commands=tuple(commands))
    return execution.generate(route, data, params, index)


def scalar_targets():
    return ROUTES[:5]


def strategy(route, data, params, train_index, test_index, fold):
    return generate(route, data, params, test_index)


class CyclicReactive:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = StrategyContextRequirements(
        market=("open", "high", "low", "close"), positions=("qty",),
        account=("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"),
        fills="new_only", events="new_only", active_orders="snapshot", context_mode="numeric")

    def __init__(self, *, task, window):
        self.task, self.window = task, int(window)

    def reset(self, *, seed, task):
        self.task = task

    def on_bar_close(self, context, out):
        elapsed = int(context.bar_index)-self.task.start_bar
        if elapsed % (2*self.window) == 0:
            out.market(0, OrderSide.BUY, .5)
        elif elapsed % (2*self.window) == self.window:
            out.market(0, OrderSide.SELL, .5, reduce_only=True)


class PreparedCyclic:
    causal_cache_contract = STRICT_CAUSAL_CACHE_CONTRACT_V1

    def build_strategy(self, *, params, task):
        return CyclicReactive(task=task, window=params["window"])

    def close(self):
        pass


class CyclicFactory:
    def prepare_reactive_wfo(self, *, data, folds, static_config):
        return PreparedCyclic()


def replay_clock(fold, stage, elapsed):
    return fold.train_index[-1]+pd.Timedelta(seconds={"search": 10, "fit": 20, "seal": 30}[stage])


def endpoint(route, data, mode, *, start="2020-04-01", prepared=False, numeric="reference", witness=True):
    if route in scalar_targets():
        backend = "legacy" if route in {"pct_equity", "dca_ladder"} else "native_vectorized"
        old = scalar.make_scalar_endpoint(route, backend, mode,
            prepared="require" if prepared else "off", runtime="rust" if prepared else "numba")
    elif route == "portfolio":
        old = portfolio.make_endpoint(mode)
    elif route in {"basket", "arbitrage"}:
        old = package.make_endpoint(mode, kind="basket" if route == "basket" else "basis")
    elif route == "reactive_reset":
        # Reuse the WFO config factory; W3 retains its original reset-flat account.
        old = scalar.make_scalar_endpoint("signal_notional", mode=mode)
    else:
        old = execution.make_endpoint(route, mode)
    c, wf = old.config, old.config.walkforward_config
    meta = dict(mode=mode, min_matured_origins=12, lambda_reg=10., full_ranking=True,
                native_batch_policy=numeric, label_observer=True, reporting_lag_seconds=86400.)
    wf = replace(wf, split_mode=str(start), split_frequency="monthly", train_window="90D",
        is_subperiods=1, optuna_trials=8, random_seed=731, min_trades_per_year=None,
        trade_penalty_factor=None, top_is_fraction=.5, flat_eps=1., flat_min_samples=1,
        meta_selection=meta, metadata={**wf.metadata, "use_prepared_meta_witness": witness})
    if route == "reactive_reset":
        wf = replace(wf, fold_account_policy="reset_flat", fold_boundary_position_policy="reset_flat",
                     metadata={**wf.metadata, "financial_retention_scope": "segmented_reset_flat_execution"})
        financial = QuantBTEndpoint.native_event_strategy(initial_capital=20000., leverage=2.,
            fee_rate=.0005, use_funding=True, funding_rate=data.funding_rate,
            report_level="audit", native_backend="rust", reactive_kernel_mode="single_pass",
            reactive_runtime="numeric_every_bar_v1", execution_contract="event_lifecycle_v3_next_open",
            execution=ExecutionConfig(slippage_bps=1.))
        return financial.prepare_reactive_walk_forward(data=data, strategy_factory=CyclicFactory(),
            walkforward_config=wf, symbols=["X"])
    if route in execution_routes():
        fc = c.wfo_execution_config
        symbols = list(DELIVERY) if route == "delivery_arbitrage" else ["X"]
        rates = {s: f.funding_rate for s, f in data.items()} if isinstance(data, dict) else data.funding_rate
        fc = replace(fc, account=replace(fc.account, leverage=2.), execution=replace(fc.execution, slippage_bps=1.),
            use_funding=True, funding_rate=rates, symbols=symbols,
            metadata={**fc.metadata, **({"delivery_lifecycle": catalog()} if route == "delivery_arbitrage" else {})})
        return QuantBTEndpoint(replace(c, walkforward_config=wf, strategy_class=partial(strategy, route),
                                      wfo_execution_config=fc, symbols=symbols))
    rates = {s: f.funding_rate for s, f in data.items()} if isinstance(data, dict) else data.funding_rate
    return QuantBTEndpoint(replace(c, walkforward_config=wf, strategy_class=partial(strategy, route),
        account=replace(c.account, leverage=2.), execution=replace(c.execution, slippage_bps=1.),
        fee=.001, fee_rate=.0005, slippage=.0001, use_funding=True, funding_rate=rates))


def execution_routes():
    return ("intrabar", "event_driven", "order_commands", "delivery_arbitrage")


@dataclass
class Run:
    route: str
    endpoint: object
    result: object
    context: MetaHistoryContext
    data: object

    @property
    def meta(self):
        return self.result.metadata["meta_selection"] if self.route == "reactive_reset" else self.result.metadata["walk_forward"]["meta_selection"]


def clone_history(source, *, revisions=None, reverse=False):
    h = MetaHistory()
    items = list(source._revisions.values()) if revisions is None else list(revisions)
    for r in reversed(items) if reverse else items:
        h.append(r)
    return h


def run(route, mode="shadow", *, data=None, history=None, start="2020-04-01",
        prepared=False, numeric="reference", witness=True, clock=replay_clock):
    data = tape(route) if data is None else data
    bt = endpoint(route, data, mode, start=start, prepared=prepared, numeric=numeric, witness=witness)
    ctx = MetaHistoryContext(history if history is not None else MetaHistory(),
        "pre-e06-public-synthetic", "pre-e06-"+route, "1D", "pre-e06-software-v1", clock=clock)
    kwargs = {} if mode == "off" else dict(meta_history=ctx)
    if route != "reactive_reset":
        kwargs["data"] = data
    result = bt.backtest(param_ranges=RANGES, **kwargs)
    if route == "reactive_reset":
        bt.close()
    return Run(route, bt, result, ctx, data)


def current(data, cutoff):
    end = cutoff+pd.offsets.MonthEnd(1)
    return {s: f.loc[:end].copy() for s, f in data.items()} if isinstance(data, dict) else data.loc[:end].copy()


def independent(run, task, candidate, *, forward=False):
    a, b = (task.forward_start, task.forward_end) if forward else (task.is_start, task.is_end)
    frames = run.data if isinstance(run.data, dict) else {"X": run.data}
    idx = next(iter(frames.values())).loc[a:b].index
    if run.route == "reactive_reset":
        from types import SimpleNamespace
        financial = run.endpoint.endpoint
        prepared = financial.prepare_native_event_strategy(data=run.data, symbols=["X"])
        start = run.data.index.get_loc(a)
        marker = SimpleNamespace(start_bar=start, end_bar=start+len(idx), seed=task.resolved_fold_seed)
        try:
            return prepared.run_window(CyclicReactive(task=marker, window=candidate.effective_params["window"]),
                start_bar=start, end_bar=start+len(idx), report_level="audit")
        finally:
            prepared.backend.clear_prepared_caches()
    payload = generate(run.route, run.data, candidate.effective_params, idx)
    if run.route in execution_routes():
        return execute_window(run.endpoint.config.wfo_execution_config, run.data, payload)
    mode = run.route if run.route in {"portfolio", "basket", "arbitrage"} else "single_signal"
    diagnostic = QuantBTEndpoint(replace(run.endpoint.config, mode=mode))
    data = {s: f.loc[idx] for s, f in frames.items()} if isinstance(run.data, dict) else run.data.loc[idx]
    kwargs = dict(positions=payload) if run.route == "portfolio" else dict(signal=payload)
    return diagnostic.backtest(data=data, **kwargs)


def account_equal(a, b, *, exact=True):
    for key in ("equity", "returns", "positions", "fees", "funding", "margin"):
        x, y = getattr(a, key, None), getattr(b, key, None)
        assert (x is None) == (y is None), key
        if x is not None:
            if exact:
                np.testing.assert_array_equal(x, y, err_msg=key)
            else:
                np.testing.assert_allclose(x, y, rtol=1e-10, atol=1e-10, err_msg=key)


def rebuild_final(value):
    """Rebuild the stitched account, never substitute reset-flat diagnostics."""
    if value.route == "reactive_reset":
        return [independent(value, task, next(c for c in task.candidates
                if c.evaluation_id == record["selected_evaluation_id"]), forward=True)
                for task, record in zip(value.meta["tasks"], value.meta["records"], strict=True)]
    output = value.result.metadata["walk_forward_result"].oos_output
    if value.route in execution_routes():
        return execute_window(value.endpoint.config.wfo_execution_config, value.data, output)
    mode = value.route if value.route in {"portfolio", "basket", "arbitrage"} else "single_signal"
    financial = QuantBTEndpoint(replace(value.endpoint.config, mode=mode))
    kwargs = dict(positions=output) if mode == "portfolio" else dict(signal=output)
    return financial.backtest(data=value.data, **kwargs)


def decision_equal(a, b):
    assert a.meta["snapshots"][0] == b.meta["snapshots"][0]
    x, y = a.meta["records"][0], b.meta["records"][0]
    for key in ("training_snapshot_id", "training_revision_ids", "family_id", "matured_origins",
                "selected_params", "selected_evaluation_id", "native_selected_evaluation_id",
                "panel_members", "final_selection_reason"):
        assert x[key] == y[key], key
    assert x["proposal"].predictions == y["proposal"].predictions
    assert a.meta["tasks"][0].candidates == b.meta["tasks"][0].candidates
    for x, y in zip(a.meta["models"].values(), b.meta["models"].values(), strict=True):
        # Physical artifact vintages differ; the permitted basis/fit do not.
        assert replace(x, wall_generated_at=y.wall_generated_at) == y


def policy_equal(a, b, *, prepared=False):
    """Numeric implementations share a logical decision, not artifact bytes."""
    assert a.meta["snapshots"][0] == b.meta["snapshots"][0]
    x, y = a.meta["records"][0], b.meta["records"][0]
    for field in ("selected_params", "native_selected_params", "final_selection_reason", "matured_origins"):
        assert x[field] == y[field], field
    ta, tb = a.meta["tasks"][0], b.meta["tasks"][0]
    assert ta.family == tb.family
    assert ta.anchor.candidate_id == tb.anchor.candidate_id
    assert [c.candidate_id for c in ta.candidates] == [c.candidate_id for c in tb.candidates]
    for ca, cb in zip(ta.candidates, tb.candidates, strict=True):
        oa, ob = ca.observation, cb.observation
        for field in ("status", "activity_count", "sample_count", "economics_id", "input_signature"):
            assert getattr(oa, field) == getattr(ob, field), field
        np.testing.assert_allclose([ca.objective, oa.raw_sharpe, oa.sample_std],
                                   [cb.objective, ob.raw_sharpe, ob.sample_std], rtol=1e-10, atol=1e-10)
    for pa, pb in zip(x["proposal"].predictions, y["proposal"].predictions, strict=True):
        assert pa["candidate_id"] == pb["candidate_id"] and pa["eligible"] == pb["eligible"]
        if pa["yhat"] is not None:
            np.testing.assert_allclose([pa["yhat"], pa["qhat"], pa["distance"]],
                                       [pb["yhat"], pb["qhat"], pb["distance"]], rtol=1e-10, atol=1e-10)
    ra = a.result.fold_results[0].result if a.route == "reactive_reset" else a.result
    rb = b.result.fold_results[0].result if b.route == "reactive_reset" else b.result
    if prepared and a.route == "pct_equity":
        for key in ("equity", "returns", "positions"):
            np.testing.assert_allclose(getattr(ra, key), getattr(rb, key), rtol=1e-10, atol=1e-10)
        # Legacy exposes weights, not native fee/funding/margin buffers.
        assert not hasattr(ra, "fees")
        assert "pct_equity_transition" in rb.metadata
    else:
        account_equal(ra, rb, exact=False)
