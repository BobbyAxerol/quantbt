"""ACC-01 F18: undefined periods do not erase independent report groups."""

from copy import deepcopy
from dataclasses import replace
import json
import pickle

import numpy as np
import pandas as pd
import pytest

from quantbt.core.results import BacktestResultV2, OptionBacktestResult
from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting.account import PERIOD_KEYS, reduce_account
from quantbt.metrics.reporting.adapters import account_from_completed
from quantbt.metrics.reporting.cache import ReportingCache
from quantbt.metrics.reporting.execution import ExecutionObservations
from quantbt.metrics.reporting.inputs import (
    AccountObservations, UndefinedPeriodReturn, UndefinedPeriodReturns, derived_returns,
)
from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome
from quantbt.metrics.reporting.public import build_completed_report, format_reporting_report
from quantbt.metrics.reporting.request import ReportingRequest


DAY = 86_400_000_000_000


def completed(cls=BacktestResultV2, marks=(100., 0., 0.)):
    index = pd.to_datetime([0, DAY, 2 * DAY], utc=True)
    return cls(equity=pd.Series(marks, index=index),
        returns=pd.Series([0., -1., np.nan], index=index),
        positions=pd.DataFrame({"X": [0., 1., 0.]}, index=index),
        closes=pd.DataFrame({"X": [100., 100., 100.]}, index=index),
        symbols=["X"], initial_capital=100., liquidated=True, liquidation_bar=1)


def request(*, backend="python", sampling="observed_bar", cache=None):
    account = ReportingContractV1(scope="full", unit="account_period", currency="USD",
        baseline_equity=100., baseline_time_ns=0, scope_end_ns=2 * DAY,
        sampling=sampling, annual_periods=365., equity_clock="bar_close")
    coverage = ReportingCoverageV1(result_identity="acc01-bankrupt", producer="recorded fixture",
        profile="audit", ledger="complete", retained_rows=2, dropped_rows=0)
    rows = tuple(RecordedOutcome(trade_id=name, symbol="X", side="long", currency="USD",
        opened_at_ns=0, closed_at_ns=DAY, close_sequence=sequence, net_pnl=pnl, action_id="A")
        for sequence, (name, pnl) in enumerate((("win", 10.), ("loss", -110.))))
    ledger = LedgerObservations(records=rows, coverage=coverage, matching="recorded_lot",
        valuation_time_ns=2 * DAY, rosters=(ActionRoster(action_id="A", outcome_ids=("win", "loss"),
            shared_net_adjustment=0., allocation_witness="all costs in recorded net"),))
    execution = ExecutionObservations(coverage=coverage, currency="USD", scope_start_ns=0,
        scope_end_ns=2 * DAY, witness="exact executed counters and costs",
        aggregates=(("fill_count", 4), ("total_fee", 2.)), times_ns=[0, DAY, 2 * DAY],
        paths=(("fees", [0., 2., 0.]),))
    contracts = tuple(replace(account, unit=unit, matching="recorded_lot",
        grouping="authoritative_action_id" if unit == "closed_action" else "none",
        ledger_scope="closed_in_scope_lifetime") for unit in ("closed_trade", "closed_action"))
    return ReportingRequest(account=account, result_identity=coverage.result_identity,
        backend=backend, partial_mask=(False, False, False), return_witness="three complete observed periods",
        ledger=ledger, ledger_contracts=contracts, execution=execution, cache=cache, retain_episodes=True)


