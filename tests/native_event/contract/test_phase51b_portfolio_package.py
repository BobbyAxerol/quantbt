from __future__ import annotations

import numpy as np
import pytest

from quantbt.core.package_execution_contracts import (
    PackageLegRequest,
    PackageState,
    PackageTransactionPolicy,
    execute_package_transaction_reference,
)
from quantbt.core.portfolio_execution_contracts import (
    PortfolioMarginAllocationPolicy,
    PortfolioTargetRejectReason,
    execute_portfolio_target_reference,
)


def test_portfolio_sequential_legacy_freezes_deterministic_symbol_order():
    result = execute_portfolio_target_reference(
        [0.0, 0.0], [8.0, 8.0], [100.0, 100.0], equity=1_000.0,
        leverages=1.0, fee_rates=0.0,
        policy=PortfolioMarginAllocationPolicy.SEQUENTIAL_LEGACY,
    )
    np.testing.assert_array_equal(result.accepted_units, [8.0, 0.0])
    assert result.rejection_reasons == ("ACCEPTED", "POST_COST_MARGIN")
    assert result.invariants()["passed"] is True


def test_portfolio_all_or_none_never_partially_mutates_target():
    result = execute_portfolio_target_reference(
        [1.0, -1.0], [8.0, -8.0], [100.0, 100.0], equity=1_000.0,
        leverages=1.0, fee_rates=0.001,
        policy=PortfolioMarginAllocationPolicy.ALL_OR_NONE_TARGET,
    )
    np.testing.assert_array_equal(result.accepted_units, [1.0, -1.0])
    assert result.rejection_reasons == ("ATOMIC_ROLLBACK", "ATOMIC_ROLLBACK")


def test_portfolio_reduce_first_releases_margin_before_increase():
    result = execute_portfolio_target_reference(
        [8.0, 0.0], [0.0, 8.0], [100.0, 100.0], equity=850.0,
        leverages=1.0, fee_rates=0.0,
        policy=PortfolioMarginAllocationPolicy.REDUCE_FIRST_THEN_INCREASE,
    )
    np.testing.assert_array_equal(result.accepted_units, [0.0, 8.0])
    assert result.available_equity_after == pytest.approx(50.0)


def test_portfolio_pro_rata_and_explicit_rejection_taxonomy():
    result = execute_portfolio_target_reference(
        [0.0, 0.0, 0.0], [10.0, 10.0, 1.0], [100.0, 100.0, np.nan], equity=1_000.0,
        policy=PortfolioMarginAllocationPolicy.PRO_RATA_TO_AVAILABLE_MARGIN,
        stale=[False, False, True], tradable=[True, True, True],
    )
    np.testing.assert_allclose(result.accepted_units[:2], [5.0, 5.0])
    assert result.rejection_reasons[0] == PortfolioTargetRejectReason.POST_COST_MARGIN.value
    assert result.rejection_reasons[2] == PortfolioTargetRejectReason.STALE_PRICE.value
    assert result.invariants()["passed"] is True


def _legs(*, stale_second=False, expensive_second=False):
    return (
        PackageLegRequest("primary", "BTC-PERP", 1.0, 100.0, 50.0, fee_rate=0.001),
        PackageLegRequest(
            "hedge", "BTC-QUARTER", -1.0, 102.0,
            2_000.0 if expensive_second else 50.0,
            fee_rate=0.001, source_age_ns=101 if stale_second else 0,
        ),
    )


def test_atomic_package_preflight_failure_has_no_partial_mutation():
    result = execute_package_transaction_reference(
        "basis-1", _legs(stale_second=True), available_equity=1_000.0,
        policy=PackageTransactionPolicy.ATOMIC_ALL_OR_NONE, max_staleness_ns=100,
    )
    assert result.final_state is PackageState.ABORTED
    assert result.fills.empty
    assert result.reserved_margin == result.released_margin == 0.0
    assert result.rejection_reasons == ("SIBLING_PREFLIGHT_REJECTED", "STALE_MARKET")
    assert result.invariants()["passed"] is True


def test_best_effort_exposes_residual_notional_and_releases_reservation():
    result = execute_package_transaction_reference(
        "basis-2", _legs(expensive_second=True), available_equity=1_000.0,
        policy=PackageTransactionPolicy.BEST_EFFORT,
    )
    assert result.final_state is PackageState.PARTIAL
    assert result.accepted_legs == ("primary",)
    assert result.rejected_legs == ("hedge",)
    assert result.residual_notional == pytest.approx(100.0)
    assert result.reserved_margin == result.released_margin
    assert result.invariants()["passed"] is True


def test_sequential_and_hedge_after_primary_have_explicit_state_sequences():
    sequential = execute_package_transaction_reference(
        "calendar", _legs(), available_equity=1_000.0,
        policy=PackageTransactionPolicy.SEQUENTIAL,
    )
    hedge_failure = execute_package_transaction_reference(
        "hedge-after", _legs(expensive_second=True), available_equity=1_000.0,
        policy=PackageTransactionPolicy.HEDGE_AFTER_PRIMARY,
    )
    assert sequential.final_state is PackageState.FILLED
    assert sequential.residual_notional == pytest.approx(-2.0)
    assert PackageState.COMMITTING.value in set(sequential.transitions["state"])
    assert hedge_failure.final_state is PackageState.PARTIAL
    assert PackageState.COMPENSATING.value in set(hedge_failure.transitions["state"])
