"""ACC-01 F12: finite inputs may have nonrepresentable aggregate outcomes."""

from dataclasses import replace
import json

import pytest

from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting.cache import ReportingCache
from quantbt.metrics.reporting.ledger import reduce_ledger
from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome


DAY = 86_400_000_000_000


def policy(unit="closed_trade", end=2 * DAY):
    return ReportingContractV1(scope="full", unit=unit, currency="USD", baseline_equity=100.,
        baseline_time_ns=0, scope_end_ns=end, sampling="observed_bar", annual_periods=1.,
        equity_clock="bar_close", matching="recorded_lot", ledger_scope="closed_in_scope_lifetime",
        grouping="authoritative_action_id" if unit == "closed_action" else "none")


def outcome(index, value, *, action=None, symbol="X"):
    return RecordedOutcome(trade_id=f"trade-{index}", symbol=symbol, side="long", currency="USD",
        opened_at_ns=0, closed_at_ns=(index + 1) * DAY, close_sequence=index,
        net_pnl=value, allocated_fee=1., allocated_funding_cost=-.5, allocated_slippage_cost=.25,
        holding_bars=index + 1, return_denominator=1e308, initial_risk=1e308, action_id=action)


def observations(rows, *, groups=None, adjustments=None, end=None):
    rows = tuple(rows)
    if groups is None:
        groups = {row.action_id: (row.trade_id,) for row in rows if row.action_id is not None}
    adjustments = adjustments or {}
    rosters = tuple(ActionRoster(action_id=action, outcome_ids=members,
        shared_net_adjustment=adjustments.get(action, 0.), allocation_witness="recorded allocation")
        for action, members in groups.items())
    coverage = ReportingCoverageV1(result_identity="acc01-ledger", producer="recorded outcomes",
        profile="audit", ledger="complete", retained_rows=len(rows), dropped_rows=0)
    return LedgerObservations(records=rows, coverage=coverage, matching="recorded_lot", rosters=rosters,
        valuation_time_ns=end if end is not None else max((row.closed_at_ns or 0 for row in rows), default=2 * DAY))


def assert_invalid(metric, count):
    assert metric.status == "invalid" and metric.value is None
    assert "overflow" in metric.reason and metric.sample_count == count


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_f12_two_finite_extreme_outcomes_are_json_safe_without_losing_population(backend, unit):
    rows = (outcome(0, 1e308, action="A"), outcome(1, 1e308, action="B"))
    obs = observations(rows)
    with ReportingCache() as cache:
        report = cache.reduce("ledger", obs, policy(unit), backend=backend, retain_population=True)
        assert cache.reduce("ledger", obs, policy(unit), backend=backend, retain_population=True) is report
    metric = lambda name: report.metric(unit + "." + name)
    assert_invalid(metric("net_pnl"), 2)
    assert metric("profit_factor").status == "no_loss" and metric("profit_factor").value is None
    assert_invalid(metric("top_profit_concentration"), 2)
    for name, expected in {"closed_count": 2, "win_count": 2, "loss_count": 0,
                           "breakeven_count": 0, "win_rate": 1, "max_win_streak": 2,
                           "max_loss_streak": 0, "largest_win": 1e308, "median_pnl": 1e308,
                           "avg_profit": 1e308, "avg_pnl": 1e308, "expected_payoff": 1e308,
                           "allocated_fee": 2, "allocated_funding_cost": -1,
                           "allocated_slippage_cost": .5, "mean_holding_days": 1.5}.items():
        actual = metric(name)
        assert actual.status == "valid" and actual.value == pytest.approx(expected)
    assert metric("avg_profit").sample_count == 2
    metadata = report.to_metadata()
    provenance = metadata["provenance"]
    for path in ("leg_net_sum", "population_net_sum"):
        assert provenance[path] is None
        assert provenance["numeric_issues"][path] == {"status": "invalid", "reason": "numeric overflow"}
    assert provenance["symbol_closed_pnl"] == {"X": None}
    assert provenance["numeric_issues"]["symbol_closed_pnl.X"]["status"] == "invalid"
    assert provenance["population_complete"] is True
    assert provenance["closed_population_ids"] == [["trade-0"], ["trade-1"]]
    json.dumps(metadata, allow_nan=False)
    assert obs.records == rows and all(row.net_pnl == 1e308 for row in rows)


