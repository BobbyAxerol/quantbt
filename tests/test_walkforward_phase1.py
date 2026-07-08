from __future__ import annotations

import pandas as pd

from quantbt import (
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    QuantBTEndpoint,
    SizingPolicy,
    SizingPolicyKind,
    WalkForwardConfig,
    WalkForwardEngine,
)


def _bars(index, close=100.0):
    return pd.DataFrame(
        {
            "open": float(close),
            "high": float(close) * 1.01,
            "low": float(close) * 0.99,
            "close": float(close),
            "volume": 1_000.0,
        },
        index=index,
    )


def _idx():
    return pd.date_range("2021-07-01", "2022-09-30", freq="1D", tz="UTC")


def test_walkforward_phase1_splitter_has_no_lookahead_and_stitches_oos_series():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(float(fold.fold_id + 1), index=test_index)

    engine = WalkForwardEngine(
        strategy=strategy,
        config=WalkForwardConfig(split_mode="walk_forward_2022", split_frequency="quarterly"),
    )
    result = engine.run(data=_bars(idx), params={"window": 10})

    assert len(result.folds) == 3
    for fold in result.folds:
        assert fold.train_index.max() < fold.test_index.min()
    assert result.oos_output.loc["2021-12-31"] == 0.0
    assert result.oos_output.loc["2022-01-01"] == 1.0
    assert result.oos_output.loc["2022-04-01"] == 2.0
    assert result.fold_table["train_bars"].min() > 0


def test_walkforward_endpoint_routes_stitched_signal_to_signal_notional():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode="walk_forward_2022",
        split_frequency="quarterly",
        target_mode="signal_notional",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=_bars(idx), symbols=["BTC"], params={"window": 10})

    assert result.metadata["walk_forward"]["n_folds"] == 3
    assert result.metadata["backend"] == "native_vectorized"
    assert result.positions["Position_BTC"].loc["2022-01-02"] > 0.0


def test_walkforward_endpoint_routes_pct_equity_to_legacy_backtester():
    idx = _idx()

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(0.5, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="pct_equity",
        initial_capital=20_000.0,
        leverage=5.0,
        alloc_per_trade=0.5,
        fee=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=_bars(idx), params={"window": 10})

    assert result.metadata["walk_forward"]["target_mode"] == "pct_equity"
    assert result.metadata["hedge_type"] == "pct_equity"


def test_walkforward_endpoint_routes_dataframe_output_to_portfolio():
    idx = _idx()
    data = {"BTC": _bars(idx, 100.0), "ETH": _bars(idx, 10.0)}

    def strategy(data, params, train_index, test_index, fold):
        return pd.DataFrame({"BTC": 1.0, "ETH": -1.0}, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="portfolio",
        portfolio_mode="longshort",
        initial_capital=100_000.0,
        leverage=5.0,
        alloc_per_trade=1_000.0,
        fee=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, params={"window": 10})

    assert result.metadata["backend"] == "legacy_portfolio"
    assert result.metadata["walk_forward"]["target_mode"] == "portfolio"
    assert "Position_BTC" in result.positions.columns
    assert "Position_ETH" in result.positions.columns


def test_walkforward_endpoint_routes_supported_arbitrage_signal():
    idx = _idx()
    data = {
        "PERP": _bars(idx, 100.0),
        "QUARTERLY": _bars(idx, 101.0),
    }
    spec = BasisArbitrageSpec(
        arb_id="WFO_BASIS",
        legs=(
            ArbitrageLeg("PERP", -1.0, role="perp", contract_type=ContractType.LINEAR),
            ArbitrageLeg("QUARTERLY", 1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=1_000.0,
            reference_symbol="PERP",
        ),
    )

    def strategy(data, params, train_index, test_index, fold):
        return pd.Series(1.0, index=test_index)

    bt = QuantBTEndpoint.walk_forward(
        strategy_class=strategy,
        split_mode=2022,
        split_frequency="quarterly",
        target_mode="arbitrage",
        backend="native_vectorized",
        arbitrage_spec=spec,
        initial_capital=100_000.0,
        leverage=5.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = bt.backtest(data=data, params={"window": 10})

    assert result.metadata["engine"] == "units_v2_basis_arbitrage"
    assert result.metadata["walk_forward"]["target_mode"] == "arbitrage"
    assert "package_target_units" in result.metadata
