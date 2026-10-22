"""Synthetic same-contract proofs; no alpha, real market or optimizer runs."""

from dataclasses import fields

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig, ExecutionContract, InstrumentSpec, IntrabarIntentTape,
    IntrabarLevelMode, IntrabarSessionTape, QuantBTEndpoint, SessionExecutionPolicy,
    prepare_market_tape, run_intrabar_reference, run_intrabar_session_kernel,
)
from quantbt.core.intrabar_reference import IntrabarEventFlag
from quantbt.endpoint import PreparedIntrabarRunner
from quantbt.metrics.performance import compute_performance_metrics
from quantbt.optimization.meta_selection.observer import (
    ResultMetricAdapter, canonical_metric_contract, market_signature,
)
from quantbt.optimization.meta_selection.records import OutcomeStatus
from quantbt.wfo_execution import WfoExecutionWindow, execute_window
from tools.mode4_quarterly.contracts import quarterly_calendar
from tools.mode4_quarterly.execution import FIRST_ACTION_CONVENTION, IntrabarEvaluationContext
from tools.mode4_quarterly.selection import score_candidate


@pytest.fixture
def native():
    return pytest.importorskip("_quantbt_native", reason="explicit native sidecar needs existing extension")


def frame(n=8, *, start="2021-01-01", rows=None):
    data = pd.DataFrame(dict(open=100., high=100., low=100., close=100., volume=1000.),
                        index=pd.date_range(start, periods=n, freq="h", tz="UTC"))
    for i, changes in (rows or {}).items():
        for name, value in changes.items():
            data.loc[data.index[i], name] = value
    return data


def intent(sides, **kwargs):
    return IntrabarIntentTape.from_arrays(entry_side=sides,
        entry_size=np.abs(np.sign(sides)).astype(float), **kwargs)


def sliced(tape, start, stop):
    return IntrabarIntentTape(**{f.name: getattr(tape, f.name) if f.name == "level_mode"
        or getattr(tape, f.name) is None else getattr(tape, f.name)[start:stop]
        for f in fields(tape)})


def oracles(data, tape, spec=None):
    spec = spec or InstrumentSpec("X")
    market = prepare_market_tape(data=data, symbols=["X"], use_funding=False)
    session = IntrabarSessionTape(np.zeros(len(data), np.int64),
        np.ones(len(data), bool), np.zeros(len(data), bool))
    kwargs = dict(tape=market, intent=tape,
        account=AccountConfig(initial_capital=20_000., leverage=1., maintenance_ratio=.005),
        contract=ExecutionContract.intrabar_bracket(close_on_last_bar=True),
        fee_rate=.0004, slippage_rate=0., contract_size=spec.contract_size,
        sizing_mode="fixed_notional", fixed_notional=2_000.,
        qty_step=spec.lot_size, min_qty=spec.min_qty,
        min_notional=spec.min_notional, tick_size=spec.tick_size,
        session_policy=SessionExecutionPolicy(entry_position_policy="flat_only",
                                             cancel_pending_on_session_change=False),
        session_tape=session)
    return (run_intrabar_reference(**kwargs),
            run_intrabar_session_kernel(**kwargs, report_level="audit"))


def assert_parity(result, reference, numba):
    for other in (reference, numba):
        for name in ("equity", "fees", "funding"):
            np.testing.assert_allclose(getattr(result, name), getattr(other, name), rtol=0., atol=1e-9)
        np.testing.assert_allclose(result.positions.iloc[:, 0], other.position, rtol=0., atol=1e-9)
        for name in ("average_entry", "active_stop", "active_take_profit"):
            np.testing.assert_allclose(result.diagnostics[name], getattr(other, name), rtol=0., atol=1e-9)
        np.testing.assert_array_equal(result.diagnostics.event_flags, other.event_flags)
        assert result.liquidated == other.liquidated
        assert result.liquidation_bar == other.liquidation_bar
        assert len(result.fills) == len(other.fills)
        for actual, expected in zip(result.fills, other.fills, strict=True):
            assert (actual.bar_index, actual.sequence, actual.timestamp, actual.side, actual.reason) == (
                expected.bar_index, expected.sequence, expected.timestamp, expected.side, expected.reason)
            np.testing.assert_allclose([actual.qty, actual.price, actual.fee],
                                      [expected.qty, expected.price, expected.fee], rtol=0., atol=1e-9)
    np.testing.assert_allclose(result.margin.initial_margin, numba.initial_margin, rtol=0., atol=1e-9)
    np.testing.assert_allclose(result.margin.maintenance_margin, numba.maintenance_margin, rtol=0., atol=1e-9)


