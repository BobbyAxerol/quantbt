from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quantbt.core.orders import OrderSide, Trade
from quantbt.metrics.report_contracts import ReportingCoverageV1
from quantbt.metrics.reporting.adapters import trades_from_completed
from quantbt.metrics.reporting.execution import ExecutionObservations, reconcile_account, reduce_execution
from quantbt.metrics.reporting.ledger import reduce_ledger
from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome

from .reference_oracle import DAY_NS, closed_outcomes, recorded_net_pnl
from .test_account_reducers import assert_value, policy


FIXTURES = json.loads((Path(__file__).parent / "fixtures/manual.json").read_text())


def ledger_policy(unit="closed_trade", start=0, end=30, **kwargs):
    settings = dict(unit=unit, matching="position_episode",
                    grouping="authoritative_action_id" if unit == "closed_action" else "none",
                    ledger_scope="closed_in_scope_lifetime")
    settings.update(kwargs)
    return replace(policy([start, end]), **settings)


def ledger_coverage(n, ledger="complete"):
    return ReportingCoverageV1(result_identity="executed-outcomes", producer="recorded-ledger",
        profile="audit", ledger=ledger, retained_rows=n if ledger in {"complete", "truncated"} else 0,
        dropped_rows=2 if ledger == "truncated" else 0, reason=None if ledger == "complete" else "outcome population not retained completely")


def rows_from_fixture():
    records = deepcopy(FIXTURES["closed_records"])
    for row in records:
        if "unrealized_pnl" in row:
            row["open_unrealized_pnl"] = row.pop("unrealized_pnl")
    return [RecordedOutcome(**row) for row in records]


def ledger(rows, *, rosters=True, coverage=None):
    grouped = {}
    if rosters:
        for row in rows:
            if row.action_id:
                grouped.setdefault(row.action_id, []).append(row.trade_id)
    return LedgerObservations(records=rows, matching="position_episode",
        coverage=coverage or ledger_coverage(len(rows)), valuation_time_ns=max(30, max((r.closed_at_ns or 0 for r in rows), default=0)),
        rosters=tuple(ActionRoster(action_id=name, outcome_ids=ids, shared_net_adjustment=0.,
                                   allocation_witness="all action costs allocated in leg net outcomes") for name, ids in grouped.items()))


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_met02_t01_t04_t05_opposite_side_net_population_oracle(unit):
    rows = rows_from_fixture()
    obs = ledger(rows)
    actual = reduce_ledger(obs, ledger_policy(unit))
    expected = closed_outcomes(FIXTURES["closed_records"], currency="USDT", unit=unit)
    for name, value in expected.items():
        if name not in {"values", "status"}:
            assert_value(actual.metric(unit + "." + name), value)
    meta = json.loads(actual.provenance_json)
    assert meta["leg_net_sum"] == meta["population_net_sum"] == -10
    assert sum(meta["symbol_closed_pnl"].values()) == -10
    json.dumps(actual.to_metadata(), allow_nan=False)
    assert obs.records == tuple(rows)


def test_met02_t04_t05_partial_close_reversal_and_asynchronous_actions():
    rows = rows_from_fixture()
    rows[1] = replace(rows[1], closed_at_ns=None, net_pnl=-20, open_unrealized_pnl=-60)
    report = reduce_ledger(ledger(rows), ledger_policy("closed_action"))
    assert report.metric("closed_action.closed_count").value == 2
    assert report.metric("closed_action.net_pnl").value == -30
    # The reversing trade has its own accepted action identity, not a guessed side flag.
    rows[1] = replace(rows[1], action_id="reversal")
    report = reduce_ledger(ledger(rows), ledger_policy("closed_action"))
    assert report.metric("closed_action.closed_count").value == 3
    assert report.metric("closed_action.net_pnl").value == 70
    rows[1] = replace(rows[1], action_id="A", closed_at_ns=25)
    report = reduce_ledger(ledger(rows), ledger_policy("closed_action"), retain_population=True)
    assert json.loads(report.provenance_json)["closed_population_ids"] == [["B-short"], ["A-long", "A-short"], ["C-long"]]