@pytest.mark.parametrize("backend", ["python", "numba"])
def test_f12_overflowed_loss_denominator_is_not_a_fabricated_zero_ratio(backend):
    obs = observations([outcome(0, 1e308), outcome(1, -1e308), outcome(2, -1e308)])
    report = reduce_ledger(obs, policy(end=3 * DAY), backend=backend)
    assert_invalid(report.metric("closed_trade.profit_factor"), 3)
    for name, expected in {"net_pnl": -1e308, "closed_count": 3, "win_count": 1,
                           "loss_count": 2, "breakeven_count": 0, "max_loss_streak": 2,
                           "avg_profit": 1e308, "avg_loss": -1e308, "payoff_ratio": 1,
                           "median_pnl": -1e308, "top_profit_concentration": 1}.items():
        metric = report.metric("closed_trade." + name)
        assert metric.status == "valid" and metric.value == pytest.approx(expected)
    json.dumps(report.to_metadata(), allow_nan=False)


@pytest.mark.parametrize("backend", ["python", "numba"])
def test_f12_open_outcome_overflow_does_not_erase_closed_metrics(backend):
    rows = [outcome(0, 7.), replace(outcome(1, 1e308, action="A"), closed_at_ns=None,
                                   open_unrealized_pnl=1e308),
            replace(outcome(2, 1e308, action="B"), closed_at_ns=None, open_unrealized_pnl=1e308)]
    obs = observations(rows, end=2 * DAY)
    report = reduce_ledger(obs, policy(), backend=backend)
    assert report.metric("closed_trade.closed_count").value == 1
    assert report.metric("closed_trade.net_pnl").value == 7
    assert report.metric("closed_trade.open_at_observation_end_count").value == 2
    assert_invalid(report.metric("closed_trade.open_realized_net_pnl"), 2)
    assert_invalid(report.metric("closed_trade.open_unrealized_pnl"), 2)
    assert report.to_metadata()["provenance"]["population_net_sum"] == 7
    json.dumps(report.to_metadata(), allow_nan=False)


@pytest.mark.parametrize("backend", ["python", "numba"])
def test_f12_overflow_within_one_action_preserves_count_costs_and_holding(backend):
    rows = [outcome(0, 1e308, action="A"), outcome(1, 1e308, action="A")]
    obs = observations(rows, groups={"A": ("trade-0", "trade-1")})
    report = reduce_ledger(obs, policy("closed_action"), backend=backend, retain_population=True)
    assert report.metric("closed_action.closed_count").value == 1
    for name in ("net_pnl", "win_count", "loss_count", "breakeven_count", "win_rate",
                 "avg_pnl", "max_win_streak", "profit_factor"):
        assert_invalid(report.metric("closed_action." + name), 1)
    assert report.metric("closed_action.allocated_fee").value == 2
    assert report.metric("closed_action.mean_holding_days").value == 2
    assert report.metric("closed_action.open_at_observation_end_count").value == 0
    provenance = report.to_metadata()["provenance"]
    assert provenance["population_complete"] is True
    assert provenance["closed_population_ids"] == [["trade-0", "trade-1"]]
    assert provenance["population_net_sum"] is None
    json.dumps(report.to_metadata(), allow_nan=False)