@pytest.mark.parametrize("side", (-1, 1))
def test_fixed_notional_actual_fill_distance_and_final_flat(native, side):
    data = frame(rows={1: dict(open=120., high=124., low=119., close=122.),
                       2: dict(open=123., high=125., low=122., close=124.)})
    tape = intent([side, 0, 0, 0, 0, 0, 0, side], stop_value=np.full(8, 30.),
        take_profit_value=np.full(8, 40.), level_mode=IntrabarLevelMode.PRICE_DISTANCE)
    with IntrabarEvaluationContext(data, symbol="X") as context:
        evaluated = context.evaluate(tape, data.index, {"side": side}, report_level="audit")
    result = evaluated.original_result
    assert_parity(result, *oracles(data, tape))
    assert result.positions.iloc[0, 0] == 0.
    assert result.fills[0].bar_index == 1
    assert result.fills[0].qty == pytest.approx(2000. / 120.)
    assert result.fills[0].fee == pytest.approx(.8)
    assert result.diagnostics.active_stop.iloc[1] == 120. - side * 30.
    assert result.diagnostics.active_take_profit.iloc[1] == 120. + side * 40.
    assert result.fills[-1].reason.value == "final_close"
    assert result.positions.iloc[-1, 0] == 0.
    assert len(result.fills) == 2  # Last close's opportunity is not executed.
    assert evaluated.metadata["intent_shift_bars"] == 0
    assert evaluated.metadata["boundary_calls"] == 1
    assert evaluated.metadata["python_callbacks"] == 0
    assert evaluated.metadata["boundary_transferred_bytes"] is None


@pytest.mark.parametrize(("case", "rows", "exit_price", "reason"), [
    ("ambiguous", {1: dict(high=112., low=94.)}, 95., "stop_loss"),
    ("stop_gap", {2: dict(open=80., high=85., low=75., close=82.)}, 80., "stop_loss"),
    ("tp_gap", {2: dict(open=120., high=125., low=119., close=122.)}, 108., "take_profit"),
])
def test_protection_fees_and_conservative_gap_policy(native, case, rows, exit_price, reason):
    data = frame(rows=rows)
    tape = intent([1, 0, 0, 0, 0, 0, 0, 0], stop_value=np.full(8, .05),
                  take_profit_value=np.full(8, .08))
    with IntrabarEvaluationContext(data, symbol="X") as context:
        result = context.evaluate(tape, data.index, {"case": case}, report_level="audit").original_result
    assert_parity(result, *oracles(data, tape))
    assert result.fills[-1].price == exit_price
    assert result.fills[-1].reason.value == reason
    fees = (100. + exit_price) * 20. * .0004
    assert result.fees.sum() == pytest.approx(fees)
    assert result.equity.iloc[-1] == pytest.approx(20_000. + (exit_price - 100.) * 20. - fees)
    assert result.metadata["ambiguity_count"] == (1 if case == "ambiguous" else 0)


def test_flat_only_conflict_and_protection_reentry(native):
    data = frame(rows={4: dict(low=94.)})
    tape = intent([1, -1, 1, 0, 1, 0, 0, 0], exit_long=[False, True] + [False] * 6,
                  stop_value=np.full(8, .05))
    with IntrabarEvaluationContext(data, symbol="X") as context:
        result = context.evaluate(tape, data.index, {}, report_level="audit").original_result
    assert_parity(result, *oracles(data, tape))
    assert result.positions.iloc[2, 0] == 0.  # Invested opportunity blocked before technical exit.
    assert int(result.diagnostics.event_flags.iloc[2]) & int(IntrabarEventFlag.FLAT_ONLY_BLOCKED)
    assert [f.reason.value for f in result.fills] == [
        "entry", "technical_exit", "entry", "stop_loss", "entry", "final_close"]
    assert [f.bar_index for f in result.fills] == [1, 2, 3, 4, 5, 7]


