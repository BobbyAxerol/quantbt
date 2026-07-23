from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    ExerciseStyle,
    GammaScalpingConfig,
    OptionHedgeConfig,
    OptionHedgePolicyType,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    QuantBTEndpoint,
    SettlementStyle,
    build_gamma_scalping_strategy_run,
)


def test_gamma_scalping_adapter_builds_snapshot_local_packages():
    chain, registry = _gamma_chain_and_registry()
    run = build_gamma_scalping_strategy_run(
        chain,
        registry,
        GammaScalpingConfig(
            max_spread_bps=100,
            hedge_policy=OptionHedgeConfig(policy=OptionHedgePolicyType.FIXED_THRESHOLD, threshold=0.05),
        ),
    )

    assert len(run.packages) == 2
    assert run.packages[0].tag == "gamma_scalping_open"
    assert run.packages[1].tag == "gamma_scalping_close"
    assert run.selected_contracts.loc[0, "strike"] == pytest.approx(100_000.0)
    assert run.selected_contracts.loc[0, "call_id"] == "BTC-C100.TEST"
    assert run.selected_contracts.loc[0, "put_id"] == "BTC-P100.TEST"
    assert run.hedge_policy is not None
    assert run.metadata["strategy"] == "gamma_scalping"


def test_options_endpoint_delta_hedged_contract_returns_combined_equity():
    chain, registry = _gamma_chain_and_registry()
    run = build_gamma_scalping_strategy_run(
        chain,
        registry,
        GammaScalpingConfig(
            hedge_policy=OptionHedgeConfig(policy="fixed_threshold", threshold=0.01),
        ),
    )
    underlying = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-02 00:00:00", "2026-01-03 00:00:00"]),
            "close": [100_000.0, 102_000.0, 99_000.0],
        }
    )

    bt = QuantBTEndpoint.options(
        initial_capital=100_000.0,
        reporting_currency="USD",
        initial_balances={"USD": 100_000.0},
        fee_rate=0.0,
    )
    result = bt.backtest(chain=chain, instruments=registry, strategy_run=run, underlying=underlying)

    assert len(result.equity) == chain["timestamp_ns"].nunique() + 1
    assert result.equity.iloc[0] == pytest.approx(100_000.0)
    assert result.option_equity.index.equals(result.combined_equity.index)
    assert result.equity.equals(result.combined_equity)
    assert not result.hedge_report.empty
    assert int(result.hedge_report["should_rebalance"].sum()) >= 1
    assert result.metadata["delta_hedge_contract"]["enabled"] is True
    assert result.metadata["strategy_run"]["strategy"] == "gamma_scalping"
    assert result.metadata["selected_contracts"].shape[0] == 2
    assert result.run_manifest["delta_hedge"]["underlying_source"] == "underlying_dataframe:close"
    report = result.full_report()
    assert report["initial_capital"] == pytest.approx(100_000.0)
    assert report["final_equity"] == pytest.approx(result.combined_equity.iloc[-1])


def _gamma_chain_and_registry() -> tuple[pd.DataFrame, OptionInstrumentRegistry]:
    ts = [int(pd.Timestamp(value, tz="UTC").value) for value in ("2026-01-01", "2026-01-02", "2026-01-03")]
    expiry = int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value)
    specs = (
        _spec("BTC-C100.TEST", OptionKind.CALL, expiry),
        _spec("BTC-P100.TEST", OptionKind.PUT, expiry),
        _spec("BTC-C110.TEST", OptionKind.CALL, expiry),
        _spec("BTC-P110.TEST", OptionKind.PUT, expiry),
    )
    registry = OptionInstrumentRegistry.from_iterable(specs)
    rows = []
    for snap_idx, (timestamp_ns, spot) in enumerate(zip(ts, (100_000.0, 102_000.0, 99_000.0))):
        rows.extend(
            [
                _row(timestamp_ns, 0, "BTC-C100.TEST", "call", 100_000.0, spot, 2100.0 + 100.0 * snap_idx, 0.52),
                _row(timestamp_ns, 1, "BTC-P100.TEST", "put", 100_000.0, spot, 1900.0 - 50.0 * snap_idx, -0.48),
                _row(timestamp_ns, 2, "BTC-C110.TEST", "call", 110_000.0, spot, 500.0, 0.20),
                _row(timestamp_ns, 3, "BTC-P110.TEST", "put", 110_000.0, spot, 9000.0, -0.80),
            ]
        )
    return pd.DataFrame(rows), registry


def _spec(symbol: str, kind: OptionKind, expiry_ns: int) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="test",
        underlying_id="BTC-PERP.TEST",
        underlying_index_id="BTC-INDEX.TEST",
        option_kind=kind,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0 if "100" in symbol else 110_000.0,
        expiry_ns=expiry_ns,
        settlement_currency="USD",
        premium_currency="USD",
        quote_currency="USD",
        multiplier=1.0,
        contract_size=1.0,
        qty_step=1.0,
        tick_size=0.01,
        convention_version="test_linear_v1",
    )


def _row(timestamp_ns: int, sequence_id: int, symbol: str, kind: str, strike: float, spot: float, mark: float, delta: float) -> dict:
    return {
        "timestamp_ns": timestamp_ns,
        "instrument_id": symbol,
        "venue": "TEST",
        "underlying_id": "BTC-PERP.TEST",
        "expiry_ns": int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value),
        "strike": strike,
        "option_kind": kind,
        "bid_price": mark - 5.0,
        "bid_size": 10.0,
        "ask_price": mark + 5.0,
        "ask_size": 10.0,
        "mark_price": mark,
        "last_price": mark,
        "index_price": spot,
        "forward_price": spot,
        "mark_iv": 0.5,
        "bid_iv": 0.49,
        "ask_iv": 0.51,
        "delta": delta,
        "gamma": 0.0001,
        "vega": 100.0,
        "theta": -10.0,
        "open_interest": 100.0,
        "volume": 100.0,
        "quote_currency": "USD",
        "settlement_currency": "USD",
        "sequence_id": sequence_id,
        "source_latency_ns": 1_000_000,
    }
