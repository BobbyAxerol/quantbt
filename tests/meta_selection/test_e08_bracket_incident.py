"""Preserve declared sizing, never cure a rejection by redefining the kernel."""

import numpy as np
import pandas as pd
import pytest

from quantbt import IntrabarIntentTape, QuantBTEndpoint
from examples.intrabar_bracket_diagnostic import bracket, event, intents, market, PRICES


@pytest.mark.parametrize("symbol", PRICES)
@pytest.mark.parametrize("backend", ("reference", "numba", "rust"))
def test_reported_input_rejects_while_correct_notional_fills(symbol, backend):
    frame, side = market(symbol)
    _, bad = bracket(symbol, frame, side, backend=backend, weight=2000., allocation=100000.)
    assert bad.metadata["fill_count"] == 0
    assert bad.metadata["rejected_count"] == 11
    assert not bad.positions.to_numpy().any() and bad.fees.sum() == 0
    assert (bad.equity == 20000.).all()
    bt, good = bracket(symbol, frame, side, backend=backend)
    assert len(bt.fills_report) == good.metadata["fill_count"] == 22
    assert good.metadata["rejected_count"] == 0 and good.fees.sum() > 0
    _, equivalent = bracket(symbol, frame, side, backend=backend, weight=2000., allocation=1.)
    pd.testing.assert_series_equal(good.equity, equivalent.equity)
    pd.testing.assert_series_equal(good.fees, equivalent.fees)
    pd.testing.assert_frame_equal(good.positions, equivalent.positions)
    fills = bt.fills_report
    first = np.flatnonzero(side)[0]
    assert fills.iloc[0].timestamp == frame.index[first+1]
    assert fills.iloc[0].qty * fills.iloc[0].price == pytest.approx(2000.)
    assert fills.iloc[0].fee == pytest.approx(.9)


@pytest.mark.parametrize("symbol", PRICES)
def test_reference_numba_rust_and_prepared_account_parity(symbol):
    frame, side = market(symbol, 59)
    baseline = None
    for backend in ("reference", "numba", "rust"):
        bt, result = bracket(symbol, frame, side, backend=backend)
        if baseline is not None:
            for name in ("equity", "positions", "fees", "funding"):
                np.testing.assert_allclose(getattr(result, name), getattr(baseline, name), rtol=1e-12, atol=1e-9)
            columns = ["bar_index", "sequence", "timestamp", "side", "qty", "price", "fee", "reason"]
            pd.testing.assert_frame_equal(bt.fills_report[columns], baseline.metadata["fills_report"][columns])
        baseline = result
        if backend != "reference":
            prepared = bt.prepare_intrabar(data=frame, symbols=[symbol])
            rerun = prepared.run(intent=intents(side, 1.))
            np.testing.assert_array_equal(result.equity, rerun.equity)
            np.testing.assert_array_equal(result.positions, rerun.positions)


@pytest.mark.parametrize("backend", ("python", "rust"))
def test_same_side_event_callback_and_explicit_tape_fill(backend):
    frame, side = market()
    a, callback = event("BTCUSDT", frame, side, backend=backend)
    b, commands = event("BTCUSDT", frame, side, backend=backend, callback=False)
    assert len(a.fills_report) == len(b.fills_report) == 22
    np.testing.assert_array_equal(callback.equity, commands.equity)
    np.testing.assert_array_equal(callback.positions, commands.positions)


def test_scalar_optional_levels_are_not_silently_broadcast():
    with pytest.raises(ValueError, match="length"):
        IntrabarIntentTape.from_arrays(entry_side=[1, 0, 0], entry_size=[1., 0., 0.], stop_value=.013)


def test_shifted_signal_moves_fill_and_last_signal_cannot_fill():
    frame, _ = market(days=1)
    side = np.zeros(len(frame), np.int8)
    side[0:4] = 1
    bt, result = bracket("BTCUSDT", frame, side)
    assert bt.fills_report.iloc[0].timestamp == frame.index[1]
    shifted = np.r_[0, side[:-1]]
    bt, _ = bracket("BTCUSDT", frame, shifted)
    assert bt.fills_report.iloc[0].timestamp == frame.index[2]
    final = np.zeros(len(frame), np.int8)
    final[-1] = 1
    bt, _ = bracket("BTCUSDT", frame, final)
    assert len(bt.fills_report) == 0


