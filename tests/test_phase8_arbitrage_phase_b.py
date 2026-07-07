from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    ArbitrageSpec,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    CarryModel,
    ContractType,
    CostModel,
    FundingArbitrageSpec,
    HedgePolicy,
    HedgePolicyKind,
    LifecycleModel,
    LifecycleModelKind,
    MarginModel,
    PackageExecutionKind,
    SignalModel,
    SizingPolicy,
    SizingPolicyKind,
    SpreadFormula,
    SpreadFormulaKind,
)


def _leg(symbol, *, ratio=1.0, role="leg", expiry=None, funding_enabled=False, contract_type=ContractType.LINEAR):
    return ArbitrageLeg(
        symbol=symbol,
        ratio=ratio,
        role=role,
        contract_type=contract_type,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=10.0,
        expiry=expiry,
        funding_enabled=funding_enabled,
    )


def _hedge():
    return HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL)


def _sizing(reference_symbol="A"):
    return SizingPolicy(
        kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
        notional=10_000.0,
        reference_symbol=reference_symbol,
    )


def test_phase_b_models_coerce_string_enums_and_normalize_expiry_to_utc():
    leg = _leg("A", contract_type="linear", expiry="2024-03-29 08:00:00")
    execution = ArbExecutionPolicy(kind="best_effort", order_type="market", tif="ioc")
    spec = ArbitrageSpec(
        arb_id="ARB-001",
        legs=(leg, _leg("B", ratio=-1.0)),
        hedge_policy=HedgePolicy(kind="base_qty_equal"),
        sizing_policy=_sizing("A"),
        spread_formula=SpreadFormula(kind="price_diff", base_symbol="A", quote_symbol="B"),
        execution_policy=execution,
    )

    assert leg.contract_type is ContractType.LINEAR
    assert str(leg.expiry.tz) == "UTC"
    assert execution.kind is PackageExecutionKind.BEST_EFFORT
    assert execution.allow_partial_fill is True
    assert spec.spread_formula.kind is SpreadFormulaKind.PRICE_DIFF


def test_phase_b_rejects_reference_symbols_outside_legs():
    with pytest.raises(ValueError, match="reference_symbol"):
        ArbitrageSpec(
            arb_id="ARB-001",
            legs=(_leg("A"), _leg("B", ratio=-1.0)),
            hedge_policy=_hedge(),
            sizing_policy=_sizing("MISSING"),
        )


def test_phase_b_rejects_spread_symbols_outside_legs():
    with pytest.raises(ValueError, match="base_symbol"):
        ArbitrageSpec(
            arb_id="ARB-001",
            legs=(_leg("A"), _leg("B", ratio=-1.0)),
            hedge_policy=_hedge(),
            sizing_policy=_sizing("A"),
            spread_formula=SpreadFormula(kind=SpreadFormulaKind.PRICE_DIFF, base_symbol="MISSING"),
        )


def test_phase_b_lifecycle_requires_expiry_when_settlement_or_roll_is_requested():
    with pytest.raises(ValueError, match="expiry lifecycle"):
        ArbitrageSpec(
            arb_id="ARB-001",
            legs=(_leg("A"), _leg("B", ratio=-1.0)),
            hedge_policy=_hedge(),
            sizing_policy=_sizing("A"),
            lifecycle_model=LifecycleModel(kind=LifecycleModelKind.EXPIRY_SETTLEMENT),
        )


def test_phase_b_calendar_spread_requires_all_legs_to_have_distinct_expiries():
    common_expiry = pd.Timestamp("2024-03-29", tz="UTC")
    with pytest.raises(ValueError, match="distinct expiries"):
        CalendarSpreadSpec(
            arb_id="CAL-001",
            legs=(
                _leg("FUT1", expiry=common_expiry),
                _leg("FUT2", ratio=-1.0, expiry=common_expiry),
            ),
            hedge_policy=_hedge(),
            sizing_policy=_sizing("FUT1"),
        )

    spec = CalendarSpreadSpec(
        arb_id="CAL-002",
        legs=(
            _leg("FUT1", expiry="2024-03-29"),
            _leg("FUT2", ratio=-1.0, expiry="2024-06-28"),
        ),
        hedge_policy=_hedge(),
        sizing_policy=_sizing("FUT1"),
    )
    assert spec.arb_type.value == "calendar_spread"


def test_phase_b_funding_arbitrage_requires_funding_enabled_leg():
    with pytest.raises(ValueError, match="funding-enabled"):
        FundingArbitrageSpec(
            arb_id="FUND-001",
            legs=(_leg("PERP_A"), _leg("PERP_B", ratio=-1.0)),
            hedge_policy=_hedge(),
            sizing_policy=_sizing("PERP_A"),
        )

    spec = FundingArbitrageSpec(
        arb_id="FUND-002",
        legs=(_leg("PERP_A", funding_enabled=True), _leg("PERP_B", ratio=-1.0)),
        hedge_policy=_hedge(),
        sizing_policy=_sizing("PERP_A"),
    )
    assert spec.arb_type.value == "funding"


def test_phase_b_model_value_validation_and_semantic_role_uniqueness():
    with pytest.raises(ValueError, match="cost bps"):
        CostModel(fee_bps=-1.0)
    with pytest.raises(ValueError, match="funding_interval_hours"):
        CarryModel(kind="funding", funding_interval_hours=0.0)
    with pytest.raises(ValueError, match="hedged_margin_offset"):
        MarginModel(hedged_margin_offset=1.5)
    with pytest.raises(ValueError, match="lookback"):
        SignalModel(kind="zscore", lookback=0)

    # Default role="leg" may repeat, but semantic roles should not.
    ArbitrageSpec(
        arb_id="OK-DEFAULT-ROLES",
        legs=(_leg("A"), _leg("B", ratio=-1.0)),
        hedge_policy=_hedge(),
        sizing_policy=_sizing("A"),
    )
    with pytest.raises(ValueError, match="unique roles"):
        BasisArbitrageSpec(
            arb_id="BAD-ROLES",
            legs=(_leg("A", role="perp"), _leg("B", ratio=-1.0, role="perp")),
            hedge_policy=_hedge(),
            sizing_policy=_sizing("A"),
        )

