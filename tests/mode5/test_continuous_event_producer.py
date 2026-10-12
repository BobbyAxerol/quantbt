"""Synthetic original-engine qualification only, not five-alpha research evidence."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderCommand, OrderSide, OrderType, QuantBTEndpoint, TimeInForce
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN, get_event_clock_contract
from quantbt.core.results import BacktestResultV2
from quantbt.endpoint import EndpointConfig, _WalkForwardEndpointScorer
from quantbt.mode5.dossier.records import Record
from quantbt.mode5 import event_producer as producer
from quantbt.optimization.meta_selection.observer import economics_identity
from quantbt.wfo_execution import WfoExecutionWindow


SYMBOL = "PUBLIC_SYNTHETIC"


def bars():
    index = pd.date_range("2023-12-31", periods=36, freq="h", tz="UTC")
    close = 100. + np.arange(len(index))
    return pd.DataFrame(dict(open=close-.5, high=close+1., low=close-1.,
        close=close, volume=1000.), index=index)


def command(timestamp, identifier, side=OrderSide.BUY, qty=1.3, **kwargs):
    return OrderCommand(timestamp=timestamp, symbol=SYMBOL, side=side, qty=qty,
        order_type=kwargs.pop("order_type", OrderType.MARKET), tif=TimeInForce.GTC,
        order_id=identifier, **kwargs)


class SyntheticLifecycle:
    strategy_version = "public-synthetic-v1"

    def __init__(self):
        self.callbacks = 0

    def on_bar_close(self, context):
        self.callbacks += 1
        if context.bar_index == 0:
            return (command(context.timestamp, "entry"),)
        if context.bar_index == 2:
            return (command(context.timestamp, "resting", order_type=OrderType.LIMIT, price=80.),)
        if context.bar_index == 10:
            return (command(context.timestamp, "partial", side=OrderSide.SELL, qty=.5, reduce_only=True),)
        if context.bar_index == 35:
            return (command(context.timestamp, "outside", qty=3.),)
        return ()


def endpoint(mode, backend, audit=False, **overrides):
    kwargs = dict(input_mode=mode, profile="research", backend=backend,
        execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN, initial_capital=10000., leverage=5.,
        fee_rate=.0002, use_funding=True, funding_rate=.0001, qty_step=.5, min_qty=.5,
        min_notional=10., slippage_bps=2., symbols=[SYMBOL])
    kwargs.update(overrides)
    value = QuantBTEndpoint.event_driven(**kwargs)
    if audit:
        value = QuantBTEndpoint(replace(value.config, report_level="audit", audit_sink="memory",
            reactive_execution_mode="audit", audit_mode="native_trace"))
    return value


@pytest.fixture(scope="module", params=[(mode, backend, audit)
    for mode in ("strategy", "orders") for backend in ("python", "rust") for audit in (False, True)])
def executed(request):
    mode, backend, audit = request.param
    original = endpoint(mode, backend, audit)
    data = bars()
    strategy = SyntheticLifecycle()
    if mode == "strategy":
        result = original.simulate(data=data, strategy=strategy)
        assert strategy.callbacks == len(data)
    else:
        commands = (command(data.index[1], "entry"),
            command(data.index[3], "resting", order_type=OrderType.LIMIT, price=80.),
            command(data.index[11], "partial", side=OrderSide.SELL, qty=.5, reduce_only=True))
        result = original.simulate(data=data, order_commands=commands)
    source, execution = producer.producer_records(original.config, SyntheticLifecycle)
    return original.config, data, result, source, execution


def test_real_public_event_metadata_paths_and_original_terminal_policy(executed):
    config, data, result, source, execution = executed
    before = deepcopy(result)
    producer.validate_result(result, execution, config)
    assert type(result) is BacktestResultV2
    assert source.data["financial_provider"] == execution.data["economics"]["source_identity"]
    assert execution.data["economics"]["identity"] == economics_identity(config)
    assert execution.data["backend"] == result.metadata["backend"] == "native_event"
    assert execution.data["clock"]["equity_clock"] == "bar_close"
    assert execution.data["clock"]["event_clock_contract"] == get_event_clock_contract(EVENT_LIFECYCLE_V3_NEXT_OPEN).to_metadata()
    assert execution.data["clock"]["command_timestamp_semantics"] == (
        "signal_bar_close" if config.mode == "native_event_strategy" else "effective_bar")
    assert execution.data["initial_state"] == dict(equity=10000., position_policy="flat",
        order_policy="empty", phase="before_first_bar")
    assert execution.data["terminal_policy"]["positions"] == "original_no_forced_flatten"
    assert result.positions.iloc[-1, 0] == .5
    assert result.equity.index.equals(data.index)
    assert result.fees.sum() > 0
    assert result.funding.sum() > 0
    for name in ("equity", "positions", "fees", "funding", "margin"):
        actual, saved = getattr(result, name), getattr(before, name)
        (pd.testing.assert_frame_equal if isinstance(actual, pd.DataFrame) else pd.testing.assert_series_equal)(actual, saved)
    assert result.metadata.keys() == before.metadata.keys()
    assert result.metadata["run_config"] == before.metadata["run_config"]
    if config.mode == "native_event_strategy":
        assert result.metadata["ignored_commands_after_end"] == 1
        assert result.metadata["primary_engine_runs"] == 1
        assert result.metadata["oracle_engine_runs"] == 0
    if config.report_level == "audit":
        assert len(result.fills) == 2
        first = result.fills[0]
        assert first.timestamp == data.index[1]
        assert first.qty == 1.
        assert first.price == pytest.approx(data.open.iloc[1]*1.0002)
        assert first.fee == pytest.approx(first.price*.0002)
        assert not result.metadata["active_orders"].empty


@pytest.mark.parametrize("field", ["backend", "engine", "execution_contract_id", "event_clock_contract",
    "execution_contract", "native_event_backend_requested", "native_event_backend_resolved", "run_config",
    "quantity_constraints", "fee_rate_oneway", "fee_rate", "canonical_one_way_fee_rate", "fee_round_trip",
    "slippage_bps", "slippage", "use_funding", "initial_capital", "leverage", "maintenance_ratio"])
def test_metadata_tamper_and_missing_fields_fail_closed(executed, field):
    config, _, original, _, execution = executed
    result = deepcopy(original)
    result.metadata[field] = "untrusted"
    with pytest.raises(ValueError, match="metadata mismatch"):
        producer.validate_result(result, execution, config)
    del result.metadata[field]
    with pytest.raises(ValueError, match="metadata mismatch"):
        producer.validate_result(result, execution, config)


@pytest.mark.parametrize("field", ["account", "execution", "sizing", "funding", "fees"])
def test_nested_original_run_config_tamper_is_not_self_certification(executed, field):
    config, _, result, _, execution = executed
    altered = deepcopy(result)
    altered.metadata["run_config"][field] = {}
    with pytest.raises(ValueError, match="metadata mismatch"):
        producer.validate_result(altered, execution, config)


@pytest.mark.parametrize("field", ["initial_capital", "leverage", "symbols", "liquidation"])
def test_original_account_fields_differ_from_unmodified_metadata(executed, field):
    config, _, result, _, execution = executed
    result = deepcopy(result)
    if field == "symbols":
        result.symbols = ["OTHER"]
    elif field == "liquidation":
        result.liquidated, result.liquidation_bar = True, len(result.equity)
    else:
        setattr(result, field, getattr(result, field)*2)
    with pytest.raises(ValueError):
        producer.validate_result(result, execution, config)


@pytest.mark.parametrize("path", ["equity", "returns", "positions", "closes", "fees", "funding", "margin"])
def test_nonfinite_or_mismatched_original_financial_paths(executed, path):
    config, _, result, _, execution = executed
    result = deepcopy(result)
    value = getattr(result, path)
    value.iloc[-1] = np.nan
    with pytest.raises(ValueError, match="account path"):
        producer.validate_result(result, execution, config)
    result = deepcopy(executed[2])
    getattr(result, path).index = getattr(result, path).index+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="account path"):
        producer.validate_result(result, execution, config)


@pytest.mark.parametrize("update", [dict(fee_rate=.002), dict(fee=.004), dict(use_funding=False),
    dict(funding_rate=.003), dict(qty_step=.1), dict(lot_size=.1), dict(slot_size=.1),
    dict(min_qty=.1), dict(min_notional=20.), dict(contract_size=2.), dict(symbols=["OTHER"]),
    dict(backend_policy="prefer_compatibility"), dict(reactive_gil_policy="different"),
    dict(audit_mode="native_trace"), dict(oracle_sample_seed=5)])
def test_bound_config_drift_requires_new_qualification(update):
    config = endpoint("strategy", "python").config
    _, execution = producer.producer_records(config, SyntheticLifecycle)
    changed = replace(config, **update)
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(None, execution, changed)


@pytest.mark.parametrize("field,value", [("initial_capital", 20000.), ("leverage", 3.),
    ("maintenance_ratio", .02), ("margin_buffer", .2), ("base_currency", "EUR")])
def test_exact_account_configuration_is_bound(field, value):
    config = endpoint("strategy", "python").config
    _, execution = producer.producer_records(config, SyntheticLifecycle)
    changed = replace(config, account=replace(config.account, **{field: value}))
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(None, execution, changed)


def test_execution_config_and_funding_values_not_only_series_summary_are_bound():
    data = bars()
    funding = pd.Series(.0001, index=data.index, name="funding")
    config = endpoint("strategy", "python", funding_rate=funding).config
    _, execution = producer.producer_records(config, SyntheticLifecycle)
    funding.iloc[5] *= 2
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(None, execution, config)
    changed = replace(config, execution=replace(config.execution, slippage_bps=5.))
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(None, execution, changed)


@pytest.mark.parametrize("update", [dict(mode="pct_equity"), dict(backend="auto"),
    dict(native_backend="auto"), dict(native_backend=None), dict(native_backend="replay_certified"),
    dict(event_engine_version="v1"), dict(native_static_abi="0.4"), dict(execution_contract=None),
    dict(execution_contract="event_lifecycle_v2_next_bar_close"), dict(execution_contract="unknown"),
    dict(reactive_runtime="numeric_every_bar_v1"), dict(reactive_kernel_mode="replay_certified"),
    dict(audit_mode="verify_against_oracle"), dict(oracle_sample_rate=.1)])
def test_unqualified_routes_and_clocks_are_explicit_errors(update):
    config = replace(endpoint("strategy", "python").config, **update)
    with pytest.raises(NotImplementedError):
        producer.producer_records(config, SyntheticLifecycle)


def test_forged_clock_with_a_valid_id_cannot_borrow_registered_semantics():
    clock = replace(get_event_clock_contract(EVENT_LIFECYCLE_V3_NEXT_OPEN), observation_phase="bar_open")
    config = replace(endpoint("strategy", "python").config, execution_contract=clock)
    with pytest.raises(NotImplementedError, match="exact registered"):
        producer.producer_records(config, SyntheticLifecycle)


def test_backend_drift_not_hidden_by_equal_economics():
    python = endpoint("strategy", "python").config
    rust = replace(python, native_backend="rust")
    assert economics_identity(python) == economics_identity(rust)
    ps, pe = producer.producer_records(python, SyntheticLifecycle)
    rs, re = producer.producer_records(rust, SyntheticLifecycle)
    assert ps != rs and pe != re
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(None, pe, rust)


@pytest.mark.parametrize("field", ["reactive_execution_mode", "reactive_kernel_mode", "command_effective_phase",
    "single_pass_accounting_source", "state_owner", "authoritative_mutable_state_count",
    "python_shadow_accounting", "primary_engine_runs", "oracle_engine_runs", "reactive_static_replay_count",
    "single_pass_replay_certified", "static_replay_available"])
def test_reactive_lifecycle_or_replay_metadata_cannot_replace_original_execution(field):
    original = endpoint("strategy", "python")
    result = original.simulate(data=bars(), strategy=SyntheticLifecycle())
    _, execution = producer.producer_records(original.config, SyntheticLifecycle)
    result.metadata[field] = "untrusted"
    with pytest.raises(ValueError, match="metadata mismatch"):
        producer.validate_result(result, execution, original.config)


@pytest.mark.parametrize("mode,backend", [(m, b) for m in ("strategy", "orders") for b in ("python", "rust")])
def test_original_disabled_funding_and_legacy_fee_conversion(mode, backend):
    original = endpoint(mode, backend, use_funding=False, fee_rate=None, fee=.0008)
    data = bars()
    result = (original.simulate(data=data, strategy=SyntheticLifecycle()) if mode == "strategy"
        else original.simulate(data=data, order_commands=(command(data.index[1], "entry"),)))
    _, execution = producer.producer_records(original.config, SyntheticLifecycle)
    producer.validate_result(result, execution, original.config)
    assert result.metadata["fee_rate_oneway"] == .0004
    assert result.funding.sum() == 0.
    result.funding.iloc[-1] = 1.
    with pytest.raises(ValueError, match="disabled funding"):
        producer.validate_result(result, execution, original.config)


def test_matched_callback_commands_python_rust_account_and_terminal_parity():
    data = bars()
    results = []
    for mode in ("strategy", "orders"):
        for backend in ("python", "rust"):
            original = endpoint(mode, backend, audit=True)
            source, execution = producer.producer_records(original.config, SyntheticLifecycle)
            if mode == "strategy":
                result = original.simulate(data=data, strategy=SyntheticLifecycle())
            else:
                result = original.simulate(data=data, order_commands=(
                    command(data.index[1], "entry"),
                    command(data.index[3], "resting", order_type=OrderType.LIMIT, price=80.),
                    command(data.index[11], "partial", side=OrderSide.SELL, qty=.5, reduce_only=True)))
            producer.validate_result(result, execution, original.config)
            assert source.data["financial_provider"] == execution.data["economics"]["source_identity"]
            assert list(result.metadata["active_orders"].order_id) == ["resting"]
            assert not result.liquidated
            assert [f.timestamp for f in result.fills] == [data.index[1], data.index[11]]
            assert [f.qty for f in result.fills] == [1., .5]
            results.append(result)
    reference = results[0]
    for actual in results[1:]:
        for name in ("equity", "returns", "positions", "closes", "fees", "funding", "margin"):
            left, right = getattr(reference, name), getattr(actual, name)
            compare = pd.testing.assert_frame_equal if isinstance(left, pd.DataFrame) else pd.testing.assert_series_equal
            compare(left, right, check_exact=False, rtol=0., atol=1e-9)
        assert actual.initial_capital == reference.initial_capital
        assert actual.leverage == reference.leverage
        assert actual.liquidation_bar == reference.liquidation_bar
        assert [(f.order_id, f.side, f.qty) for f in actual.fills] == [
            (f.order_id, f.side, f.qty) for f in reference.fills]
        assert [f.price for f in actual.fills] == pytest.approx([f.price for f in reference.fills], rel=0., abs=1e-9)
        assert [f.fee for f in actual.fills] == pytest.approx([f.fee for f in reference.fills], rel=0., abs=1e-9)
    entry = data.open.iloc[1]*1.0002
    partial_exit = data.open.iloc[11]*.9998
    fees = (entry+.5*partial_exit)*.0002
    funding = (data.close.iloc[8]+.5*data.close.iloc[[16, 24, 32]].sum())*.0001
    terminal = 10000.+.5*(partial_exit-entry)+.5*(data.close.iloc[-1]-entry)-fees-funding
    assert reference.fees.sum() == pytest.approx(fees, rel=0., abs=1e-9)
    assert reference.funding.sum() == pytest.approx(funding, rel=0., abs=1e-9)
    assert reference.equity.iloc[-1] == pytest.approx(terminal, rel=0., abs=1e-9)


@pytest.mark.parametrize("backend", ["python", "rust"])
def test_provider_source_and_native_binary_drift_without_editing_existing_files(monkeypatch, backend):
    config = endpoint("strategy", backend).config
    _, execution = producer.producer_records(config, SyntheticLifecycle)
    original = Path.read_bytes
    def changed(path):
        contents = original(path)
        if (backend == "python" and path.name == "constraints.py") or (backend == "rust" and path.suffix == ".so"):
            return contents+b"synthetic-drift"
        return contents
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(None, execution, config)


def test_native_source_witness_uses_the_loaded_exact_binary():
    import _quantbt_native._quantbt_native as native
    expected = "2959f5388c6a8e57bdef5a6dafe76da3624ef57dba379f7ca686e9bf202ad26b"
    assert sha256(Path(native.__file__).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("field", ["native_event_rust_available", "native_event_rust_compatible",
    "native_event_rust_fallback_reason"])
def test_native_result_capability_metadata_cannot_drift(field):
    original = endpoint("orders", "rust")
    data = bars()
    result = original.simulate(data=data, order_commands=(command(data.index[1], "entry"),))
    _, execution = producer.producer_records(original.config, SyntheticLifecycle)
    result.metadata[field] = "untrusted"
    with pytest.raises(ValueError, match="metadata mismatch"):
        producer.validate_result(result, execution, original.config)


@pytest.mark.parametrize("mode,backend", [(m, b) for m in ("strategy", "orders") for b in ("python", "rust")])
def test_existing_original_scorer_qualification_and_real_execution_without_replay(mode, backend):
    config = endpoint(mode, backend).config
    source, execution = producer.producer_records(config, SyntheticLifecycle)
    contract = SimpleNamespace(source=source, execution=execution)
    route = "event_driven" if mode == "strategy" else "order_commands"
    data = bars()
    scorer = _WalkForwardEndpointScorer(EndpointConfig(mode="walk_forward", symbols=[SYMBOL],
        wfo_execution_config=config), route, market_data=data)
    assert producer.qualify_producer(scorer, SyntheticLifecycle, contract) == execution
    assert scorer.prepared_cache_metadata()["fallback_runs"] == 0
    output = (WfoExecutionWindow(route, data.index, strategy_factory=SyntheticLifecycle)
        if mode == "strategy" else WfoExecutionWindow(route, data.index,
            commands=(command(data.index[1], "entry"),)))
    class OriginalResultCheck:
        calls = 0
        def score(self, result, index):
            self.calls += 1
            producer.validate_result(result, execution, scorer.score_config)
            assert result.metadata["wfo_execution_window"]["financial_replays"] == 0
            assert index.equals(result.equity.index)
            return {"sharpe": 0.}
    check = OriginalResultCheck()
    scorer.mode5_metric_policy = check
    try:
        assert scorer(data, output, data.index, SimpleNamespace(fold_id=0), {}, "synthetic", 365) == {"sharpe": 0.}
        assert check.calls == scorer.prepared_cache_metadata()["fallback_runs"] == 1
        with pytest.raises(TypeError, match="original public endpoint scorer"):
            producer.qualify_producer(SimpleNamespace(score_config=config), SyntheticLifecycle, contract)
        scorer.score_config = replace(config, fee_rate=.0003)
        with pytest.raises(ValueError, match="continuous binding"):
            producer.qualify_producer(scorer, SyntheticLifecycle, contract)
    finally:
        scorer.release_prepared_state()


def test_typed_inputs_and_forged_execution_record_cannot_certify_an_account(executed):
    config, _, result, _, execution = executed
    with pytest.raises(TypeError, match="EndpointConfig"):
        producer.producer_records(SimpleNamespace(**vars(config)), SyntheticLifecycle)
    with pytest.raises(TypeError, match="BacktestResultV2"):
        producer.validate_result(SimpleNamespace(**vars(result)), execution, config)
    forged = execution.data
    forged["initial_state"]["equity"] *= 2
    with pytest.raises(ValueError, match="drift"):
        producer.validate_result(result, Record.of(forged), config)