@pytest.mark.parametrize("basis,net", [("included_in_fill_price", 117), ("recorded_separate_cost", 114)])
def test_met02_t04_net_cost_allocation_once_and_funding_credit(basis, net):
    attributes = dict(trade_id="a", symbol="BTC", side="long", currency="USDT", opened_at_ns=0,
        closed_at_ns=30, close_sequence=1, gross_pnl=120., allocated_fee=5., allocated_funding_cost=-2., allocated_slippage_cost=3.)
    row = RecordedOutcome(**attributes)
    report = reduce_ledger(ledger([row]), ledger_policy(slippage_basis=basis))
    assert report.metric("closed_trade.net_pnl").value == net
    assert report.metric("closed_trade.net_pnl").value == recorded_net_pnl(attributes, slippage_basis=basis)
    direct = reduce_ledger(ledger([replace(row, net_pnl=net)]), ledger_policy(slippage_basis=basis))
    assert direct.metric("closed_trade.net_pnl").value == net
    assert direct.metric("closed_trade.allocated_fee").value == 5
    assert direct.metric("closed_trade.allocated_funding_cost").value == -2


@pytest.mark.parametrize("values", [[10, 20], [-10, -20], [0, 0], [10, 0, -10], [10, 20, 0, -2, -3, 1e-9], []])
def test_met02_t01_t04_t07_empty_flat_breakeven_streak_and_residual(values):
    records = [RecordedOutcome(trade_id=str(i), symbol="BTC", side="long", currency="USDT",
        closed_at_ns=10, close_sequence=i, net_pnl=value) for i, value in enumerate(values)]
    report = reduce_ledger(ledger(records), ledger_policy(breakeven_currency_tolerance=1e-8))
    reference = [dict(trade_id=r.trade_id, currency="USDT", closed_at_ns=10, close_sequence=r.close_sequence, net_pnl=r.net_pnl) for r in records]
    expected = closed_outcomes(reference, currency="USDT", tolerance=1e-8)
    for key, value in expected.items():
        if key not in {"status", "values"}:
            assert_value(report.metric("closed_trade." + key), value)
    if not values:
        assert report.metric("closed_trade.closed_count").value == 0
        assert report.metric("closed_trade.profit_factor").status == "undefined"


@pytest.mark.parametrize("reason", ["liquidation", "forced_last_bar", "pre_expiry_flatten", "roll_close", "hedge_exit", "cash_settlement"])
def test_met02_t06_recorded_terminal_and_roll_outcomes_not_reexecuted(reason):
    # Tests reporting of an already recorded outcome, not engine certification of this event.
    row = RecordedOutcome(trade_id="recorded", symbol="ETH", side="short", currency="USDT",
        opened_at_ns=0, closed_at_ns=30, close_sequence=0, net_pnl=-7, close_reason=reason)
    report = reduce_ledger(ledger([row]), ledger_policy())
    assert report.metric("closed_trade.net_pnl").value == -7
    assert json.loads(report.provenance_json)["population_reason_counts"] == {reason: 1}


@pytest.mark.parametrize("population", ["omitted", "unsupported", "truncated"])
def test_met02_t07_absent_and_truncated_are_not_zero_closed_counts(population):
    rows = rows_from_fixture() if population == "truncated" else []
    report = reduce_ledger(ledger(rows, coverage=ledger_coverage(len(rows), population)), ledger_policy())
    assert all(m.status == "unavailable" and m.value is None for m in report.metrics)
    assert report.metric("closed_trade.closed_count").coverage.ledger == population


