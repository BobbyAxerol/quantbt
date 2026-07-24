from __future__ import annotations

import pandas as pd

from quantbt import (
    AccountConfig,
    NativeOptionBackend,
    NativeOptionConfig,
    OptionBacktestResult,
    OptionExecutionConfig,
    OptionPackageIntent,
    OptionPackageLeg,
    OrderSide,
)
from quantbt.core.results import BacktestResultV2
from quantbt.metrics import option_report_bundle, option_run_manifest


def test_native_option_result_contract_reports(option_phase3_chain, option_phase3_registry):
    package = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="long-call-1",
        legs=(
            OptionPackageLeg(
                instrument_id="BTC-01FEB26-100000-C.DERIBIT",
                side=OrderSide.BUY,
                ratio=1.0,
            ),
        ),
        quantity=1.0,
    )
    backend = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0, leverage=1.0),
            option_execution=OptionExecutionConfig(fee_rate=0.0001),
            initial_balances={"USD": 20_000.0},
            conversion_rates={"BTC": 100_000.0},
            reporting_currency="USD",
        )
    )

    result = backend.run(
        chain=option_phase3_chain,
        instruments=option_phase3_registry,
        packages=[package],
    )

    assert isinstance(result, OptionBacktestResult)
    assert isinstance(result, BacktestResultV2)
    assert result.equity.index.is_monotonic_increasing
    assert result.equity.iloc[0] == 20_000.0
    assert result.equity.iloc[-1] != result.equity.iloc[0]
    assert len(result.fills) == 1
    assert result.fills_report.loc[0, "symbol"] == "BTC-01FEB26-100000-C.DERIBIT"
    assert result.packages_report.loc[0, "status"] == "filled"
    assert set(["USD", "BTC"]).issubset(result.cash_report.columns)
    assert not result.marks_report.empty
    assert not result.greeks_report.empty
    assert "requirement" in result.margin_report.columns
    assert option_run_manifest(result)["backend"] == "native_option"
    bundle = option_report_bundle(result)
    assert set(bundle).issuperset({"fills_report", "packages_report", "cash_report", "margin_report"})
    report = result.full_report()
    assert report["initial_capital"] == 20_000.0


def test_native_option_result_supports_settlement_events(option_phase3_chain, option_phase3_registry):
    package = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="long-put-1",
        legs=(OptionPackageLeg(instrument_id="BTC-01FEB26-110000-P.DERIBIT", side=OrderSide.BUY, ratio=1.0),),
        quantity=1.0,
    )
    backend = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0),
            initial_balances={"USD": 20_000.0},
            conversion_rates={"BTC": 100_000.0},
        )
    )

    result = backend.run(
        chain=option_phase3_chain,
        instruments=option_phase3_registry,
        packages=[package],
        settlement_events=[
            {
                "symbol": "BTC-01FEB26-110000-P.DERIBIT",
                "timestamp_ns": int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value),
                "settlement_price": 100_000.0,
            }
        ],
    )

    assert len(result.settlements_report) == 1
    assert result.positions.iloc[-1]["Position_BTC-01FEB26-110000-P.DERIBIT"] == 0.0
    assert result.metadata["settlement_count"] == 1
