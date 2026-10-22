from dataclasses import replace
import math

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderSide
from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, ReturnObservations
from quantbt.metrics.reporting.ledger_inputs import LedgerObservations, RecordedOutcome
from tools.mode5_admission.ledger import reconcile_fills
from tools.mode5_statistics.analysis import analyze_account, analyze_campaigns, partition_pnl, separate_score_channels, summary_availability
from tests.mode5.test_admission_ledger import market, order, run
from tests.mode5.test_admission_lifecycle import protection


DAY = 86_400_000_000_000


def account_fixture(marks, *, times=None, baseline=100., baseline_time=0):
    times = np.arange(1, len(marks)+1, dtype=np.int64)*DAY if times is None else times
    coverage = ReportingCoverageV1(result_identity="synthetic", producer="explicit-synthetic-path",
        profile="compact", ledger="omitted", retained_rows=0, dropped_rows=0, reason="account-only fixture")
    obs = AccountObservations(times_ns=times, equity=marks, coverage=coverage)
    contract = ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=baseline, baseline_time_ns=baseline_time, scope_end_ns=int(times[-1]),
        sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
    return obs, contract


def campaign_fixture(values, *, opened=False):
    records = tuple(RecordedOutcome(trade_id=str(i), symbol="X", side="long", currency="USDT",
        opened_at_ns=0, closed_at_ns=(i+1)*DAY, close_sequence=i, net_pnl=value,
        allocated_fee=0., allocated_funding_cost=0.) for i, value in enumerate(values))
    if opened:
        records += (RecordedOutcome(trade_id="open", symbol="X", side="short", currency="USDT",
            opened_at_ns=DAY, closed_at_ns=None, close_sequence=len(records), net_pnl=-.3),)
    coverage = ReportingCoverageV1(result_identity="synthetic-campaigns", producer="verified-position-episodes",
        profile="audit", ledger="complete", retained_rows=len(records), dropped_rows=0)
    obs = LedgerObservations(records=records, matching="position_episode", coverage=coverage,
                             valuation_time_ns=(len(values)+1)*DAY)
    contract = ReportingContractV1(scope="full", unit="closed_trade", currency="USDT",
        baseline_equity=20000., baseline_time_ns=0, scope_end_ns=(len(values)+1)*DAY,
        sampling="explicit_period_returns", annual_periods=365., equity_clock="bar_close",
        matching="position_episode", ledger_scope="closed_in_scope_lifetime")
    return obs, contract


def raw_metric(report, name):
    return next(row for row in report["metrics"] if row["metric_id"] == "reporting."+name)


def test_m5t_024_account_observation_N_not_fill_or_campaign_count():
    data = market(100.+np.sin(np.arange(43))+.1*np.arange(43))
    data.index = pd.date_range("2024-01-01", periods=43, freq="D", tz="UTC")
    result = run(data, (order(data, 1, OrderSide.BUY, 20., "entry"),
        order(data, 15, OrderSide.SELL, 5., "partial", reduce_only=True),
        order(data, 42, OrderSide.SELL, 15., "exit", reduce_only=True)))
    assert len(result.fills) == 3
    marks = result.equity.to_numpy()
    returns = marks/np.r_[20000., marks[:-1]]-1
    obs, contract = account_fixture(marks, times=data.index.asi8, baseline=20000.,
                                    baseline_time=int(data.index[0].value)-DAY)
    before = obs.identity
    out = analyze_account(obs, contract, partial_mask=[False]*43, witness="43 complete observed days; three fills are support only")
    assert out["moments"]["n"] == out["derived"]["psr"]["sample_count"] == 43
    assert out["daily_count"] == 43 and np.count_nonzero(returns == 0) > 0
    assert obs.identity == before
    expected = np.mean(returns)/np.std(returns, ddof=1)*math.sqrt(365)
    assert out["derived"]["sharpe_annual"]["value"] == pytest.approx(expected, abs=1e-10)
    assert raw_metric(out["raw_reporting"], "period.sharpe")["value"] == pytest.approx(expected, abs=1e-10)


