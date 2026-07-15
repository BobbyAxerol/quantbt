from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    ArbitrageLeg,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    ContractType,
    FundingArbitrageSpec,
    HedgePolicy,
    HedgePolicyKind,
    IndexBasketArbSpec,
    NativeEventBackend,
    NativeEventConfig,
    NativeVectorizedBackend,
    NativeVectorizedConfig,
    SizingPolicy,
    SizingPolicyKind,
    build_arbitrage_domain_audit,
    compare_native_arbitrage_results,
)
from quantbt.core.schema import AccountConfig


def _idx():
    return pd.date_range("2024-01-01", periods=4, freq="8h", tz="UTC")


def _signal(idx):
    return pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)


def _event():
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    )


def _vectorized():
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(initial_capital=50_000.0, leverage=10.0),
            fee_rate=0.0,
            use_funding=True,
        )
    )


def test_phase5_3_basis_native_audit_and_event_vectorized_parity_pass():
    idx = _idx()
    closes = {
        "BTC-PERP": pd.Series([100.0, 100.0, 105.0, 103.0], index=idx),
        "BTC-QUARTERLY": pd.Series([102.0, 102.0, 104.0, 101.0], index=idx),
    }
    spec = BasisArbitrageSpec(
        arb_id="AUDIT_BASIS",
        legs=(
            ArbitrageLeg("BTC-PERP", -1.0, role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
            ArbitrageLeg("BTC-QUARTERLY", 1.0, role="quarterly", contract_type=ContractType.LINEAR),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0, reference_symbol="BTC-PERP"),
    )

    event = _event().run_basis_arbitrage(idx, spec, _signal(idx), closes, funding_rate={"BTC-PERP": 0.0})
    vectorized = _vectorized().run_basis_arbitrage(idx, spec, _signal(idx), closes, funding_rate={"BTC-PERP": 0.0})

    event_audit = build_arbitrage_domain_audit(event, raise_on_fail=True)
    vector_audit = build_arbitrage_domain_audit(vectorized, raise_on_fail=True)
    parity = compare_native_arbitrage_results(event, vectorized, raise_on_fail=True)

    assert event_audit["status"] == "pass"
    assert vector_audit["status"] == "pass"
    assert parity["status"] == "pass"
    assert event_audit["target_symbols"] == ["BTC-PERP", "BTC-QUARTERLY"]
    assert event_audit["final_gross_target_units"] == 0.0
    assert event_audit["final_gross_position_units"] == 0.0


def test_phase5_3_audit_fails_on_corrupted_package_residual():
    idx = _idx()
    closes = {
        "BTC-MAR": pd.Series([100.0, 100.0, 101.0, 101.0], index=idx),
        "BTC-JUN": pd.Series([103.0, 103.0, 104.0, 104.0], index=idx),
    }
    spec = CalendarSpreadSpec(
        arb_id="AUDIT_CORRUPT",
        legs=(ArbitrageLeg("BTC-MAR", -1.0, expiry="2024-03-29"), ArbitrageLeg("BTC-JUN", 1.0, expiry="2024-06-28")),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0, reference_symbol="BTC-MAR"),
    )
    result = _event().run_package_arbitrage(idx, spec, _signal(idx), closes)
    corrupted = result.metadata["package_pnl_report"].copy()
    corrupted.loc[idx[2], "pnl_residual"] = 1.0
    result.metadata["package_pnl_report"] = corrupted

    audit = build_arbitrage_domain_audit(result, tolerance=1e-9)

    assert audit["status"] == "fail"
    assert audit["checks"]["package_pnl_residual_ok"] is False
    with pytest.raises(AssertionError):
        build_arbitrage_domain_audit(result, tolerance=1e-9, raise_on_fail=True)


def test_phase5_3_advanced_package_specs_have_audit_reports():
    idx = _idx()
    funding_closes = {
        "PERP_A": pd.Series([100.0, 100.0, 105.0, 105.0], index=idx),
        "PERP_B": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
    }
    funding_spec = FundingArbitrageSpec(
        arb_id="AUDIT_FUNDING",
        legs=(ArbitrageLeg("PERP_A", 1.0, funding_enabled=True), ArbitrageLeg("PERP_B", -1.0)),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY, notional=10_000.0, reference_symbol="PERP_A"),
    )
    funding = {"PERP_A": pd.Series([0.0, 0.0, 0.01, 0.0], index=idx), "PERP_B": 0.0}

    event_funding = _event().run_package_arbitrage(idx, funding_spec, _signal(idx), funding_closes, funding_rate=funding)
    vector_funding = _vectorized().run_package_arbitrage(idx, funding_spec, _signal(idx), funding_closes, funding_rate=funding)

    assert build_arbitrage_domain_audit(event_funding, raise_on_fail=True)["status"] == "pass"
    assert build_arbitrage_domain_audit(vector_funding, raise_on_fail=True)["status"] == "pass"
    assert compare_native_arbitrage_results(event_funding, vector_funding, raise_on_fail=True)["status"] == "pass"

    index_closes = {
        "ETF": pd.Series([100.0, 100.0, 100.0, 100.0], index=idx),
        "A": pd.Series([50.0, 50.0, 52.0, 52.0], index=idx),
        "B": pd.Series([25.0, 25.0, 24.0, 24.0], index=idx),
    }
    index_spec = IndexBasketArbSpec(
        arb_id="AUDIT_INDEX",
        legs=(ArbitrageLeg("ETF", -1.0), ArbitrageLeg("A", 1.0), ArbitrageLeg("B", 2.0)),
        hedge_policy=HedgePolicy(HedgePolicyKind.NOTIONAL_NEUTRAL),
        sizing_policy=SizingPolicy(SizingPolicyKind.TARGET_GROSS_NOTIONAL, notional=20_000.0),
    )
    event_index = _event().run_package_arbitrage(idx, index_spec, _signal(idx), index_closes)
    vector_index = _vectorized().run_package_arbitrage(idx, index_spec, _signal(idx), index_closes)

    assert build_arbitrage_domain_audit(event_index, raise_on_fail=True)["status"] == "pass"
    assert build_arbitrage_domain_audit(vector_index, raise_on_fail=True)["status"] == "pass"
    assert compare_native_arbitrage_results(event_index, vector_index, raise_on_fail=True)["status"] == "pass"