def test_overnight_signal_and_position_do_not_reset(native):
    data = frame(50)
    sides = np.zeros(50, np.int8)
    sides[[23, 24, 47]] = [1, -1, -1]
    tape = intent(sides)
    with IntrabarEvaluationContext(data, symbol="X") as context:
        result = context.evaluate(tape, data.index, {}, report_level="audit").original_result
    assert_parity(result, *oracles(data, tape))
    assert result.fills[0].bar_index == 24
    assert result.positions.iloc[48, 0] == 20.
    assert len(result.fills) == 2
    policy = result.metadata["session_policy"]
    assert policy["cancel_pending_on_session_change"] is False
    assert policy["max_long_entries_per_session"] is None
    assert policy["max_short_entries_per_session"] is None
    assert result.metadata["session_reset_count"] == 0


@pytest.mark.parametrize("spec", [
    InstrumentSpec("X", lot_size=3., tick_size=.5, min_qty=3.),
    InstrumentSpec("X", contract_size=2., lot_size=3., tick_size=.5, min_qty=3.),
    InstrumentSpec("X", min_notional=2500.),
    InstrumentSpec("X", min_qty=30.),
])
def test_instrument_rounding_and_rejection(native, spec):
    data = frame(rows={1: dict(open=123., high=124., low=122., close=123.)})
    tape = intent([1, 0, 0, 0, 0, 0, 0, 0])
    with IntrabarEvaluationContext(data, symbol="X", instrument=spec) as context:
        result = context.evaluate(tape, data.index, {}, report_level="audit").original_result
    assert_parity(result, *oracles(data, tape, spec))
    if spec.lot_size:
        assert result.fills[0].qty == np.floor(2000. / (123. * spec.contract_size) / 3.) * 3.
    else:
        assert len(result.fills) == 0
        assert result.metadata["rejected_count"] == 1


def test_short_gap_liquidation_keeps_censoring_and_daily_support(native):
    data = frame(48, rows={25: dict(open=1500., high=1510., low=1490., close=1500.)})
    sides = np.zeros(48, np.int8)
    sides[23] = -1
    tape = intent(sides)
    with IntrabarEvaluationContext(data, symbol="X") as context:
        evaluated = context.evaluate(tape, data.index, {}, report_level="audit")
    result = evaluated.original_result
    assert_parity(result, *oracles(data, tape))
    assert result.liquidated and result.liquidation_bar == 25
    assert result.fills[-1].reason.value == "liquidation"
    assert evaluated.meta_observation.status == OutcomeStatus.CENSORED
    assert evaluated.daily_returns[0].value == 0.
    assert evaluated.daily_returns[1].status == "BANKRUPT"
    assert evaluated.daily_returns[1].value is None


def test_prefix_window_leakage_and_exact_wfo_first_action(native):
    data = frame(96)
    sides = np.zeros(96, np.int8)
    sides[[0, 23, 24, 71, 72]] = [1, -1, 1, -1, 1]
    tape = intent(sides)
    index = data.index[24:72]
    with IntrabarEvaluationContext(data, symbol="X") as context:
        evaluated = context.evaluate(sliced(tape, 0, 72), index, {"warmup": 24}, report_level="audit")
        window = next(iter(context._windows.values()))
        output = WfoExecutionWindow("intrabar", index,
            intent=pd.DataFrame({"entry_signal": sides[24:72].astype(float)}, index=index),
            session=window.runner.session_tape)
        public = execute_window(window.runner.endpoint.config, data, output, symbols=["X"])
        tape.entry_side[:24] = 0
        tape.entry_side[72:] = -1
        data.iloc[:24] = 500.
        data.iloc[72:] = 900.
        repeat = context.evaluate(tape, index, {"warmup": 999}, report_level="audit")
    future = frame(96)
    future.iloc[72:] = 900.
    with IntrabarEvaluationContext(future, symbol="X") as context:
        changed_future = context.evaluate(tape, index, {}, report_level="audit")
    result = evaluated.original_result
    assert_parity(result, *oracles(frame(96).iloc[24:72], sliced(tape, 24, 72)))
    pd.testing.assert_series_equal(result.equity, public.equity)
    pd.testing.assert_frame_equal(result.positions, public.positions)
    pd.testing.assert_series_equal(result.equity, repeat.original_result.equity)
    assert result.equity.iloc[0] == 20_000. and result.fees.iloc[0] == 0.
    assert result.positions.iloc[0, 0] == 0. and result.fills[0].bar_index == 1
    assert evaluated.meta_observation == repeat.meta_observation
    assert evaluated.meta_observation == changed_future.meta_observation
    assert evaluated.metadata["first_action_convention"] == FIRST_ACTION_CONVENTION
    assert evaluated.metadata["prior_intent_injected"] is False


