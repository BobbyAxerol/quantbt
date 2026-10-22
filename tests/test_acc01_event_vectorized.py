"""Independent ACC-01 controls for effective config and executed attribution."""

import numpy as np
import pandas as pd
import pytest

from quantbt import (AccountConfig, ExecutionConfig, NativeEventBackend, NativeEventConfig,
    NativeVectorizedBackend, NativeVectorizedConfig, OrderIntent, OrderCommand, OrderSide, OrderType,
    InstrumentSpec, ArbitrageLeg, BasisArbitrageSpec, ContractType, HedgePolicy,
    HedgePolicyKind, SizingPolicy, SizingPolicyKind)


INDEX = pd.date_range("2024-01-01 06:00", periods=4, freq="h", tz="UTC")
PRICE = pd.Series(100., index=INDEX)


def event(route, *, minimum=0., orders=None, execution=None, **overrides):
    prices = {"A": PRICE, "B": PRICE} if isinstance(overrides.get("leverage"), dict) else {"A": PRICE}
    orders = orders if orders is not None else [OrderIntent(INDEX[1], symbol, OrderSide.BUY,
        OrderType.MARKET, 1.) for symbol in prices]
    backend = NativeEventBackend(NativeEventConfig(account=AccountConfig(initial_capital=1000.),
        execution=execution or ExecutionConfig(min_order_notional=minimum), fee_rate=.01,
        use_funding=False, native_backend="python", report_level="standard", reactive_kernel_mode="single_pass"))
    kwargs = dict(closes=prices, highs=prices, lows=prices, **overrides)
    if route == "orders":
        return backend.run_orders(INDEX, orders, **kwargs)
    commands = tuple(OrderCommand.from_intent(o) for o in orders)
    if route == "commands":
        return backend.run_order_commands(INDEX, commands, **kwargs)
    class Once:
        def initialize(self, context):
            return commands
        def on_bar_close(self, context):
            return ()
        def finalize(self, context):
            return ()
    return backend.run_strategy(INDEX, Once(), **kwargs)


@pytest.mark.parametrize("route", ["orders", "commands", "callback"])
@pytest.mark.parametrize("field", ["contract_size", "leverage"])
@pytest.mark.parametrize("value", [0., -1., np.nan, np.inf, {"A": 0.}])
def test_t01_event_invalid_positive_financial_vectors_reject(route, field, value):
    with pytest.raises(ValueError):
        event(route, **{field: value})


@pytest.mark.parametrize("route", ["orders", "commands", "callback"])
def test_t01_t05_effective_minimum_and_matched_financial_control(route):
    control = event(route, minimum=100.)
    assert len(control.fills) == 1
    assert control.equity.iloc[-1] == pytest.approx(999.)
    assert control.fees.sum() == pytest.approx(1.)
    assert control.margin.initial_margin.iloc[-1] == pytest.approx(100.)
    assert len(event(route, minimum=200.).fills) == 0
    assert len(event(route, min_notional=200.).fills) == 0
    assert len(event(route, minimum=200., min_notional=10.).fills) == 0
    assert len(event(route, instruments={"A": InstrumentSpec("A", min_notional=200.)}, min_notional=10.).fills) == 0
    with pytest.raises(ValueError):
        event(route, fee_rate=-.01)


@pytest.mark.parametrize("route", ["orders", "commands", "callback"])
@pytest.mark.parametrize("close_qty,remaining", [(1., 1.), (5., 0.)])
def test_t05_minimum_exempts_risk_reductions_and_never_reverses(route, close_qty, remaining):
    orders = [OrderIntent(INDEX[1], "A", OrderSide.BUY, OrderType.MARKET, 2.),
              OrderIntent(INDEX[2], "A", OrderSide.SELL, OrderType.MARKET, close_qty, reduce_only=True)]
    result = event(route, minimum=150., orders=orders)
    assert len(result.fills) == 2
    assert result.positions.Position_A.iloc[-1] == remaining


@pytest.mark.parametrize("route", ["orders", "commands", "callback"])
def test_t10_heterogeneous_leverage_discloses_allocation_dependence(route):
    result = event(route, leverage={"A": 1., "B": 10.})
    assert result.margin.initial_margin.iloc[-1] == pytest.approx(110.)
    assert result.metadata["initial_buying_power"] is None
    assert result.metadata["buying_power_model"] == "allocation_dependent"
    assert result.metadata["leverage_by_symbol"] == {"A": 1., "B": 10.}
    assert event(route).metadata["initial_buying_power"] == 1000.


@pytest.mark.parametrize("bps", [10000., 20000.])
@pytest.mark.parametrize("cls", [NativeVectorizedConfig, NativeEventConfig])
def test_t08_nonpositive_execution_price_configuration_rejects(cls, bps):
    with pytest.raises(ValueError, match="positive execution prices"):
        cls(account=AccountConfig(initial_capital=1000.), execution=ExecutionConfig(slippage_bps=bps))