def metric(report, group, name):
    return next(item for item in report["groups"][group]["metrics"]
                if item["metric_id"] == "reporting." + name)


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("sampling", ["observed_bar", "observed_daily_utc"])
@pytest.mark.parametrize("cls", [BacktestResultV2, OptionBacktestResult])
def test_f18_public_bankruptcy_preserves_account_drawdown_ledger_execution(backend, sampling, cls):
    result = completed(cls)
    before = {name: getattr(result, name).copy(deep=True) for name in ("equity", "returns", "positions", "closes")}
    with ReportingCache() as cache:
        config = request(backend=backend, sampling=sampling, cache=cache)
        report = result.full_report(reporting=config)
        assert report == result.full_report(reporting=config)
        assert cache.hits == 4 and cache.misses == 4
    assert all(group["status"] == "available" for group in report["groups"].values())
    for name, expected in {"account.total_return": -1, "account.final_equity": 0,
                           "account.elapsed_days": 2, "drawdown.max_depth": 1,
                           "drawdown.last_observed_depth": 1, "drawdown.episode_count": 1,
                           "drawdown.current_open_duration_ns": 2 * DAY}.items():
        value = metric(report, "account_period", name)
        assert value["status"] == "valid" and value["value"] == expected
    assert metric(report, "account_period", "account.cagr_elapsed")["status"] == "undefined"
    assert metric(report, "account_period", "account.calmar")["status"] == "undefined"
    for name in PERIOD_KEYS:
        value = metric(report, "account_period", "period." + name)
        if name == "count":
            assert value["status"] == "valid" and value["value"] == 3
        else:
            assert value["status"] == "undefined" and value["value"] is None
            assert "nonpositive equity" in value["reason"] and value["sample_count"] == 3
    for group, name, expected in (("closed_trade", "closed_trade.closed_count", 2),
                                  ("closed_trade", "closed_trade.win_count", 1),
                                  ("closed_trade", "closed_trade.net_pnl", -100),
                                  ("closed_action", "closed_action.closed_count", 1),
                                  ("closed_action", "closed_action.net_pnl", -100),
                                  ("execution", "execution.fill_count", 4),
                                  ("execution", "execution.total_fee", 2),
                                  ("execution", "execution.sum_fees", 2)):
        value = metric(report, group, name)
        assert value["status"] == "valid" and value["value"] == expected
    provenance = report["groups"]["account_period"]["provenance"]
    assert provenance["period_status"] == "undefined"
    assert provenance["first_undefined_time_ns"] == 2 * DAY
    assert provenance["observed_periods"] == provenance["retained_periods"] == 3
    assert provenance["return_witness"] == config.return_witness
    assert "nonpositive equity" in format_reporting_report(report)
    json.dumps(report, allow_nan=False)
    for name, value in before.items():
        checker = pd.testing.assert_frame_equal if isinstance(value, pd.DataFrame) else pd.testing.assert_series_equal
        checker(getattr(result, name), value)


def test_f18_typed_low_level_error_remains_strict_and_identifies_the_period():
    result, config = completed(), request()
    obs = AccountObservations(times_ns=[0, DAY, 2 * DAY], equity=[100., 0., 0.], coverage=config.ledger.coverage)
    with pytest.raises(UndefinedPeriodReturn, match="nonpositive equity") as caught:
        obs.with_derived_returns(config.account, partial_mask=[False] * 3, witness="explicit bars")
    assert isinstance(caught.value, ValueError)
    disposition = caught.value.observations
    assert isinstance(disposition, UndefinedPeriodReturns) and not hasattr(disposition, "values")
    assert disposition.first_undefined_time_ns == 2 * DAY
    adapted = account_from_completed(result, config.account, result_identity=config.result_identity,
        partial_mask=config._partial_mask_array, return_witness=config.return_witness)
    assert isinstance(adapted.returns, UndefinedPeriodReturns)
    assert reduce_account(adapted, config.account).metric("account.total_return").value == -1


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_f18_undefined_snapshot_roundtrips_and_cache_remain_immutable(protocol):
    config = request()
    obs = account_from_completed(completed(), config.account, result_identity=config.result_identity,
        partial_mask=config._partial_mask_array, return_witness=config.return_witness)
    for restored in (deepcopy(obs), pickle.loads(pickle.dumps(obs, protocol=protocol))):
        assert restored.identity == obs.identity
        for array in (restored.equity, restored.times_ns, restored.returns.end_times_ns, restored.returns.partial_mask):
            with pytest.raises(ValueError):
                array.setflags(write=True)
        with ReportingCache() as cache:
            report = cache.reduce("account", obs, config.account)
            assert cache.reduce("account", restored, config.account) is report
            restored.returns.partial_mask.dtype = np.uint8
            with pytest.raises(ValueError, match="array header changed"):
                cache.reduce("account", restored, config.account)


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("marks,expected_return,expected_dd", [
    ((100., -1., 0.), -1., 1.01), ((100., 0., 100.), 0., 1.),
])
def test_f18_nonpositive_previous_mark_does_not_erase_later_account_values(backend, marks, expected_return, expected_dd):
    config = request(backend=backend)
    report = completed(marks=marks).full_report(reporting=config)
    assert metric(report, "account_period", "account.total_return")["value"] == expected_return
    assert metric(report, "account_period", "drawdown.max_depth")["value"] == expected_dd
    assert metric(report, "account_period", "period.mean_arithmetic")["status"] == "undefined"