def test_m5t_026_first_fee_actual_quantbt_and_partition_preserves_initial_mark():
    data = market((100.,)*5)
    result = run(data, (order(data, 1, OrderSide.BUY, 20., "entry"),
                        order(data, 3, OrderSide.SELL, 20., "exit", reduce_only=True)))
    original = result.equity.to_numpy().copy()
    partitions = partition_pnl(original, initial_equity=20000., block_ends=(1, 4))
    assert partitions[0]["money_pnl"] == pytest.approx(-.8, abs=1e-10)
    assert sum(row["money_pnl"] for row in partitions) == pytest.approx(-1.6, abs=1e-10)
    assert math.prod(1+row["simple_return"] for row in partitions)-1 == pytest.approx(original[-1]/20000.-1, abs=1e-12)
    obs, contract = account_fixture([90., 99.])
    out = analyze_account(obs, contract, partial_mask=[False]*2, witness="fee/loss included in first mark")
    assert raw_metric(out["raw_reporting"], "account.total_return")["value"] == pytest.approx(-.01)
    assert raw_metric(out["raw_reporting"], "drawdown.max_depth")["value"] == pytest.approx(.1)
    np.testing.assert_array_equal(original, result.equity.to_numpy())
    with pytest.raises(NotImplementedError, match="flow"):
        replace(contract, cashflows="deposit")


def test_m5t_027_actual_partial_campaign_pf_not_fill_proxy():
    data = market((100.,)*9)
    for bar, high in ((2, 103.), (3, 105.), (4, 107.)):
        data.iloc[bar, data.columns.get_loc("high")] = high
    data.iloc[7:, data.columns.get_loc("close")] = 98.
    data.iloc[7:, data.columns.get_loc("open")] = 98.
    data.iloc[7:, data.columns.get_loc("high")] = 99.
    data.iloc[7:, data.columns.get_loc("low")] = 97.
    result = run(data, (order(data, 1, OrderSide.BUY, 10., "entry"), *protection(data),
        order(data, 6, OrderSide.BUY, 10., "second"),
        order(data, 7, OrderSide.SELL, 10., "second-exit", reduce_only=True)))
    fills = sorted(result.fills, key=lambda row: row.timestamp)
    witness = reconcile_fills(data.index, data.close, fills, initial_capital=20000., fee_rate=.0004)
    assert len(fills) == 6 and len(witness.closed_campaigns) == 2
    pnl = [row["net_pnl"] for row in witness.closed_campaigns]
    obs, contract = campaign_fixture(pnl)
    report = analyze_campaigns(obs, contract)
    campaign_pf = raw_metric(report["raw_reporting"], "closed_trade.profit_factor")["value"]
    assert campaign_pf == pytest.approx(pnl[0]/-pnl[1], abs=1e-12)
    assert raw_metric(report["raw_reporting"], "closed_trade.closed_count")["value"] == 2.
    # A fill-fee/price proxy has no campaign meaning and cannot feed PSR.
    assert report["psr"]["status"] == "UNAVAILABLE"
    assert report["pnl_tail"]["value"] == pytest.approx(min(pnl), abs=1e-12)


@pytest.mark.parametrize("values,expected", [([], "undefined"), ([0.], "undefined"), ([2.], "no_loss"),
                                            ([2., -1., 0.], "valid")])
def test_campaign_no_loss_zero_support_and_open_censoring(values, expected):
    obs, contract = campaign_fixture(values, opened=True)
    report = analyze_campaigns(obs, contract)
    metric = raw_metric(report["raw_reporting"], "closed_trade.profit_factor")
    assert metric["status"] == expected
    assert report["closed_campaigns"] == len(values)
    assert raw_metric(report["raw_reporting"], "closed_trade.open_at_observation_end_count")["value"] == 1.
    if expected != "valid":
        assert metric["value"] is None