def test_t08_valid_vectorized_slippage_and_t10_capacity():
    backend = NativeVectorizedBackend(NativeVectorizedConfig(account=AccountConfig(initial_capital=1000.),
        execution=ExecutionConfig(slippage_bps=100.), fee_rate=.01, use_funding=False))
    result = backend.run_target_units(INDEX, {"A": pd.Series([0., -1., -1., -1.], index=INDEX)},
        {"A": PRICE}, highs={"A": PRICE}, lows={"A": PRICE})
    assert result.fees.sum() == pytest.approx(.99)
    assert result.equity.iloc[-1] == pytest.approx(998.01)
    result = backend.run_target_units(INDEX, {s: pd.Series([0., 1., 1., 1.], index=INDEX) for s in ("A", "B")},
        {"A": PRICE, "B": PRICE}, highs={"A": PRICE, "B": PRICE}, lows={"A": PRICE, "B": PRICE},
        leverage={"A": 1., "B": 10.})
    assert result.metadata["initial_buying_power"] is None


def basis_case(runtime="numba", *, liquidate=True, event_backend=False, slippage=0.):
    closes = {s: PRICE for s in ("P", "F")}
    low = {s: pd.Series([100., 100., 10. if liquidate else 100., 100.], index=INDEX) for s in closes}
    high = {s: pd.Series([100., 100., 190. if liquidate else 100., 100.], index=INDEX) for s in closes}
    spec = BasisArbitrageSpec(arb_id="acc01-basis", legs=(
        ArbitrageLeg(symbol="P", ratio=-1., role="perp", contract_type=ContractType.LINEAR, funding_enabled=True),
        ArbitrageLeg(symbol="F", ratio=1., role="future", contract_type=ContractType.LINEAR, funding_enabled=False)),
        hedge_policy=HedgePolicy(kind=HedgePolicyKind.BASE_QTY_EQUAL, freeze_on_entry=True),
        sizing_policy=SizingPolicy(kind=SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
            notional=1000., reference_symbol="P"))
    account = AccountConfig(initial_capital=100., leverage=100.)
    if event_backend:
        backend = NativeEventBackend(NativeEventConfig(account=account, fee_rate=.001,
            execution=ExecutionConfig(slippage_bps=slippage), use_funding=True, native_backend="python"))
    else:
        backend = NativeVectorizedBackend(NativeVectorizedConfig(account=account, fee_rate=.001,
            execution=ExecutionConfig(slippage_bps=slippage), use_funding=True, target_runtime=runtime))
    signal = pd.Series([0., 1., 1., 0.], index=INDEX)
    return backend.run_basis_arbitrage(INDEX, spec, signal, closes, highs=high, lows=low, funding_rate=.01)


@pytest.mark.parametrize("runtime", ["numba", "rust"])
def test_t02_package_liquidation_uses_executed_costs_not_position_reconstruction(runtime):
    result = basis_case(runtime)
    assert result.equity.tolist() == pytest.approx([100., 98., 0., 0.])
    leg = result.metadata["leg_pnl_report"]
    assert leg.fee.sum() == pytest.approx(2.)
    assert leg.funding_pnl.sum() == 0.
    assert leg.liquidation_pnl.sum() == pytest.approx(-98.)
    assert leg.total_pnl.sum() == pytest.approx(-100.)
    assert result.metadata["leg_pnl_authority"] == "executed_account_buffers_v1"
    assert "_executed_account_attribution" not in result.metadata
    np.testing.assert_allclose(result.metadata["package_pnl_report"].pnl_residual, 0., atol=1e-10)
    if runtime == "rust":
        assert result.metadata["target_runtime"] == "rust_direct_target_v1"
        assert result.metadata["native_target_execution"]["native_execution_passes"] == 1
        assert result.metadata["native_target_execution"]["boundary_calls"] == 1


@pytest.mark.parametrize("event_backend", [False, True])
def test_t02_nonliquidating_package_cost_identity(event_backend):
    result = basis_case(liquidate=False, event_backend=event_backend, slippage=2.)
    leg = result.metadata["leg_pnl_report"]
    assert leg.total_pnl.sum() == pytest.approx(result.equity.iloc[-1] - 100.)
    assert leg.fee.sum() == pytest.approx(result.fees.sum())
    assert -leg.funding_pnl.sum() == pytest.approx(result.funding.sum())


def test_t02_target_score_and_public_compact_do_not_retain_attribution():
    backend = NativeVectorizedBackend(NativeVectorizedConfig(account=AccountConfig(initial_capital=1000.), use_funding=False))
    result = backend.run_target_units(INDEX, {"A": pd.Series([0., 1., 1., 0.], index=INDEX)},
        {"A": PRICE}, highs={"A": PRICE}, lows={"A": PRICE})
    assert "_executed_account_attribution" not in result.metadata
