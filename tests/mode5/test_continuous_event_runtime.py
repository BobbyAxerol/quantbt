"""Synthetic public event WFO qualification, not private-alpha dependency proof."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN
from quantbt.endpoint import _WalkForwardEndpointScorer, _walkforward_scoring_config
from quantbt.mode5.continuous_binding import (
    ContinuousMode5Calibration, continuous_calibration_binding,
)
from quantbt.mode5.continuous_producer import producer_records, validate_result
from quantbt.mode5.dossier.dossier import Dossier
from quantbt.mode5.dossier.evidence import KINDS, Matrix
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.plans import CalibrationPlan
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.integration_contracts import calibration_context
from quantbt.optimization import SamplerConfig
from quantbt.wfo_execution import WfoExecutionWindow

from test_continuous_runtime import continuous_setup


SYMBOL = "ETHUSDT"
ROUTES = [(route, backend) for route in ("event_driven", "order_commands")
    for backend in ("python", "rust")]
PRELOAD = 31 * 24
SCORED = 32 * 24
_builds = []
_callbacks = []


def _commands(bar, timestamp, period, qty):
    common = dict(timestamp=timestamp, symbol=SYMBOL, tif=TimeInForce.GTC)
    if bar in (0, 380, 756):
        return (OrderCommand(**common, side=OrderSide.BUY, qty=qty,
            order_type=OrderType.MARKET, order_id=f"entry-{bar}"),)
    if bar in (period, 384 + period, 762):
        return (OrderCommand(**common, side=OrderSide.SELL,
            qty=.5 if bar == 762 else 1., reduce_only=True,
            order_type=OrderType.MARKET, order_id=f"exit-{bar}"),)
    if bar == 2:
        return (OrderCommand(**common, side=OrderSide.BUY, qty=qty,
            order_type=OrderType.LIMIT, price=80., order_id="terminal-pending"),)
    if bar == 4:
        return (OrderCommand(**common, side=OrderSide.BUY, qty=1e9,
            order_type=OrderType.MARKET, order_id="margin-rejected"),)
    return ()


class SyntheticCallback:
    strategy_version = "continuous-public-synthetic-v1"

    def __init__(self, period, qty):
        self.period, self.qty = period, qty
        self.calls = []

    def on_bar_close(self, context):
        self.calls.append((context.bar_index, context.timestamp, context.positions[SYMBOL]))
        return _commands(context.bar_index, context.timestamp, self.period, self.qty)


@dataclass(frozen=True)
class CallbackFactory:
    period: int
    qty: float

    def __call__(self):
        child = SyntheticCallback(self.period, self.qty)
        _callbacks.append(child)
        return child


def _history(data, params, train_index, test_index):
    assert len(data) == PRELOAD + SCORED
    assert train_index.equals(test_index)
    assert test_index.equals(data.index[PRELOAD:])
    # Preload is consumed by the producer, not supplied by an external closure.
    mean = float(data.close.iloc[:PRELOAD].mean())
    _builds.append((data.index.copy(), dict(params), mean))
    return int(params["period"]), 1.3 if mean > 100. else 1.4


def callback_output(data, params, train_index, test_index, fold):
    period, qty = _history(data, params, train_index, test_index)
    return WfoExecutionWindow("event_driven", test_index,
        strategy_factory=CallbackFactory(period, qty))


def command_output(data, params, train_index, test_index, fold):
    period, qty = _history(data, params, train_index, test_index)
    commands = tuple(c for bar in range(len(test_index) - 1)
        for c in _commands(bar, test_index[bar + 1], period, qty))
    return WfoExecutionWindow("order_commands", test_index, commands=commands)


def event_setup(tmp_path, route, backend):
    builder = callback_output if route == "event_driven" else command_output
    endpoint, frame, ranges, old = continuous_setup(tmp_path, strategy=builder,
        preload_days=31, trials=4)
    financial = QuantBTEndpoint.event_driven(
        input_mode="strategy" if route == "event_driven" else "orders",
        profile="research", backend=backend,
        execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
        initial_capital=20000., leverage=3., fee_rate=.0003, slippage_bps=2.,
        use_funding=True, funding_rate=.0001, qty_step=.5, min_qty=.5,
        min_notional=10., symbols=[SYMBOL])
    config = replace(financial.config, report_level="audit", audit_sink="memory",
        reactive_execution_mode="audit", audit_mode="native_trace")
    source, execution = producer_records(config, builder)
    contract = old.continuous_contract
    b = old.binding.data
    binding = continuous_calibration_binding(geometry=contract.geometry,
        source=source, execution=execution, witness=contract.witness,
        windows=old.windows, reference=old.reference, sampler=SamplerConfig(**b["sampler"]),
        metrics=b["metrics"], selection=b["selection"], batch_size=1)
    context = calibration_context(data=frame, strategy=builder,
        execution_config=config, param_ranges=ranges, binding=binding)
    d = old.dossier.record.data
    dossier = Dossier.create(context=context,
        matrices=tuple(Matrix(Record.of(d["matrices"][k])) for k in KINDS),
        rosters=tuple(Record.of(d["matrices"][k]["roster"]) for k in KINDS),
        inventory=Record.of(old.catalog.require_ref(d["inventory_ref"])),
        inventory_ref=d["inventory_ref"], catalog=old.catalog, axes=d["axes"],
        radar=d["radar"], batteries=d["batteries"],
        assessments=d["recommendations"]["recipes"], limitations=d["limitations"],
        compute_bill=d["compute_bill"])
    spec = deepcopy(old.plan.record.data["recipe"])
    spec["domain"].update(schema_id=context.data["schema"],
        effective_geometry_identity=contract.geometry.identity)
    spec["retention"].update(contract_id="continuous_account_observation_v1",
        runtime_binding_identity=binding.identity)
    spec["reuse"]["selection_policy"] = asdict(old.access)
    plan = CalibrationPlan.search(dossier, {**spec, "search_budget": 4},
        "synthetic original-event continuous WFO proof, no economic claim")
    journal = GovernanceLog(tmp_path / "event-journal")
    journal.seal_dossier(dossier, old.catalog)
    journal.seal_plan(dossier, plan, old.catalog, researcher="test",
        reason=plan.record.data["reason"])
    calibration = ContinuousMode5Calibration(dossier, plan, old.catalog, journal, binding)
    wf = replace(endpoint.config.walkforward_config, target_mode=route,
        mode5_calibration=calibration)
    public = QuantBTEndpoint(replace(endpoint.config, walkforward_config=wf,
        walkforward_target_mode=route, wfo_execution_config=config))
    assert binding.data["metrics"] == b["metrics"]
    assert binding.data["selection"] == b["selection"]
    assert _walkforward_scoring_config(public.config, route) is config
    return public, frame, ranges, calibration


@dataclass
class Study:
    route: str
    backend: str
    endpoint: QuantBTEndpoint
    frame: pd.DataFrame
    calibration: ContinuousMode5Calibration
    result: object
    direct: object
    queries: tuple
    builds: tuple
    callbacks: tuple

    @property
    def wf(self):
        return self.result.metadata["walk_forward_result"]

    @property
    def diagnostics(self):
        return self.wf.metadata["mode5_diagnostics_first"]

    @property
    def retained(self):
        return self.wf.mode5_continuous_accounts


@pytest.fixture(scope="module", params=ROUTES,
    ids=[f"{route}-{backend}" for route, backend in ROUTES])
def study(request, tmp_path_factory):
    route, backend = request.param
    endpoint, frame, ranges, calibration = event_setup(
        tmp_path_factory.mktemp(f"continuous-{route}-{backend}"), route, backend)
    queries = []
    original = _WalkForwardEndpointScorer._score_fallback

    def observe(scorer, data, output, index, report_level=None):
        assert type(scorer) is _WalkForwardEndpointScorer
        assert scorer.score_config is endpoint.config.wfo_execution_config
        query = scorer.mode5_metric_policy.request
        result = original(scorer, data, output, index, report_level)
        queries.append((query, result))
        return result

    _builds.clear()
    _callbacks.clear()
    patch = pytest.MonkeyPatch()
    patch.setattr(_WalkForwardEndpointScorer, "_score_fallback", observe)
    try:
        before = frame.copy(deep=True)
        result = endpoint.backtest(data=frame, param_ranges=ranges)
        pd.testing.assert_frame_equal(frame, before)
        wf = result.metadata["walk_forward_result"]
        selected = wf.oos_output
        scored = frame.loc[selected.index]
        direct_endpoint = QuantBTEndpoint(endpoint.config.wfo_execution_config)
        if route == "event_driven":
            assert len(selected.parts) == 1
            direct = direct_endpoint.backtest(data=scored,
                strategy=selected.parts[0].strategy_factory())
        else:
            direct = direct_endpoint.backtest(data=scored, order_commands=selected.commands,
                datetime_index=selected.index)
        value = Study(route, backend, endpoint, frame, calibration, result, direct,
            tuple(queries), tuple(_builds), tuple(_callbacks))
        print(json.dumps(dict(synthetic_event_study=f"{route}-{backend}",
            trial_states=[r["state"] for r in value.diagnostics["trial_ledger"]],
            effective_query_params=[q.point.params for q, _ in queries],
            original_query_accounts=len(queries), final_accounts=1, direct_checks=1,
            callback_instances=len(value.callbacks), margin_shape=list(result.margin.shape),
            engine=result.metadata["engine"]), sort_keys=True))
        yield value
    finally:
        patch.undo()
        _builds.clear()
        _callbacks.clear()


def _paths_equal(left, right):
    for name in ("equity", "returns", "positions", "closes", "fees", "funding", "margin", "diagnostics"):
        a, b = getattr(left, name), getattr(right, name)
        assert a.index.equals(b.index)
        if isinstance(a, pd.DataFrame):
            assert a.columns.equals(b.columns)
        np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), rtol=0., atol=1e-9)
    assert left.initial_capital == right.initial_capital == 20000.
    assert left.leverage == right.leverage == 3.
    assert left.symbols == right.symbols == [SYMBOL]
    assert left.liquidated == right.liquidated is False
    assert left.liquidation_bar == right.liquidation_bar
    assert [asdict(f) for f in left.fills] == [asdict(f) for f in right.fills]
    assert left.metadata["lifecycle_counters"] == right.metadata["lifecycle_counters"]
    for name in ("active_orders", "order_events", "order_report", "command_report",
            "command_outcome_report_v1", "lifecycle_event_report_v1"):
        assert (name in left.metadata) == (name in right.metadata)
        a, b = left.metadata.get(name), right.metadata.get(name)
        if a is None and b is None:
            continue
        assert isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame)
        pd.testing.assert_frame_equal(a, b)


def test_public_event_config_is_resealed_not_legacy_pct_equity(study):
    c = study.calibration.continuous_contract
    config = study.endpoint.config.wfo_execution_config
    source, execution = producer_records(config, study.endpoint.config.strategy_class)
    assert c.source == source and c.execution == execution
    assert c.execution.data["route"] == config.mode
    assert c.execution.data["economics"]["native_backend"] == study.backend
    assert c.execution.data["clock"]["equity_clock"] == "bar_close"
    assert c.execution.data["clock"]["id"] == EVENT_LIFECYCLE_V3_NEXT_OPEN
    assert Record.of(study.calibration.dossier.record.data["context"]) == calibration_context(data=study.frame,
        strategy=study.endpoint.config.strategy_class, execution_config=config,
        param_ranges={"period": (6, 24, 1)}, binding=study.calibration.binding)
    for _, result in study.queries:
        validate_result(result, execution, config)
    validate_result(study.result, execution, config)
    validate_result(study.direct, execution, config)


def test_public_budget_has_multiple_effective_attempts_and_one_account_per_query(study):
    rows = study.diagnostics["trial_ledger"]
    assert len(rows) == 4
    completed = [r for r in rows if r["state"] == "COMPLETE"]
    assert len(completed) >= 2
    assert len({q.point.effective_json for q, _ in study.queries}) >= 2
    # The selected audit is a distinct, explicit original account, not replay.
    assert len(study.queries) == len(completed) + 1 == len(study.retained.entries)
    for (query, result), (_, account) in zip(study.queries, study.retained.entries, strict=True):
        assert account.request == query
        assert account.execution.financial_execution_count == 1
        np.testing.assert_array_equal(account.observations.equity, result.equity)
    assert study.diagnostics["annual_account_resets"] == 0
    assert study.diagnostics["deployment_authorized"] is False


def test_selected_query_final_and_direct_original_accounts_match(study):
    selected = [(q, r) for q, r in study.queries if q.point.params == study.wf.params]
    assert len(selected) >= 2
    for _, result in selected:
        _paths_equal(result, study.result)
    _paths_equal(study.result, study.direct)
    assert study.result.fees.sum() > 0. and study.result.funding.sum() > 0.
    assert study.result.margin.shape == (SCORED, 2)


def test_actual_next_open_fills_constraints_rejections_and_terminal_state(study):
    result = study.result
    first = result.fills[0]
    assert first.order_id == "entry-0"
    assert first.timestamp == result.equity.index[1]
    assert first.qty == 1.
    assert first.price == pytest.approx(study.frame.loc[first.timestamp, "open"] * 1.0002)
    assert first.fee == pytest.approx(first.price * .0003)
    assert result.positions.iloc[0, 0] == 0.
    assert result.equity.iloc[0] == 20000.
    assert result.positions.iloc[-1, 0] == .5
    assert "margin-rejected" not in {f.order_id for f in result.fills}
    if study.route == "order_commands" and study.backend == "rust":
        assert "order_events" not in result.metadata
        events = result.metadata["lifecycle_event_report_v1"]
        assert "REJECT" in set(events.lifecycle_event_kind)
        assert result.metadata["native_terminal_state_v1"] == dict(
            available=True, authority="rust", reason=None, replayed=False)
    else:
        events = result.metadata["order_events"]
        assert "reject" in set(events.event_name)
    assert result.metadata["lifecycle_counters"]["rejected_count"] == 1
    assert result.metadata["lifecycle_counters"]["pending_command_count"] == 1
    assert result.diagnostics.rejected_orders.sum() == 1
    assert not result.metadata["active_orders"].empty
    assert "terminal-pending" in set(result.metadata["active_orders"].order_id)
    terminal = study.retained.entries[-1][1].execution.terminal_state.data
    assert terminal["equity"] == result.equity.iloc[-1]
    assert terminal["terminal_policy"] == study.calibration.continuous_contract.execution.data["terminal_policy"]


def test_full_preload_is_consumed_but_never_financially_scored(study):
    scored = study.frame.index[PRELOAD:]
    assert len(study.frame) == PRELOAD + SCORED
    assert study.wf.oos_output.index.equals(scored)
    assert study.result.equity.index.equals(scored)
    assert len(study.wf.folds) == 1
    assert study.wf.folds[0].train_index.equals(scored)
    assert study.wf.folds[0].test_index.equals(scored)
    assert study.wf.metadata["prepared_wfo_context"]["bars"] == len(study.frame)
    scope = study.diagnostics["account_scope"]
    assert scope["preload_bars"] == PRELOAD and scope["scored_bars"] == SCORED
    assert scope["preload_account_execution"] is False
    assert study.builds
    for index, _, mean in study.builds:
        assert index.equals(study.frame.index)
        assert mean == float(study.frame.close.iloc[:PRELOAD].mean())
    c = study.calibration.continuous_contract
    assert c.access.purpose == "selection" and c.witness.role == "synthetic"
    for _, account in study.retained.entries:
        assert account.request.role == "formal_search"
        assert account.request.warmup_start_ns == int(study.frame.index[0].value)
        assert account.request.source_identity == c.source.identity
        assert account.request == c.request(study.frame, account.request.point.params)
        np.testing.assert_array_equal(account.observations.times_ns, scored.asi8)


def test_cross_year_views_keep_actual_prior_close_and_positions(study):
    for (query, result), (_, account) in zip(study.queries, study.retained.entries, strict=True):
        first, second = (r.data for r in account.annual_views)
        assert (first["environment_id"], second["environment_id"]) == ("2020", "2021")
        assert first["baseline_equity"] == 20000.
        boundary = result.equity.index.get_loc(pd.Timestamp("2021-01-01", tz="UTC"))
        assert result.positions.iloc[boundary - 1, 0] == 1.
        assert result.positions.iloc[boundary, 0] == 1.
        assert second["baseline_source"] == "prior_actual_close"
        assert second["baseline_equity"] == result.equity.iloc[boundary - 1]
        assert sum(r["money_pnl"] for r in (first, second)) == pytest.approx(
            result.equity.iloc[-1] - 20000., abs=1e-9)
        assert query.point.params["period"] >= 6


def test_fresh_callback_factory_and_no_financial_replay(study):
    for _, result in study.queries:
        metadata = result.metadata
        assert metadata["native_event_backend_requested"] == study.backend
        assert metadata["native_event_backend_resolved"] == study.backend
        assert metadata["wfo_execution_window"]["financial_replays"] == 0
        if study.route == "event_driven":
            assert metadata["primary_engine_runs"] == 1
            assert metadata["oracle_engine_runs"] == 0
        elif study.backend == "rust":
            assert metadata["native_static_execution_boundary_calls"] == 1
            assert metadata["rust_audit_replay"] is False
    if study.route == "event_driven":
        assert len(study.callbacks) == len(study.queries) + 2
        assert len({id(c) for c in study.callbacks}) == len(study.callbacks)
        for child in study.callbacks:
            assert len(child.calls) == SCORED
            assert child.calls[0] == (0, study.frame.index[PRELOAD], 0.)
            assert [r[0] for r in child.calls] == list(range(SCORED))
    else:
        assert study.callbacks == ()


def test_deepcopy_retains_immutable_detached_two_column_margin(study):
    saved = deepcopy(study.retained)
    assert saved.metadata() == study.retained.metadata()
    for (_, original), (_, copied), (_, result) in zip(
            study.retained.entries, saved.entries, study.queries, strict=True):
        assert copied.identity == original.identity
        assert not copied.observations.equity.flags.writeable
        assert not np.shares_memory(original.observations.equity, result.equity.to_numpy())
        for stream in copied.streams:
            raw = getattr(result, stream.name).to_numpy()
            if raw.ndim == 2 and raw.shape[1] == 1:
                raw = raw[:, 0]
            np.testing.assert_array_equal(stream.values, raw)
            assert not stream.values.flags.writeable
            assert not np.shares_memory(stream.values, raw)
            with pytest.raises(ValueError):
                stream.values.setflags(write=True)
        margin = next(s.values for s in copied.streams if s.name == "margin")
        assert margin.shape == (SCORED, 2)
    query_result = study.queries[0][1]
    before = query_result.margin.copy(deep=True)
    try:
        query_result.margin.iloc[:] = -123.
        assert saved.metadata() == study.retained.metadata()
        for retained in (saved, study.retained):
            margin = next(s.values for s in retained.entries[0][1].streams if s.name == "margin")
            np.testing.assert_array_equal(margin, before.to_numpy())
    finally:
        query_result.margin.iloc[:] = before.to_numpy()


@pytest.mark.parametrize("drop", [PRELOAD, 1], ids=["all-preload", "one-preload-bar"])
def test_missing_preload_fails_before_financial_execution(study, monkeypatch, drop):
    def forbidden(*args, **kwargs):
        pytest.fail("missing preload reached financial execution")
    monkeypatch.setattr(_WalkForwardEndpointScorer, "_score_fallback", forbidden)
    with pytest.raises(PermissionError, match="preload is not optional"):
        study.endpoint.backtest(data=study.frame.iloc[drop:], param_ranges={"period": (6, 24, 1)})


def test_future_suffix_fails_before_financial_execution(study, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("future suffix reached financial execution")
    monkeypatch.setattr(_WalkForwardEndpointScorer, "_score_fallback", forbidden)
    future = pd.concat([study.frame, study.frame.iloc[-1:].set_axis(
        pd.DatetimeIndex([study.frame.index[-1] + pd.Timedelta(hours=1)]))])
    with pytest.raises(PermissionError, match="future suffix"):
        study.endpoint.backtest(data=future, param_ranges={"period": (6, 24, 1)})
    with pytest.raises(PermissionError, match="prefix"):
        study.calibration.continuous_contract.request(future, study.wf.params)