def test_m5t_029_unequal_horizons_elapsed_compounding_positive_mdd():
    short_obs, short = account_fixture([90., 110.], times=np.array([DAY, 10*DAY]))
    long_obs, long = account_fixture([90., 110.], times=np.array([DAY, 100*DAY]))
    a = analyze_account(short_obs, short, partial_mask=[True]*2, witness="observed sparse calendar")
    b = analyze_account(long_obs, long, partial_mask=[True]*2, witness="observed sparse calendar")
    for row in (a, b):
        assert raw_metric(row["raw_reporting"], "drawdown.max_depth")["value"] == pytest.approx(.1)
        assert row["derived"]["psr"]["status"] == "UNAVAILABLE"
    assert raw_metric(a["raw_reporting"], "account.cagr_elapsed")["value"] == pytest.approx(1.1**(365.25/10)-1)
    assert raw_metric(b["raw_reporting"], "account.cagr_elapsed")["value"] == pytest.approx(1.1**(365.25/100)-1)
    first = partition_pnl([110., 99.], initial_equity=100., block_ends=(0, 1))
    assert sum(row["money_pnl"] for row in first) == -1.
    assert sum(row["simple_return"] for row in first) != pytest.approx(-.01)


def test_m5t_029_daily_bucket_boundary_and_no_missing_day_fill():
    times = pd.to_datetime(["2024-01-01T12:00Z", "2024-01-01T23:00Z", "2024-01-02T00:00Z", "2024-01-02T23:00Z"]).asi8
    baseline = int(pd.Timestamp("2024-01-01T00:00Z").value)
    obs, contract = account_fixture([90., 95., 99., 104.5], times=times, baseline_time=baseline)
    out = analyze_account(obs, contract, partial_mask=[True, False], witness="partial first UTC bucket")
    assert out["daily_count"] == 2 and out["partial_days"] == 1
    assert raw_metric(out["raw_reporting"], "period.mean_arithmetic")["value"] == pytest.approx((-.05+.1)/2)


def test_m5t_030_raw_and_penalized_score_channels_never_overwrite():
    record = {"raw_sharpe": 1.2, "objective": .6, "activity_count": 3}
    out = separate_score_channels(record, raw_formula_id="quantbt_sr_v2", objective_formula_id="frequency_penalty_v1")
    assert out["raw_sharpe"]["value"] == 1.2 and out["penalized_objective"]["value"] == .6
    assert record == {"raw_sharpe": 1.2, "objective": .6, "activity_count": 3}
    missing = separate_score_channels({"mean_is_sharpe": .6, "objective": .6},
        raw_formula_id="raw", objective_formula_id="penalized")
    assert missing["raw_sharpe"]["status"] == "REPLAY_REQUIRED"
    for requested in ("psr", "hac", "daily_tail", "campaign_tail"):
        availability = summary_availability({"sharpe": 1.2, "fills": 3, "max_dd_pct": -10.}, requested)
        assert availability["status"] == "REPLAY_REQUIRED" and availability["value"] is None


def test_bankruptcy_missing_witness_bad_given_returns_and_immutable_source():
    obs, contract = account_fixture([100., 0., -20.])
    out = analyze_account(obs, contract, partial_mask=[False]*3, witness="valid adverse account")
    assert out["status"] == "BANKRUPT"
    assert raw_metric(out["raw_reporting"], "account.total_return")["value"] == pytest.approx(-1.2)
    assert out["derived"]["psr"]["value"] is None
    obs, contract = account_fixture([90., 95., 100.])
    assert analyze_account(obs, contract)["status"] == "UNAVAILABLE"
    bad = ReturnObservations(values=[.1]*3, end_times_ns=obs.times_ns, partial_mask=[False]*3,
        sampling="observed_daily_utc", witness="unqualified contradictory returns")
    with pytest.raises(ValueError, match="reconcile"):
        analyze_account(replace(obs, returns=bad), contract)
