"""Independent arithmetic checks for the approved portfolio-review metrics fixes."""

import json
import math
from statistics import mean, stdev
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt.metrics import performance
from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting.ledger import reduce_ledger
from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
@pytest.mark.parametrize("timezone", ["UTC", "Asia/Ho_Chi_Minh", None])
def test_default_report_daily_grouping_and_annualization_use_timestamp_units(unit, timezone):
    utc = pd.date_range("2025-01-01", periods=8, freq="12h", tz="UTC")
    index = (utc.tz_convert(timezone) if timezone else utc.tz_localize(None)).as_unit(unit)
    equity = np.array([100., 120., 110., 100., 105., 110., 110., 120.])
    report = performance.compute_performance_metrics(
        timestamps=index, equity=equity,
        returns=[0., 1 / 5, -1 / 12, -1 / 11, 1 / 20, 1 / 21, 0., 1 / 11],
        positions=np.zeros((8, 1)), symbols=["A"], initial_capital=100., trading_days=252,
    )

    # UTC daily closes are 120, 100, 110, 120, not the first mark of each day.
    expected_returns = [-1 / 6, 1 / 10, 1 / 11]
    np.testing.assert_array_equal(performance._array_daily_equity(index, equity), [120., 100., 110., 120.])
    assert report["max_dd_duration_days"] == 2
    assert report["avg_dd_duration_days"] == 2
    assert report["max_drawdown_pct"] == pytest.approx(100 / 6)
    assert report["sharpe"] == pytest.approx(mean(expected_returns) / stdev(expected_returns) * math.sqrt(252))
    assert report["sortino"] == pytest.approx(mean(expected_returns) / (1 / 6) * math.sqrt(252))
    assert report["profit_factor"] == pytest.approx(63 / 55)
    assert report["period_expected_return_pct"] == pytest.approx(80 / 99)
    assert report["cagr_pct"] == pytest.approx((1.2 ** (365.25 / 3.5) - 1) * 100)
    population = report["metric_population"]["period_expected_return_pct"]
    assert population["population"] == "observed_daily_equity_returns"
    assert population["sample_count"] == 3
    assert index.unit == unit
    assert str(index.tz) == str(timezone)


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_intraday_annualization_and_additions_preserve_every_legacy_snapshot_value(unit):
    index = pd.to_datetime([
        "2025-01-01T00:00:00Z", "2025-01-01T00:15:00Z",
        "2025-01-01T00:45:00Z", "2025-01-01T01:45:00Z",
    ]).as_unit(unit)
    report = performance.compute_performance_metrics(
        timestamps=index, equity=[20_000., 20_200., 20_099., 20_099.],
        returns=[0., .01, -.005, 0.], positions=[0., 1., 1., 0.],
        symbols=["A"], initial_capital=20_000., trading_days=252,
    )

    # Median spacing is 30 minutes; the bar fallback includes both zero returns.
    annual_periods = 365.25 * 48
    expected_legacy = {
        "initial_capital": 20_000., "final_equity": 20_099.,
        "total_return_pct": .495, "cagr_pct": .495,
        "sharpe": mean([0., .01, -.005, 0.]) / stdev([0., .01, -.005, 0.]) * math.sqrt(annual_periods),
        "sortino": .25 * math.sqrt(annual_periods), "calmar": .99, "omega": 2.,
        "max_drawdown_pct": .5, "avg_drawdown_pct": .5,
        "max_dd_duration_days": 0, "avg_dd_duration_days": 0,
        "profit_factor": 2., "long_hitrate_pct": 50., "short_hitrate_pct": 0.,
        "avg_win_pct": 1., "avg_loss_pct": -.5, "expectancy_pct": -.125,
        "num_trades": 3, "liquidated": False,
    }
    for key, expected in expected_legacy.items():
        assert report[key] == pytest.approx(expected), key
    assert set(report) == set(expected_legacy) | {
        "metric_population", "period_expected_return_pct", "position_state_count",
    }
    assert report["position_state_count"] == report["num_trades"] == 3
    # The coherent mean is positive, unlike the preserved mixed statistic.
    assert report["period_expected_return_pct"] == pytest.approx(.125)
    metadata = report["metric_population"]
    assert metadata["expectancy_pct"]["population"] == "legacy_mixed"
    assert metadata["expectancy_pct"]["label"] == "Legacy Mixed Statistic"
    assert "Not a trade expectancy" in metadata["expectancy_pct"]["description"]
    assert metadata["position_state_count"]["alias_of"] == "num_trades"
    assert metadata["period_expected_return_pct"]["population"] == "finite_bar_returns"
    assert metadata["period_expected_return_pct"]["sample_count"] == 4
    assert metadata["avg_win_pct"]["sample_count"] == 1
    assert metadata["avg_loss_pct"]["sample_count"] == 1
    json.dumps(metadata, allow_nan=False)