def test_one_365d_account_supplies_canonical_raw_and_floor_returns(native, monkeypatch):
    fold = quarterly_calendar()[0]
    data = frame(365 * 24, start=fold.is_start)
    t = np.arange(len(data))
    close = 100. + 4. * np.sin(t / 19.)
    for name in ("open", "high", "low", "close"):
        data[name] = close
    tape = intent(np.where(t % 48 == 0, 1, 0),
                  technical_exit=t % 48 == 24)
    runs = []
    original_run = PreparedIntrabarRunner.run

    def counted(self, *args, **kwargs):
        result = original_run(self, *args, **kwargs)
        runs.append(result)
        return result

    monkeypatch.setattr(PreparedIntrabarRunner, "run", counted)
    with IntrabarEvaluationContext(data, symbol="X") as context:
        evaluated = context.evaluate(tape, data.index, {"control": "synthetic"}, is_window=True)
        assert context.metadata["physical_account_attempts"] == 1
        assert context.metadata["witness"]["market_misses"] == 1
    result = evaluated.original_result
    assert len(runs) == 1 and runs[0] is result
    assert len(evaluated.daily_returns) == 365
    expected = result.daily_returns
    assert len(expected) == 364  # Frozen raw public policy excludes initial day.
    np.testing.assert_allclose([r.value for r in evaluated.daily_returns[1:]], expected, rtol=0., atol=1e-14)
    assert evaluated.daily_returns[0].value == pytest.approx(result.daily_equity.iloc[0] / 20_000. - 1.)
    assert evaluated.daily_returns[0].value != 0.
    observation = ResultMetricAdapter(canonical_metric_contract()).observe(result,
        expected_index=data.index, economics_id=evaluated.meta_observation.economics_id,
        input_signature=market_signature(data, data.index))
    assert observation == evaluated.meta_observation
    assert observation.sample_count == 364 and observation.status == OutcomeStatus.VALID
    for oracle in oracles(data, tape):
        bar_returns = oracle.equity.pct_change().fillna(0.)
        report = compute_performance_metrics(timestamps=data.index, equity=oracle.equity,
            returns=bar_returns, positions=oracle.position, symbols=["X"],
            initial_capital=20_000., trading_days=365)
        assert observation.raw_sharpe == pytest.approx(report["sharpe"], abs=1e-12)
        assert observation.activity_count == report["num_trades"]
    scored = score_candidate("synthetic", evaluated.daily_returns,
                             fold=fold, information_as_of=fold.is_end)
    assert scored.status == "VALID"
    assert [r.valid_days for r in scored.segments] == [91, 91, 91, 92]
    assert evaluated.metadata["raw_and_floor_same_physical_account"] is True


def test_cache_reuses_only_preparation_and_never_accounts(native):
    data = frame(72)
    tape = intent([1] + [0] * 71)
    params = {"nested": {"values": [1, 2]}}
    context = IntrabarEvaluationContext(data, symbol="X", max_windows=1)
    with context:
        first = context.evaluate(tape, data.index[:48], params, report_level="audit")
        retained_equity = first.original_result.equity.copy()
        window = next(iter(context._windows.values()))
        core = window.runner.rust_prepared_market
        assert window.runner.endpoint.result is None and window.runner.endpoint.engine is None
        assert core.cache.diagnostics["tiers"]["request"]["entry_count"] == 0
        tape.entry_side[0] = 0
        first.original_result.metadata["profile_metadata"]["account"]["initial_capital"] = 1.
        params["nested"]["values"].append(3)
        data.loc[:, "close"] = 150.
        second = context.evaluate(tape, data.index[:48], params)
        assert next(iter(context._windows.values())).runner.rust_prepared_market is core
        assert second.original_result.equity.iloc[-1] == 20_000.
        assert first.original_result.equity.iloc[-1] < 20_000.
        assert first.params["nested"]["values"] == (1, 2)
        assert second.metadata["window_cache_hit"] is True
        assert second.original_result.metadata["profile_metadata"]["account"]["initial_capital"] == 20_000.
        assert context.metadata["witness"]["header_hits"] == 1
        with pytest.raises(ValueError):
            context._data["close"].to_numpy().setflags(write=True)
        context.evaluate(tape, data.index[24:], {})
        assert context.metadata["prepared_windows"] == 1
        assert context.metadata["preparations"] == 2
    assert context.metadata["closed"] is True
    assert context.metadata["prepared_windows"] == 0
    pd.testing.assert_series_equal(first.original_result.equity, retained_equity)
    context.close()
    with pytest.raises(RuntimeError, match="closed"):
        context.evaluate(tape, data.index, {})


