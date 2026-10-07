from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from .reference_oracle import closed_outcomes, recorded_net_pnl


FIXTURES = json.loads((Path(__file__).parent / "fixtures/manual.json").read_text())


@pytest.mark.parametrize("unit,expected", [("closed_trade", "trade_expected"), ("closed_action", "action_expected")])
def test_t05_opposite_legs_are_classified_at_declared_unit(unit, expected):
    records = deepcopy(FIXTURES["closed_records"])
    before = deepcopy(records)
    report = closed_outcomes(records, currency="USDT", unit=unit)
    for key, value in FIXTURES[expected].items():
        assert report[key] == pytest.approx(value)
    assert report["avg_pnl"] == report["expected_payoff"]
    assert report["payoff_ratio"] == pytest.approx(report["avg_profit"] / abs(report["avg_loss"]))
    assert records == before


def test_t05_partial_exit_unrelated_open_position_and_reversal():
    rows = deepcopy(FIXTURES["closed_records"])
    # A's second leg is still open: a closed leg is not a closed action.
    rows[1]["closed_at_ns"] = None
    assert closed_outcomes(rows, currency="USDT", unit="closed_action")["values"] == [-30, 0]
    # Closing the old episode does not close the reversal's new episode.
    rows[1]["action_id"] = "new-reversal"
    assert closed_outcomes(rows, currency="USDT", unit="closed_action")["values"] == [100, -30, 0]


def test_t05_recorded_net_costs_not_subtracted_twice():
    row = dict(net_pnl=117., gross_pnl=120., allocated_fee=5., allocated_funding_cost=-2., allocated_slippage_cost=3.)
    assert recorded_net_pnl(row) == 117
    del row["net_pnl"]
    assert recorded_net_pnl(row) == 117
    assert recorded_net_pnl(row, slippage_basis="recorded_separate_cost") == 114
    with pytest.raises(ValueError, match="allocation"):
        recorded_net_pnl({"gross_pnl": 120})


def test_t05_missing_truncated_ledger_not_empty_population():
    missing = closed_outcomes([], currency="USDT", complete=False)
    empty = closed_outcomes([], currency="USDT", complete=True)
    assert missing["closed_count"] is None
    assert empty["closed_count"] == 0 and empty["avg_pnl"] is None
    assert empty["profit_factor"] is None


def test_t05_scope_lifetime_pnl_is_not_scope_equity_change():
    rows = deepcopy(FIXTURES["closed_records"])
    report = closed_outcomes(rows, currency="USDT", scope=(15, 30))
    assert report["values"] == [-30, 0]
    carried = rows[:1]
    carried[0].update(opened_at_ns=0, closed_at_ns=20)
    lifetime = closed_outcomes(carried, currency="USDT", scope=(15, 30))
    assert lifetime["net_pnl"] == 100
    # Recorded scope-entry unrealized +80 leaves +20 in-scope, not +100.
    assert lifetime["net_pnl"] - 80 == 20


def test_t05_duplicate_ids_currency_and_timestamp_grouping_fail():
    rows = deepcopy(FIXTURES["closed_records"])
    with pytest.raises(ValueError, match="duplicate"):
        closed_outcomes(rows + [rows[0]], currency="USDT")
    rows[0]["currency"] = "BTC"
    with pytest.raises(ValueError, match="conversion"):
        closed_outcomes(rows, currency="USDT")
    rows[0]["currency"] = "USDT"
    rows[0]["action_id"] = None
    with pytest.raises(ValueError, match="identity"):
        closed_outcomes(rows, currency="USDT", unit="closed_action")


@pytest.mark.parametrize("values,pf,win,loss,breakeven", [
    ([10, 20], math.inf, 2, 0, 0), ([-10, -20], 0, 0, 2, 0),
    ([0, 0], None, 0, 0, 2), ([10, 0, -10], 1, 1, 1, 1),
])
def test_t05_closed_population_edges(values, pf, win, loss, breakeven):
    rows = [dict(trade_id=str(i), currency="USDT", closed_at_ns=i, close_sequence=i, net_pnl=v) for i, v in enumerate(values)]
    report = closed_outcomes(rows, currency="USDT")
    assert (report["win_count"], report["loss_count"], report["breakeven_count"]) == (win, loss, breakeven)
    assert report["profit_factor"] == pf


def test_t05_sequence_streaks_and_tolerance_preserve_residual():
    rows = [dict(trade_id=str(i), currency="USDT", closed_at_ns=10, close_sequence=i, net_pnl=v) for i, v in enumerate([10, 20, 0, -2, -3, 1e-9])]
    report = closed_outcomes(list(reversed(rows)), currency="USDT", tolerance=1e-8)
    assert report["max_win_streak"] == report["max_loss_streak"] == 2
    assert report["breakeven_count"] == 2
    assert report["net_pnl"] == pytest.approx(25.000000001, abs=1e-12)