@pytest.mark.parametrize("unit", ["ns", "us"])
def test_full_report_preserves_input_paths_and_exposes_population_additions(unit):
    index = pd.date_range("2025-01-01", periods=4, tz="UTC").as_unit(unit)
    equity = pd.Series([100., 90., 95., 100.], index=index)
    positions = pd.DataFrame({"Position_A": [0., 1., 1., 0.]}, index=index)
    result = SimpleNamespace(
        equity=equity, returns=pd.Series([0., -.1, 1 / 18, 1 / 19], index=index),
        positions=positions, symbols=["A"], initial_capital=100., liquidated=False,
    )
    before_equity, before_positions = equity.copy(deep=True), positions.copy(deep=True)
    report = performance.full_report(result)

    assert report["max_dd_duration_days"] == 2
    assert report["period_expected_return_pct"] == pytest.approx(mean([-.1, 1 / 18, 1 / 19]) * 100)
    assert report["position_state_count"] == report["num_trades"] == 3
    assert report["metric_population"]["expectancy_pct"]["population"] == "legacy_mixed"
    pd.testing.assert_series_equal(equity, before_equity)
    pd.testing.assert_frame_equal(positions, before_positions)
    assert equity.index.unit == unit


@pytest.mark.parametrize("returns,population,count,expected_pct", [
    ([np.nan, np.inf, -.01, .03], "finite_bar_returns", 2, 1.),
    ([np.nan, np.inf, -np.inf, np.nan], "equity_return_fallback", 3, 2 / 3),
])
def test_period_mean_metadata_tracks_the_actual_finite_return_fallback(returns, population, count, expected_pct):
    report = performance.compute_performance_metrics(
        timestamps=pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC"),
        equity=[100., 100., 99., 101.97], returns=returns,
        positions=[0., 0., 0., 0.], symbols=["A"], initial_capital=100.,
    )
    assert report["period_expected_return_pct"] == pytest.approx(expected_pct)
    assert report["metric_population"]["period_expected_return_pct"]["population"] == population
    assert report["metric_population"]["period_expected_return_pct"]["sample_count"] == count


def test_initial_flat_symbol_states_are_not_claimed_as_closed_trades():
    report = performance.compute_performance_metrics(
        timestamps=pd.date_range("2025-01-01", periods=2, tz="UTC"),
        equity=[100., 100.], returns=[0., 0.], positions=[[0., 0.], [0., 0.]],
        symbols=["A", "B"], initial_capital=100.,
    )
    assert report["num_trades"] == report["position_state_count"] == 2
    assert report["period_expected_return_pct"] == 0.
    assert report["metric_population"]["num_trades"]["label"] == "Position State Count"
    assert "Not closed trades" in report["metric_population"]["num_trades"]["description"]


def _contract(unit, *, start=0, end=30):
    return ReportingContractV1(
        scope="full" if start == 0 else "scoped", unit=unit, currency="USDT",
        baseline_equity=100., baseline_time_ns=start, scope_end_ns=end,
        sampling="observed_bar", annual_periods=365., equity_clock="recorded_event",
        matching="position_episode", grouping="authoritative_action_id" if unit == "closed_action" else "none",
        ledger_scope="closed_in_scope_lifetime",
    )


def _outcome(name, action, closed_at, net, *, side="long"):
    return RecordedOutcome(
        trade_id=name, action_id=action, symbol=name, side=side, currency="USDT",
        opened_at_ns=0, closed_at_ns=closed_at, close_sequence=0, net_pnl=net,
    )