@pytest.mark.parametrize("drop", ([10], list(range(24, 48))))
def test_floor_does_not_fabricate_missing_or_cross_gap_days(native, drop):
    data = frame(96).drop(frame(96).index[drop])
    with IntrabarEvaluationContext(data, symbol="X") as context:
        evaluated = context.evaluate(intent(np.zeros(len(data))), data.index, {})
    days = evaluated.daily_returns
    assert len(days) == 4
    if drop == [10]:
        assert [d.status for d in days] == ["UNAVAILABLE", "UNAVAILABLE", "VALID", "VALID"]
    else:
        assert [d.status for d in days] == ["VALID", "UNAVAILABLE", "UNAVAILABLE", "VALID"]
    assert all(d.value is None for d in days if d.status == "UNAVAILABLE")
    assert evaluated.meta_observation.status == OutcomeStatus.NO_VARIANCE


def test_validation_rejects_silent_alignment_and_policy_changes():
    data = frame(48)
    tape = intent(np.zeros(48))
    with IntrabarEvaluationContext(data, symbol="X") as context:
        for index in (data.index.tz_localize(None), data.index[::-1], data.index[:0], data.index[[0, 0]]):
            with pytest.raises(ValueError, match="DatetimeIndex"):
                context.evaluate(tape, index, {})
        with pytest.raises(ValueError, match="contiguous subset"):
            context.evaluate(tape, data.index.delete(4), {})
        with pytest.raises(ValueError, match="full-prefix"):
            context.evaluate(intent(np.zeros(24)), data.index[24:], {})
        with pytest.raises(ValueError, match="365"):
            context.evaluate(tape, data.index, {}, is_window=True)
        with pytest.raises(ValueError, match="report_level"):
            context.evaluate(tape, data.index, {}, report_level="score")
        with pytest.raises(TypeError, match="IntrabarIntentTape"):
            context.evaluate(data, data.index, {})
        with pytest.raises(TypeError, match="mapping"):
            context.evaluate(tape, data.index, None)


def test_native_failure_is_not_a_fallback_or_cached_account(monkeypatch):
    data = frame()

    def unavailable(*args, **kwargs):
        raise RuntimeError("native extension unavailable")

    monkeypatch.setattr(QuantBTEndpoint, "prepare_intrabar", unavailable)
    with IntrabarEvaluationContext(data, symbol="X") as context:
        with pytest.raises(RuntimeError, match="native extension unavailable"):
            context.evaluate(intent([1] + [0] * 7), data.index, {})
        assert context.metadata["prepared_windows"] == 0
        assert context.metadata["physical_account_attempts"] == 0


def test_failed_intent_does_not_poison_prepared_handle(native):
    data = frame()
    bad = intent([1] + [0] * 7)
    bad.entry_size[0] = np.nan
    with IntrabarEvaluationContext(data, symbol="X") as context:
        with pytest.raises(ValueError, match="finite"):
            context.evaluate(bad, data.index, {})
        window = next(iter(context._windows.values()))
        assert window.runner.endpoint.result is None and window.runner.endpoint.engine is None
        good = context.evaluate(intent([1] + [0] * 7), data.index, {}, report_level="audit")
        assert good.metadata["window_cache_hit"] is True
        assert good.original_result.equity.iloc[0] == 20_000.
        assert good.original_result.fees.sum() == pytest.approx(1.6)
        assert context.metadata["physical_account_attempts"] == 2


@pytest.mark.parametrize(("n", "status", "samples"), [
    (1, OutcomeStatus.INSUFFICIENT_SAMPLE, 1),
    (8, OutcomeStatus.NO_VARIANCE, 8),
])
def test_raw_support_and_partial_floor_day_remain_explicit(native, n, status, samples):
    data = frame(n)
    with IntrabarEvaluationContext(data, symbol="X") as context:
        evaluated = context.evaluate(intent(np.zeros(n)), data.index, {})
    assert evaluated.meta_observation.status == status
    assert evaluated.meta_observation.sample_count == samples
    assert evaluated.daily_returns[0].status == "UNAVAILABLE"
    assert evaluated.daily_returns[0].value is None
