from __future__ import annotations

import pytest

from quantbt import (
    AccountConfig,
    OptionBacktestEngine,
    OptionBacktestResult,
    OptionPackageIntent,
    OptionPackageLeg,
    OrderSide,
    QuantBTEndpoint,
)
from quantbt.core.arbitrage import (
    ArbitrageLeg,
    ContractType,
    HedgePolicy,
    HedgePolicyKind,
    OptionsVolArbSpec,
    SizingPolicy,
    SizingPolicyKind,
)


def test_quantbt_options_endpoint_runs_mock_chain(option_phase3_chain, option_phase3_registry):
    package = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="endpoint-long-call",
        legs=(OptionPackageLeg(instrument_id="BTC-01FEB26-100000-C.DERIBIT", side=OrderSide.BUY, ratio=1.0),),
        quantity=1.0,
    )
    endpoint = QuantBTEndpoint.options(
        initial_capital=20_000.0,
        reporting_currency="USD",
        initial_balances={"USD": 20_000.0},
        conversion_rates={"BTC": 100_000.0},
        fee_rate=0.0001,
    )

    result = endpoint.backtest(
        chain=option_phase3_chain,
        instruments=option_phase3_registry,
        packages=[package],
    )

    assert isinstance(endpoint.engine, OptionBacktestEngine)
    assert isinstance(result, OptionBacktestResult)
    assert result.metadata["backend"] == "native_option"
    assert result.metadata["run_manifest"]["result_contract"] == "OptionBacktestResult"
    assert endpoint.fills_report.equals(result.fills_report)
    metrics = endpoint.full_report()
    assert metrics["initial_capital"] == 20_000.0


def test_options_support_matrix_and_import_contract():
    matrix = QuantBTEndpoint.options_support_matrix()
    assert matrix["option_packages"]["status"] == "supported"
    assert matrix["OptionsVolArbSpec"]["route"].startswith("strategy/template")
    arb_matrix = QuantBTEndpoint.arbitrage_support_matrix()
    assert arb_matrix["OptionsVolArbSpec"]["status"] == "specialized_route"


def test_options_vol_arb_spec_is_not_routed_through_generic_arbitrage(option_phase3_chain):
    spec = OptionsVolArbSpec(
        arb_id="vol-arb",
        legs=(
            ArbitrageLeg(symbol="BTC-01FEB26-100000-C.DERIBIT", ratio=1.0, contract_type=ContractType.OPTION),
            ArbitrageLeg(symbol="BTC-PERPETUAL.DERIBIT", ratio=-1.0),
        ),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.DELTA_NEUTRAL),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0),
    )
    endpoint = QuantBTEndpoint.arbitrage("options_vol", spec=spec)

    with pytest.raises(NotImplementedError, match="QuantBTEndpoint.options"):
        endpoint.backtest(data=option_phase3_chain, signal_col="mark_price")
