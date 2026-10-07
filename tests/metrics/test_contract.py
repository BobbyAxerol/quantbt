from dataclasses import FrozenInstanceError, replace
import json

import pytest

from quantbt.metrics.report_contracts import (
    ReportingContractV1, ReportingCoverageV1, ReportingMetricV1,
)


def contract(**kwargs):
    fields = dict(scope="full", unit="account_period", currency="USDT",
                  baseline_equity=100.0, baseline_time_ns=0,
                  scope_end_ns=86_400_000_000_000, sampling="observed_bar",
                  annual_periods=365.0, equity_clock="bar_close")
    fields.update(kwargs)
    return ReportingContractV1(**fields)


def coverage(**kwargs):
    fields = dict(result_identity="synthetic-result", producer="fixture",
                  profile="audit", ledger="complete", retained_rows=0,
                  dropped_rows=0)
    fields.update(kwargs)
    return ReportingCoverageV1(**fields)


def test_t07_immutable_complete_round_trip():
    policy = contract(scope="scoped", partial_periods="exclude_disclosed",
                      risk_free_per_period=.002, mar_per_period=.003,
                      omega_threshold_per_period=.004, variance_ddof=0,
                      sortino_denominator="negative_observations", cagr_basis="period_count",
                      recovery_relative_tolerance=1e-10, disjoint_scope="independent_segments")
    copy = ReportingContractV1.from_metadata(json.loads(json.dumps(policy.to_metadata(), allow_nan=False)))
    assert copy == policy and copy.identity == policy.identity
    with pytest.raises(FrozenInstanceError):
        policy.scope = "full"
    with pytest.raises(ValueError):
        ReportingContractV1.from_metadata({**policy.to_metadata(), "unknown_policy": "drop"})


@pytest.mark.parametrize("field", ["version", "sortino_denominator", "cost_basis", "partial_periods", "recovery_relative_tolerance"])
def test_t07_partial_metadata_cannot_fall_back_to_defaults(field):
    metadata = contract().to_metadata()
    del metadata[field]
    with pytest.raises(ValueError, match="preserve"):
        ReportingContractV1.from_metadata(metadata)


@pytest.mark.parametrize("name,value", [
    ("scope", "oos_auto"), ("unit", "fills"), ("currency", ""),
    ("baseline_equity", 0), ("baseline_equity", -1), ("baseline_equity", True),
    ("baseline_equity", float("nan")), ("scope_end_ns", -1),
    ("baseline_time_ns", .5), ("scope_end_ns", True), ("annual_periods", 0),
    ("annual_periods", float("inf")), ("sampling", "guess"), ("equity_clock", "intrabar_inferred"),
    ("calendar", "local"), ("missing_periods", "forward_fill"), ("partial_periods", "guess"),
    ("cagr_basis", "abs_growth"), ("calendar_year_days", 0), ("min_cagr_days", -1),
    ("risk_free_per_period", float("nan")), ("mar_per_period", float("inf")),
    ("variance_ddof", True), ("variance_ddof", 2), ("sortino_denominator", "guess"),
    ("cost_basis", "subtract_again"), ("slippage_basis", "both"),
    ("matching", "FIFO_inferred"), ("grouping", "same_timestamp"),
    ("ledger_scope", "all_unsliced"), ("disjoint_scope", "concatenate"),
    ("recovery_relative_tolerance", 1), ("breakeven_currency_tolerance", -1),
    ("version", "native_metric_v2"),
])
def test_t02_t07_invalid_policy_fail_closed(name, value):
    with pytest.raises(ValueError):
        contract(**{name: value})


def test_t02_cashflow_contract_is_not_invented():
    with pytest.raises(NotImplementedError, match="flow-adjusted"):
        contract(cashflows="time_weighted")


def test_t07_closed_population_requires_explicit_matching_and_identity():
    with pytest.raises(ValueError):
        contract(unit="closed_trade")
    trade = contract(unit="closed_trade", matching="position_episode", ledger_scope="closed_in_scope_lifetime")
    action = replace(trade, unit="closed_action", grouping="authoritative_action_id")
    assert action.identity != trade.identity
    with pytest.raises(ValueError):
        replace(action, grouping="none")
    with pytest.raises(ValueError):
        replace(trade, unit="account_period")


@pytest.mark.parametrize("changes", [
    dict(scope="scoped"), dict(baseline_equity=120.), dict(annual_periods=252.),
    dict(mar_per_period=.01), dict(variance_ddof=0), dict(cagr_basis="period_count"),
    dict(sortino_denominator="negative_observations"), dict(equity_clock="daily_close"),
    dict(recovery_relative_tolerance=1e-12), dict(partial_periods="exclude_disclosed"),
])
def test_t07_policy_change_changes_identity(changes):
    assert replace(contract(), **changes).identity != contract().identity


@pytest.mark.parametrize("changes", [
    dict(ledger="truncated"), dict(ledger="complete", dropped_rows=1),
    dict(ledger="omitted"), dict(ledger="unsupported"), dict(retained_rows=-1),
    dict(ledger="omitted", reason="score only", retained_rows=1), dict(dropped_rows=True),
])
def test_t07_coverage_cannot_claim_complete_or_empty(changes):
    with pytest.raises(ValueError):
        coverage(**changes)


@pytest.mark.parametrize("status", ["no_loss", "undefined", "unavailable", "insufficient", "invalid"])
def test_t07_null_is_not_zero_or_nonstandard_infinity(status):
    metric = ReportingMetricV1(metric_id="reporting.trade.profit_factor",
                               contract_identity=contract().identity, unit="ratio",
                               status=status, value=None, sample_count=0,
                               coverage=coverage(), reason="registered policy")
    payload = json.loads(json.dumps(metric.to_metadata(), allow_nan=False))
    assert ReportingMetricV1.from_metadata(payload) == metric
    assert payload["value"] is None
    with pytest.raises(ValueError):
        replace(metric, value=0.)


def test_t07_zero_count_is_valid_but_infinity_is_not_json():
    metric = ReportingMetricV1(metric_id="reporting.trade.closed_count",
                               contract_identity=contract().identity, unit="count",
                               status="valid", value=0., sample_count=0, coverage=coverage())
    assert metric.value == 0.
    with pytest.raises(ValueError):
        replace(metric, value=float("inf"))
    with pytest.raises(ValueError):
        replace(metric, metric_id="num_trades")
    with pytest.raises(ValueError):
        replace(metric, contract_identity="native")
