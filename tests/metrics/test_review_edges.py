"""Independent MET-03 recheck cases, never execution or scientific repairs."""

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import ReportingRequest
from quantbt.metrics.reporting.adapters import account_from_completed
from quantbt.metrics.reporting.account import reduce_account
from quantbt.metrics.reporting.execution import ExecutionObservations
from quantbt.metrics.reporting.inputs import AccountObservations, ReturnObservations
from quantbt.metrics.reporting.ledger import reduce_ledger
from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome
from quantbt.metrics.reporting.public import build_completed_report, format_metric_value

from .test_account_reducers import coverage, policy
from .test_ledger_reducers import ledger_coverage, ledger_policy
from .reference_oracle import drawdown_episodes


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
@pytest.mark.parametrize("timezone", ["UTC", "Asia/Ho_Chi_Minh", None])
def test_review_completed_index_resolution_is_nanoseconds(unit, timezone):
    times = pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC")
    index = times.tz_convert(timezone) if timezone else times.tz_localize(None)
    index = index.as_unit(unit)
    result = SimpleNamespace(equity=pd.Series([99., 110., 105.], index=index))
    contract = replace(policy([int(times[0].value), int(times[-1].value)]), sampling="observed_bar")
    request = ReportingRequest(account=contract, result_identity="resolution",
        partial_mask=(False,) * 3, return_witness="three recorded hourly bars",
        naive_timezone="UTC" if timezone is None else None, retain_episodes=True)
    observed = account_from_completed(result, contract, result_identity="resolution", naive_timezone=request.naive_timezone)
    np.testing.assert_array_equal(observed.times_ns, times.as_unit("ns").asi8)
    report = build_completed_report(result, request).to_metadata()
    metrics = {m["metric_id"]: m for m in report["groups"]["account_period"]["metrics"]}
    assert metrics["reporting.account.total_return"]["value"] == pytest.approx(.05)
    assert report["groups"]["account_period"]["drawdown_episodes"][0]["elapsed_ns"] == 3_600_000_000_000
    assert result.equity.index.dtype == index.dtype
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("backend", ["python", "numba"])
def test_review_partially_closed_action_keeps_realized_closed_legs_and_shared_cost(backend):
    rows = (
        RecordedOutcome(trade_id="closed-long", symbol="ETH", side="long", currency="USDT",
            action_id="basket", opened_at_ns=0, closed_at_ns=10, close_sequence=0,
            net_pnl=10., open_unrealized_pnl=None),
        RecordedOutcome(trade_id="open-short", symbol="BTC", side="short", currency="USDT",
            action_id="basket", opened_at_ns=0, closed_at_ns=None, close_sequence=1,
            net_pnl=-1., open_unrealized_pnl=3.),
    )
    obs = LedgerObservations(records=rows, coverage=ledger_coverage(2), matching="position_episode",
        valuation_time_ns=30, rosters=(ActionRoster(action_id="basket", outcome_ids=("closed-long", "open-short"),
            shared_net_adjustment=-2., allocation_witness="observed shared cost at valuation end"),))
    action = reduce_ledger(obs, ledger_policy("closed_action"), backend=backend)
    trade = reduce_ledger(obs, ledger_policy(), backend=backend)
    assert action.metric("closed_action.closed_count").value == 0
    assert action.metric("closed_action.open_at_observation_end_count").value == 1
    # +10 realized by the closed leg, -1 realized on the open leg, -2 shared.
    assert action.metric("closed_action.open_realized_net_pnl").value == 7
    assert action.metric("closed_action.open_unrealized_pnl").value == 3
    assert trade.metric("closed_trade.net_pnl").value == 10
    assert trade.metric("closed_trade.open_realized_net_pnl").value == -1
    assert rows == obs.records


@pytest.mark.parametrize("valuation", [None, 20, 40])
@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_review_open_pnl_never_claims_zero_without_matched_valuation(unit, valuation):
    row = RecordedOutcome(trade_id="closed", action_id="action", symbol="BTC", side="long",
        currency="USDT", closed_at_ns=10, close_sequence=0, net_pnl=4.)
    obs = LedgerObservations(records=(row,), coverage=ledger_coverage(1), matching="position_episode",
        valuation_time_ns=valuation, rosters=(ActionRoster(action_id="action", outcome_ids=("closed",),
            shared_net_adjustment=0., allocation_witness="recorded"),))
    report = reduce_ledger(obs, ledger_policy(unit))
    assert report.metric(unit + ".net_pnl").value == 4
    for suffix in ("open_realized_net_pnl", "open_unrealized_pnl", "open_at_observation_end_count"):
        assert report.metric(unit + "." + suffix).status == "unavailable"
        assert report.metric(unit + "." + suffix).value is None


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_review_observed_empty_open_population_is_real_zero(unit):
    obs = LedgerObservations(records=(), coverage=ledger_coverage(0), matching="position_episode", valuation_time_ns=30)
    report = reduce_ledger(obs, ledger_policy(unit))
    for suffix in ("open_realized_net_pnl", "open_unrealized_pnl", "open_at_observation_end_count"):
        assert report.metric(unit + "." + suffix).value == 0
        assert report.metric(unit + "." + suffix).status == "valid"