def test_met02_t05_t07_missing_roster_id_obligation_matching_currency_costs_scope():
    rows = rows_from_fixture()
    cases = [ledger(rows, rosters=False), ledger([replace(rows[0], action_id=None)] + rows[1:]),
             replace(ledger(rows), rosters=(ActionRoster(action_id="A", outcome_ids=["missing"],
                     shared_net_adjustment=0., allocation_witness="recorded"),))]
    for obs in cases:
        assert reduce_ledger(obs, ledger_policy("closed_action")).metric("closed_action.closed_count").status == "unavailable"
    foreign = ledger([replace(rows[0], currency="BTC")])
    assert "conversion" in reduce_ledger(foreign, ledger_policy()).metric("closed_trade.net_pnl").reason
    with pytest.raises(ValueError, match="matching"):
        reduce_ledger(ledger(rows), replace(ledger_policy(), matching="recorded_lot"))
    missing_costs = replace(rows[0], net_pnl=None, gross_pnl=120.)
    assert reduce_ledger(ledger([missing_costs]), ledger_policy()).metric("closed_trade.net_pnl").status == "unavailable"
    scoped = reduce_ledger(ledger(rows), ledger_policy(start=15, scope="scoped"))
    assert scoped.metric("closed_trade.net_pnl").value == -30
    attributed = reduce_ledger(ledger(rows), ledger_policy(start=15, scope="scoped", ledger_scope="in_scope_attribution"))
    assert attributed.metric("closed_trade.net_pnl").status == "unavailable"


def test_met02_t05_t07_open_values_need_scope_timestamp_and_not_closed_pnl():
    rows = rows_from_fixture()
    rows[-1] = replace(rows[-1], net_pnl=20.)
    obs = ledger(rows)
    report = reduce_ledger(obs, ledger_policy())
    assert report.metric("closed_trade.open_realized_net_pnl").value == 20
    assert report.metric("closed_trade.open_unrealized_pnl").value == 999
    assert report.metric("closed_trade.open_at_observation_end_count").value == 1
    assert report.metric("closed_trade.net_pnl").value == -10
    assert reduce_ledger(replace(obs, valuation_time_ns=31), ledger_policy()).metric("closed_trade.open_unrealized_pnl").status == "unavailable"


def test_met02_t05_action_shared_cost_reconciliation_and_scoped_async_closure():
    obs = ledger(rows_from_fixture())
    rosters = list(obs.rosters)
    rosters[0] = replace(rosters[0], shared_net_adjustment=-5.)
    report = reduce_ledger(replace(obs, rosters=rosters), ledger_policy("closed_action"))
    metadata = json.loads(report.provenance_json)
    assert metadata["population_net_sum"] == metadata["leg_net_sum"] + metadata["shared_net_adjustment"] == -15
    controls = reconcile_account(baseline_equity=100., final_equity=1084., closed_net_pnl=-10.,
        open_realized_net_pnl=0., open_unrealized_pnl=999., shared_net_adjustment=-5.,
        currency="USDT", witness="all net controls allocated, same baseline/end, no external cashflow")
    assert controls["difference"] == 0
    with pytest.raises(ValueError, match="finite"):
        reconcile_account(baseline_equity=100., final_equity=100., closed_net_pnl=None,
            open_realized_net_pnl=0., open_unrealized_pnl=0., shared_net_adjustment=0., currency="USDT", witness="recorded")


def test_met02_t04_holding_risk_excursion_denominators_not_guessed():
    row = RecordedOutcome(trade_id="r", symbol="BTC", side="long", currency="USDT", closed_at_ns=DAY_NS,
        opened_at_ns=0, close_sequence=1, net_pnl=20., holding_bars=7, initial_risk=10., return_denominator=100.,
        mfe_net_pnl=30., mae_net_pnl=-5., excursion_witness="recorded synchronized net mark path")
    actual = reduce_ledger(ledger([row]), ledger_policy(end=DAY_NS))
    for name, expected in {"mean_holding_days": 1, "mean_holding_bars": 7, "mean_r_multiple": 2,
                           "mean_return": .2, "mean_mfe_net_pnl": 30, "mean_mae_net_pnl": -5}.items():
        assert actual.metric("closed_trade." + name).value == expected
    absent = reduce_ledger(ledger([replace(row, excursion_witness=None)]), ledger_policy(end=DAY_NS))
    assert absent.metric("closed_trade.mean_mfe_net_pnl").status == "unavailable"