def test_f18_terminal_zero_with_positive_denominators_still_has_defined_arithmetic_periods():
    config = request()
    report = completed(marks=(100., 100., 0.)).full_report(reporting=config)
    mean = metric(report, "account_period", "period.mean_arithmetic")
    assert mean["status"] == "valid" and mean["value"] == pytest.approx(-1 / 3)
    assert metric(report, "account_period", "period.mean_geometric")["status"] == "undefined"
    assert "period_status" not in report["groups"]["account_period"]["provenance"]


def test_f18_missing_returns_and_missing_ledgers_keep_distinct_unavailable_statuses():
    config = replace(request(), partial_mask=None, return_witness=None, ledger=None,
                     ledger_contracts=(), execution=None)
    report = completed().full_report(reporting=config)
    assert metric(report, "account_period", "account.total_return")["value"] == -1
    assert metric(report, "account_period", "period.sharpe")["status"] == "unavailable"
    assert report["groups"]["closed_trade"]["status"] == "unavailable"
    assert report["groups"]["closed_action"]["status"] == "unavailable"
    assert report["groups"]["execution"]["status"] == "unavailable"


@pytest.mark.parametrize("bad_index,reason", [
    ([0, 0, 2 * DAY], "strictly ordered"), ([DAY, 0, 2 * DAY], "strictly ordered"),
    ([0, None, 2 * DAY], "NaT"),
])
def test_f18_bad_completed_clocks_are_not_swallowed(bad_index, reason):
    result = completed()
    result.equity.index = pd.to_datetime(bad_index, utc=True)
    with pytest.raises(ValueError, match=reason):
        result.full_report(reporting=request())


@pytest.mark.parametrize("problem,reason", [
    ("mask_length", "aligned"), ("witness_type", "witness"), ("explicit_sampling", "producer-supplied"),
    ("scope_end", "scope"), ("result_identity", "different completed result"),
])
def test_f18_unrelated_schema_scope_and_identity_errors_remain_errors(problem, reason):
    config = request()
    if problem == "mask_length":
        config = replace(config, partial_mask=(False, False))
    elif problem == "witness_type":
        config = replace(config, return_witness=123)
    elif problem == "explicit_sampling":
        config = replace(config, account=replace(config.account, sampling="explicit_period_returns"))
    elif problem == "scope_end":
        config = replace(config, account=replace(config.account, scope_end_ns=3 * DAY), ledger=None, ledger_contracts=())
    else:
        config = replace(config, result_identity="different-result")
    with pytest.raises(ValueError, match=reason):
        completed().full_report(reporting=config)


def test_f18_arbitrary_derivation_value_error_is_not_caught(monkeypatch):
    from quantbt.metrics.reporting import adapters

    def malformed(*args, **kwargs):
        raise ValueError("unrelated derivation failure")

    monkeypatch.setattr(adapters, "derived_returns", malformed)
    with pytest.raises(ValueError, match="unrelated derivation failure"):
        build_completed_report(completed(), request())


def test_f18_invalid_mask_is_checked_before_typed_undefined_disposition():
    with pytest.raises(ValueError, match="boolean") as caught:
        derived_returns(np.array([0, DAY, 2 * DAY]), np.array([100., 0., 0.]), request().account,
                        partial_mask=[0, 0, 0], witness="recorded bars")
    assert not isinstance(caught.value, UndefinedPeriodReturn)


def test_f18_python_numba_have_the_same_public_metric_contracts():
    result = completed()
    python = result.full_report(reporting=request(backend="python"))
    numba = result.full_report(reporting=request(backend="numba"))
    for name, group in python["groups"].items():
        assert group["metrics"] == numba["groups"][name]["metrics"]
    assert python["groups"]["account_period"]["drawdown_episodes"] == numba["groups"]["account_period"]["drawdown_episodes"]