@pytest.mark.parametrize("kind", ["account", "returns", "execution", "completed"])
def test_review_nat_timestamp_is_not_a_valid_integer_clock(kind):
    missing = np.iinfo(np.int64).min
    with pytest.raises(ValueError, match="timestamp|NaT"):
        if kind == "account":
            AccountObservations(times_ns=[missing, 0], equity=[100., 90.], coverage=coverage())
        elif kind == "returns":
            ReturnObservations(end_times_ns=[missing, 0], values=[0., -.1], partial_mask=[False, False],
                sampling="observed_bar", witness="invalid missing timestamp")
        elif kind == "execution":
            ExecutionObservations(coverage=coverage(), currency="USDT", scope_start_ns=missing,
                scope_end_ns=0, witness="invalid missing timestamp", times_ns=[missing, 0], paths=(("fees", [0., 0.]),))
        else:
            result = SimpleNamespace(equity=pd.Series([100., 90.], index=pd.to_datetime([None, 0], utc=True)))
            account_from_completed(result, policy([0, 0]), result_identity="missing")


def test_review_fractional_mean_holding_bars_is_not_rounded_to_a_count():
    assert format_metric_value(1.5, "bars", "USDT") == "1.5 bars"
    assert format_metric_value(2., "count", "USDT") == "2"


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_review_open_gross_outcome_costs_and_missing_allocations(unit):
    row = RecordedOutcome(trade_id="open", action_id="A", symbol="ETH", side="long",
        currency="USDT", closed_at_ns=None, close_sequence=0, gross_pnl=10.,
        allocated_fee=2., allocated_funding_cost=-1., allocated_slippage_cost=3., open_unrealized_pnl=4.)
    obs = LedgerObservations(records=(row,), coverage=ledger_coverage(1), matching="position_episode",
        valuation_time_ns=30, rosters=(ActionRoster(action_id="A", outcome_ids=("open",),
            shared_net_adjustment=-2., allocation_witness="scope-end observed adjustment"),))
    for basis, expected in (("included_in_fill_price", 9), ("recorded_separate_cost", 6)):
        report = reduce_ledger(obs, ledger_policy(unit, slippage_basis=basis))
        assert report.metric(unit + ".open_realized_net_pnl").value == expected - (2 if unit == "closed_action" else 0)
        assert report.metric(unit + ".open_unrealized_pnl").value == 4
        missing = replace(obs, records=(replace(row, allocated_fee=None),))
        missing_report = reduce_ledger(missing, ledger_policy(unit, slippage_basis=basis))
        assert missing_report.metric(unit + ".open_realized_net_pnl").status == "unavailable"
        assert missing_report.metric(unit + ".open_unrealized_pnl").value == 4


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("tolerance", [0., .001])
def test_review_random_drawdown_oracle_clocks_negative_equity_and_cache_free_parity(seed, tolerance):
    rng = np.random.default_rng(seed)
    times = np.cumsum(rng.integers(1, 10**11, 127, dtype=np.int64))
    marks = rng.uniform(-30., 150., len(times)).round(1)
    observations = AccountObservations(times_ns=times, equity=marks, coverage=coverage())
    contract = policy(times, recovery_relative_tolerance=tolerance)
    expected = drawdown_episodes(times.tolist(), marks.tolist(), 100., int(times[0]), recovery_tolerance=tolerance)
    reports = [reduce_account(observations, contract, backend=backend, retain_episodes=True)
               for backend in ("python", "numba")]
    for report in reports:
        assert report.episodes.to_rows() == expected["episodes"]
        assert report.metric("drawdown.max_depth").value == pytest.approx(expected["max_depth"])
        assert report.metric("drawdown.current_open_duration_ns").value == expected["current_open_duration_ns"]
        assert report.metric("drawdown.longest_duration_ns").value == max(
            (ep["elapsed_ns"] for ep in expected["episodes"]), default=0)
        json.dumps(report.to_metadata(), allow_nan=False)
    for left, right in zip(reports[0].metrics, reports[1].metrics):
        assert left.status == right.status and left.sample_count == right.sample_count
        assert left.value == pytest.approx(right.value) if left.value is not None else right.value is None