def _observations(records, horizon):
    grouped = {}
    for row in records:
        grouped.setdefault(row.action_id, []).append(row.trade_id)
    rosters = tuple(
        ActionRoster(action_id=action, outcome_ids=tuple(names),
                     shared_net_adjustment=-2. if action == "basket" else 0.,
                     allocation_witness="recorded shared action cost, allocated once")
        for action, names in grouped.items()
    )
    coverage = ReportingCoverageV1(
        result_identity="portfolio-review-control", producer="authoritative-outcome-control",
        profile="audit", ledger="complete", retained_rows=len(records), dropped_rows=0,
    )
    return LedgerObservations(records=tuple(records), rosters=rosters, coverage=coverage,
                              matching="position_episode", valuation_time_ns=horizon)


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
@pytest.mark.parametrize("horizon", [None, 10, 29])
@pytest.mark.parametrize("empty", [False, True])
def test_complete_ledger_without_reporting_end_coverage_is_unavailable(unit, horizon, empty):
    records = [] if empty else [_outcome("early", "early-action", 10, 7.)]
    observations = _observations(records, horizon)
    report = reduce_ledger(observations, _contract(unit))

    # A complete snapshot at time 10 does not certify the population through 30,
    # even when it contains no outcomes or every retained outcome is closed.
    assert all(metric.status == "unavailable" and metric.value is None for metric in report.metrics)
    assert "horizon" in report.metric(unit + ".closed_count").reason
    metadata = json.loads(report.provenance_json)
    assert metadata["population_complete"] is False
    assert metadata["ledger_valuation_time_ns"] == horizon
    assert observations.coverage.ledger == "complete"


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
@pytest.mark.parametrize("horizon", [30, 40])
def test_covered_ledger_has_independent_trade_and_action_payoffs(unit, horizon):
    observations = _observations([
        _outcome("long-leg", "basket", 10, 12.),
        _outcome("short-leg", "basket", 20, -4., side="short"),
        _outcome("standalone", "single", 30, -3.),
    ], horizon)
    report = reduce_ledger(observations, _contract(unit))
    # Trades: [12, -4, -3]. Actions: [12 - 4 - 2, -3].
    expected = {
        "closed_trade": {"closed_count": 3, "win_rate": 1 / 3, "net_pnl": 5.,
                         "expected_payoff": 5 / 3, "profit_factor": 12 / 7},
        "closed_action": {"closed_count": 2, "win_rate": .5, "net_pnl": 3.,
                          "expected_payoff": 1.5, "profit_factor": 2.},
    }[unit]
    for name, value in expected.items():
        metric = report.metric(unit + "." + name)
        assert metric.status == "valid"
        assert metric.value == pytest.approx(value)
    assert json.loads(report.provenance_json)["population_complete"] is True
    open_count = report.metric(unit + ".open_at_observation_end_count")
    assert open_count.value == (0 if horizon == 30 else None)
    assert open_count.status == ("valid" if horizon == 30 else "unavailable")


@pytest.mark.parametrize("unit,net", [("closed_trade", -7.), ("closed_action", 3.)])
def test_later_ledger_snapshot_filters_scope_but_keeps_closed_action_lifetime(unit, net):
    observations = _observations([
        _outcome("long-leg", "basket", 10, 12.),
        _outcome("short-leg", "basket", 20, -4., side="short"),
        _outcome("standalone", "single", 30, -3.),
        _outcome("future", "future-action", 35, 1_000.),
    ], 40)
    report = reduce_ledger(observations, _contract(unit, start=15))
    assert report.metric(unit + ".closed_count").value == 2
    assert report.metric(unit + ".net_pnl").status == "valid"
    assert report.metric(unit + ".net_pnl").value == net
    assert report.metric(unit + ".expected_payoff").value == net / 2


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_complete_empty_ledger_at_reporting_end_certifies_zero_count_not_win_rate(unit):
    report = reduce_ledger(_observations([], 30), _contract(unit))
    for name in ("closed_count", "net_pnl", "open_at_observation_end_count"):
        metric = report.metric(unit + "." + name)
        assert metric.status == "valid"
        assert metric.value == 0
    assert report.metric(unit + ".win_rate").value is None
    assert report.metric(unit + ".win_rate").status == "undefined"
def test_default_formatter_labels_the_actual_population():
    from quantbt.endpoint import format_metrics_report
    from quantbt.metrics.performance import compute_performance_metrics

    index = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    report = compute_performance_metrics(
        timestamps=index, equity=[100, 90, 99], returns=[0, -.1, .1],
        positions=np.zeros((3, 2)), symbols=["A", "B"], initial_capital=100,
    )
    text = format_metrics_report(report)
    assert "Position State Count" in text
    assert "Period Profit Factor" in text
    assert "Mean Period Return" in text
    assert "Number of Trades" not in text
    assert "Expectancy" not in text