def test_met02_t04_t10_completed_trade_adapter_requires_explicit_witness_and_preserves_raw():
    start = pd.Timestamp("2025-01-01", tz="UTC")
    end = start + pd.Timedelta("1D")
    trade = Trade(symbol="ETH", qty=1., side=OrderSide.SELL, opened_at=start, closed_at=end,
        avg_entry=100., avg_exit=90., realized_pnl=9., fees=1., trade_id="engine-id",
        metadata={"reporting_outcome_v1": {"action_id": "recorded-action"}})
    before = deepcopy(trade.metadata)
    result = SimpleNamespace(trades=(trade,))
    obs = trades_from_completed(result, coverage=ledger_coverage(1), matching="position_episode",
        currency="USDT", pnl_basis="authoritative_net", close_sequences=[1], valuation_time_ns=int(end.value))
    report = reduce_ledger(obs, ledger_policy(start=int(start.value), end=int(end.value)))
    assert report.metric("closed_trade.net_pnl").value == 9
    assert report.metric("closed_trade.allocated_fee").status == "unavailable"
    assert trade.metadata == before and result.trades == (trade,)
    with pytest.raises(ValueError, match="basis"):
        trades_from_completed(result, coverage=ledger_coverage(1), matching="position_episode", currency="USDT", pnl_basis="guess", close_sequences=[1])
    with pytest.raises(LookupError, match="identity"):
        trades_from_completed(SimpleNamespace(trades=(replace(trade, trade_id=None),)), coverage=ledger_coverage(1),
            matching="position_episode", currency="USDT", pnl_basis="authoritative_net", close_sequences=[1])


def test_met02_t07_exact_counters_not_ledger_count_and_scope_isolation():
    obs = ExecutionObservations(coverage=ledger_coverage(1, "truncated"), currency="USDT",
        scope_start_ns=0, scope_end_ns=30, witness="full-run exact native counters",
        aggregates=(("fill_count", 123), ("total_fee", 7.5)), times_ns=[0, 10, 30],
        paths=(("fees", [1., 2., 4.5]), ("funding", [0., -2., 1.]), ("gross_exposure_ratio", [0., 1., 2.]),
               ("initial_margin", [0., 5., 10.]), ("maintenance_margin", [0., 1., 2.])))
    full = reduce_execution(obs, policy([0, 30]))
    assert full.metric("execution.fill_count").value == 123
    assert full.metric("execution.total_fee").value == full.metric("execution.sum_fees").value == 7.5
    assert full.metric("execution.sum_funding").value == -1
    assert full.metric("execution.max_initial_margin").value == 10
    scoped = reduce_execution(obs, replace(policy([10, 30]), scope="scoped"))
    assert scoped.metric("execution.fill_count").status == "unavailable"
    assert scoped.metric("execution.sum_fees").value == 6.5
    assert scoped.metric("execution.mean_gross_exposure_ratio").value == 1.5


def test_met02_t07_identity_duplicates_invalid_records_fail_closed():
    rows = rows_from_fixture()
    with pytest.raises(ValueError, match="duplicate"):
        ledger(rows + rows[:1], rosters=False)
    with pytest.raises(ValueError, match="tie-break"):
        ledger([replace(rows[0], close_sequence=2), rows[1]])
    with pytest.raises(ValueError, match="precedes"):
        replace(rows[0], opened_at_ns=11)
    with pytest.raises(ValueError, match="finite"):
        replace(rows[0], net_pnl=float("nan"))
    with pytest.raises(ValueError, match="row count"):
        ledger(rows, coverage=ledger_coverage(0))