@pytest.mark.parametrize("kind", ("min_qty", "min_notional", "margin"))
def test_rejections_do_not_look_like_fills(kind):
    frame, side = market(days=2)
    kwargs = {"min_qty": 100.} if kind == "min_qty" else {"min_notional": 3000.} if kind == "min_notional" else {"alloc_per_trade": 1e8}
    bt = QuantBTEndpoint.intrabar_bracket(initial_capital=20000., leverage=3., use_funding=False,
        intrabar_sizing_mode="fixed_notional", report_level="audit",
        **({"alloc_per_trade": 2000.} | kwargs))
    result = bt.backtest(data=frame, intent=intents(side, 1.), symbols=["BTCUSDT"])
    assert result.metadata["rejected_count"] > 0 and result.metadata["fill_count"] == 0
    assert not result.positions.to_numpy().any()


@pytest.mark.parametrize("scenario", ("reversal", "technical_exit", "stop", "tp", "ambiguous", "gap", "suppressed", "liquidation"))
def test_lifecycle_scenarios_have_same_audit_and_account(scenario):
    frame = pd.DataFrame(dict(open=[100., 100., 100., 100.], high=[100., 101., 101., 101.],
        low=[100., 99., 99., 99.], close=[100., 100., 100., 100.]),
        index=pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC"))
    sides, exits = [1, 0, 0, 0], [False]*4
    stops, tps = [.013]*4, [.026]*4
    if scenario == "reversal":
        sides[1] = -1
    elif scenario in {"technical_exit", "suppressed"}:
        exits[1] = True
        if scenario == "suppressed":
            sides[1] = 1
    elif scenario in {"stop", "ambiguous"}:
        frame.iloc[1, frame.columns.get_loc("low")] = 98.
    if scenario in {"tp", "ambiguous"}:
        frame.iloc[1, frame.columns.get_loc("high")] = 103.
    if scenario == "gap":
        frame.iloc[2] = [95., 96., 94., 95.]
    if scenario == "liquidation":
        stops, tps = None, None
        frame.iloc[1, frame.columns.get_loc("low")] = 1.
    intent = IntrabarIntentTape.from_arrays(entry_side=sides, entry_size=[1.]*4,
        technical_exit=exits, stop_value=stops, take_profit_value=tps)
    values = []
    for constructor in (QuantBTEndpoint.intrabar_bracket_reference,
            QuantBTEndpoint.intrabar_bracket, QuantBTEndpoint.intrabar_bracket_rust):
        bt = constructor(initial_capital=20000., leverage=3., use_funding=False,
            intrabar_sizing_mode="fixed_notional", alloc_per_trade=50000. if scenario == "liquidation" else 2000.,
            fee_rate=.00045, slippage_bps=2., report_level="audit")
        result = bt.backtest(data=frame, intent=intent, symbols=["X"])
        values.append((result, bt.fills_report))
    reference, fills = values[0]
    for result, ledger in values[1:]:
        for name in ("equity", "positions", "fees", "funding"):
            np.testing.assert_allclose(getattr(result, name), getattr(reference, name), rtol=1e-12, atol=1e-9)
        pd.testing.assert_frame_equal(ledger[fills.columns], fills)
        assert result.metadata["rejected_count"] == reference.metadata["rejected_count"]
        assert result.metadata["liquidated"] == reference.metadata["liquidated"]
    expected = {"reversal": "reversal_entry", "technical_exit": "technical_exit", "stop": "stop_loss",
        "tp": "take_profit", "ambiguous": "stop_loss", "gap": "stop_loss", "suppressed": "technical_exit",
        "liquidation": "liquidation"}[scenario]
    assert expected in fills.reason.tolist()