@pytest.mark.parametrize("backend", ["python", "numba"])
def test_f12_derived_recorded_net_overflow_is_not_classified_as_breakeven(backend):
    row = replace(outcome(0, 0.), net_pnl=None, gross_pnl=1e308, allocated_fee=-1e308)
    obs = observations([row], end=2 * DAY)
    report = reduce_ledger(obs, policy(), backend=backend)
    assert report.metric("closed_trade.closed_count").value == 1
    assert_invalid(report.metric("closed_trade.net_pnl"), 1)
    assert_invalid(report.metric("closed_trade.breakeven_count"), 1)
    assert report.metric("closed_trade.allocated_fee").value == -1e308
    json.dumps(report.to_metadata(), allow_nan=False)


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_f12_nonoverflowing_symbol_and_shared_adjustment_provenance_survive(unit):
    rows = [outcome(0, 0., action="A"), outcome(1, 0., action="B"),
            outcome(2, 7., action="C", symbol="unaffected")]
    obs = observations(rows, adjustments={"A": 1e308, "B": 1e308})
    report = reduce_ledger(obs, policy(unit, end=3 * DAY))
    provenance = report.to_metadata()["provenance"]
    assert provenance["symbol_closed_pnl"] == {"X": 0., "unaffected": 7.}
    assert provenance["leg_net_sum"] == 7
    if unit == "closed_action":
        assert provenance["shared_net_adjustment"] is None
        assert provenance["numeric_issues"]["shared_net_adjustment"]["status"] == "invalid"
        assert_invalid(report.metric("closed_action.net_pnl"), 3)
    else:
        assert provenance["shared_net_adjustment"] == 0
        assert report.metric("closed_trade.net_pnl").value == 7
    json.dumps(report.to_metadata(), allow_nan=False)


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_f12_normal_signed_outcomes_keep_handwritten_statistics(backend, unit):
    rows = [outcome(i, value, action=action) for i, (value, action) in enumerate(
        [(12., "A"), (-5., "A"), (0., "B"), (3., "C"), (-2., "C")])]
    obs = observations(rows, groups={"A": ("trade-0", "trade-1"), "B": ("trade-2",),
                                     "C": ("trade-3", "trade-4")})
    report = reduce_ledger(obs, policy(unit, end=5 * DAY), backend=backend)
    expected = dict(net_pnl=8, win_count=2, breakeven_count=1, max_win_streak=1,
                    allocated_fee=5, allocated_funding_cost=-2.5, allocated_slippage_cost=1.25)
    if unit == "closed_trade":
        expected.update(closed_count=5, loss_count=2, win_rate=.4, avg_profit=7.5, avg_loss=-3.5,
                        profit_factor=15 / 7, payoff_ratio=15 / 7, median_pnl=0, avg_pnl=1.6,
                        top_profit_concentration=.8, max_loss_streak=1, mean_holding_days=3)
    else:
        expected.update(closed_count=3, loss_count=0, win_rate=2 / 3, avg_profit=4,
                        median_pnl=1, avg_pnl=8 / 3, top_profit_concentration=7 / 8,
                        max_loss_streak=0, mean_holding_days=10 / 3)
        assert report.metric("closed_action.profit_factor").status == "no_loss"
    for name, value in expected.items():
        metric = report.metric(unit + "." + name)
        assert metric.status == "valid" and metric.value == pytest.approx(value)
    assert "numeric_issues" not in report.to_metadata()["provenance"]
    assert report.to_metadata()["provenance"]["population_net_sum"] == 8
    json.dumps(report.to_metadata(), allow_nan=False)


@pytest.mark.parametrize("values", [(1e308, 1e308), (1e308, -1e308, -1e308), (12., -5., 0., 3., -2.)])
@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_f12_python_numba_have_identical_metric_contracts(values, unit):
    obs = observations([outcome(i, value, action=f"action-{i}") for i, value in enumerate(values)])
    contract = policy(unit, end=len(values) * DAY)
    python = reduce_ledger(obs, contract, backend="python")
    numba = reduce_ledger(obs, contract, backend="numba")
    assert python.metrics == numba.metrics
    expected = python.to_metadata()["provenance"]
    actual = numba.to_metadata()["provenance"]
    expected.pop("backend")
    actual.pop("backend")
    assert actual == expected
