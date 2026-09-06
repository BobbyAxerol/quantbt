"""Phase 66 direct Rust target/vectorized authority contracts.

The tests intentionally keep the legacy Numba units kernel alive as a
reproducibility comparator.  Rust target execution is explicit in this phase:
``target_runtime='rust'`` or ``NativeTargetWfoRuntimeV2`` is required; no
public auto route is changed by this test module.
"""

from __future__ import annotations

import importlib.util
import math

import numpy as np
import pandas as pd
import pytest

from quantbt.backends.native_strategy_ir import NativeIRFold
from quantbt.backends.native_vectorized import NativeVectorizedBackend, NativeVectorizedConfig
from quantbt.backends.native_wfo import NativeTargetWfoRuntimeV2
from quantbt.core.schema import AccountConfig, ExecutionConfig
from quantbt.core.target_intents import compile_static_dca_target_tape
from quantbt.preparation.native_execution import NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _manual_quantize(qty: float, price: float, contract_size: float, step: float, min_qty: float, min_notional: float) -> float:
    """Independent exchange-lot oracle; does not call QuantBT's quantizer."""

    if qty == 0.0:
        return 0.0
    sign = 1.0 if qty > 0.0 else -1.0
    amount = abs(float(qty))
    if step > 0.0:
        amount = math.floor(amount / step + 1.0e-12) * step
    if amount <= 0.0:
        return 0.0
    if min_qty > 0.0 and amount + 1.0e-12 < min_qty:
        return 0.0
    if min_notional > 0.0 and amount * price * contract_size + 1.0e-12 < min_notional:
        return 0.0
    return sign * amount


def _independent_units_oracle(
    *,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    targets: np.ndarray,
    funding: np.ndarray,
    funding_mask: np.ndarray,
    initial_capital: float,
    leverage: np.ndarray,
    maintenance_ratio: float,
    fee_rate: np.ndarray,
    contract_size: np.ndarray,
    slippage: float,
    use_funding: bool,
    qty_step: np.ndarray,
    min_qty: np.ndarray,
    min_notional: np.ndarray,
) -> dict[str, object]:
    """Small independent reference for the frozen close-target units contract.

    This deliberately reproduces the public contract as a plain Python loop,
    rather than calling either the Numba kernel or the Rust request.  It is
    narrow by design: non-tradable/stale invalid-target handling belongs to the
    Rust-only target contract and is exercised separately below.
    """

    bars, symbols = closes.shape
    quantized = np.empty_like(targets, dtype=np.float64)
    for bar in range(bars):
        for symbol in range(symbols):
            quantized[bar, symbol] = _manual_quantize(
                float(targets[bar, symbol]),
                float(closes[bar, symbol]),
                float(contract_size[symbol]),
                float(qty_step[symbol]),
                float(min_qty[symbol]),
                float(min_notional[symbol]),
            )

    equity = np.zeros(bars, dtype=np.float64)
    positions = np.zeros((bars, symbols), dtype=np.float64)
    fees = np.zeros(bars, dtype=np.float64)
    turnover = np.zeros(bars, dtype=np.float64)
    funding_cost = np.zeros(bars, dtype=np.float64)
    initial_margin = np.zeros(bars, dtype=np.float64)
    maintenance_margin = np.zeros(bars, dtype=np.float64)
    rejected = np.zeros(bars, dtype=np.int64)
    reject_code = np.zeros(bars, dtype=np.int64)
    current = np.zeros(symbols, dtype=np.float64)
    account = float(initial_capital)
    liquidated = False
    liquidation_bar = -1
    liquidation_reason = 0
    equity[0] = account

    for bar in range(1, bars):
        if liquidated:
            continue
        for symbol in range(symbols):
            account += current[symbol] * (closes[bar, symbol] - closes[bar - 1, symbol]) * contract_size[symbol]

        worst_equity = account
        worst_maintenance = 0.0
        for symbol in range(symbols):
            position = current[symbol]
            if position == 0.0:
                continue
            worst_price = lows[bar, symbol] if position > 0.0 else highs[bar, symbol]
            worst_equity += position * (worst_price - closes[bar, symbol]) * contract_size[symbol]
            worst_maintenance += abs(position) * worst_price * contract_size[symbol] * maintenance_ratio
        if worst_maintenance > 0.0 and worst_equity <= worst_maintenance:
            liquidated = True
            liquidation_bar = bar
            liquidation_reason = 1
            account = 0.0
            equity[bar] = 0.0
            continue

        if bool(funding_mask[bar]) and use_funding:
            for symbol in range(symbols):
                amount = current[symbol] * closes[bar, symbol] * contract_size[symbol] * funding[bar, symbol]
                account -= amount
                funding_cost[bar] += amount

        close_maintenance = sum(
            abs(current[symbol]) * closes[bar, symbol] * contract_size[symbol] * maintenance_ratio
            for symbol in range(symbols)
        )
        if close_maintenance > 0.0 and account <= close_maintenance:
            liquidated = True
            liquidation_bar = bar
            liquidation_reason = 2
            account = 0.0
            equity[bar] = 0.0
            continue

        current_initial = sum(
            abs(current[symbol]) * closes[bar, symbol] * contract_size[symbol] / leverage[symbol]
            for symbol in range(symbols)
        )
        available = max(account - current_initial, 0.0)
        for symbol in range(symbols):
            target = quantized[bar, symbol]
            delta = target - current[symbol]
            if abs(delta) < 1.0e-12:
                continue
            price = closes[bar, symbol]
            execution_price = price * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
            notional = abs(delta) * execution_price * contract_size[symbol]
            fee = notional * fee_rate[symbol]
            slippage_cost = abs(delta) * abs(execution_price - price) * contract_size[symbol]
            old_initial = abs(current[symbol]) * price * contract_size[symbol] / leverage[symbol]
            new_initial = abs(target) * execution_price * contract_size[symbol] / leverage[symbol]
            margin_delta = new_initial - old_initial
            required = fee + slippage_cost + max(margin_delta, 0.0)
            if required > available:
                rejected[bar] += 1
                reject_code[bar] = 1
                continue
            account -= fee + slippage_cost
            current[symbol] = target
            fees[bar] += fee
            turnover[bar] += notional
            available = max(available - fee - slippage_cost - margin_delta, 0.0)

        close_initial = sum(
            abs(current[symbol]) * closes[bar, symbol] * contract_size[symbol] / leverage[symbol]
            for symbol in range(symbols)
        )
        close_maintenance = sum(
            abs(current[symbol]) * closes[bar, symbol] * contract_size[symbol] * maintenance_ratio
            for symbol in range(symbols)
        )
        if close_maintenance > 0.0 and account <= close_maintenance:
            liquidated = True
            liquidation_bar = bar
            liquidation_reason = 3
            account = 0.0
            equity[bar] = 0.0
            continue
        positions[bar] = current
        initial_margin[bar] = close_initial
        maintenance_margin[bar] = close_maintenance
        equity[bar] = account

    return {
        "equity": equity,
        "positions": positions,
        "fees": fees,
        "turnover": turnover,
        "funding": funding_cost,
        "initial_margin": initial_margin,
        "maintenance_margin": maintenance_margin,
        "rejected": rejected,
        "reject_code": reject_code,
        "liquidated": liquidated,
        "liquidation_bar": liquidation_bar,
        "liquidation_reason": liquidation_reason,
    }


def _target_fixture(*, symbols: int = 1, initial_capital: float = 10_000.0):
    bars = 12
    index = pd.date_range("2025-01-01", periods=bars, freq="1h", tz="UTC")
    first = np.array([100.0, 101.0, 104.0, 102.0, 98.0, 101.0, 106.0, 103.0, 99.0, 100.0, 105.0, 103.0])
    closes = np.column_stack([first + float(column) * 3.0 for column in range(symbols)])
    highs = closes + 2.0
    lows = closes - 2.0
    funding = np.zeros((bars, symbols), dtype=np.float64)
    funding[3] = 0.0001
    funding[8] = -0.0002
    funding_mask = np.zeros(bars, dtype=np.bool_)
    funding_mask[[3, 8]] = True
    cache = NativeExecutionPreparationCache()
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.view("int64"), dtype=np.int64),
        opens=np.ascontiguousarray(closes),
        highs=np.ascontiguousarray(highs),
        lows=np.ascontiguousarray(lows),
        closes=np.ascontiguousarray(closes),
        volumes=np.ones_like(closes),
        funding=np.ascontiguousarray(funding),
        funding_mask=funding_mask,
        symbols=[f"S{column}" for column in range(symbols)],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.full(symbols, 1.5, dtype=np.float64),
        leverages=np.full(symbols, 3.0, dtype=np.float64),
        fee_rates=np.full(symbols, 0.0005, dtype=np.float64),
        initial_capital=initial_capital,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=True,
    )
    return index, closes, highs, lows, funding, funding_mask, cache, template


def _direct_payload(cache, template, *, targets, output_profile=1, **kwargs):
    request = cache.direct_target_request(
        template,
        targets=np.ascontiguousarray(targets, dtype=np.float64),
        output_profile=output_profile,
        **kwargs,
    )
    return dict(request.core.execute_typed().as_dict())


def _vector_backend(*, target_runtime: str, initial_capital: float = 10_000.0, leverage: float = 3.0):
    return NativeVectorizedBackend(
        NativeVectorizedConfig(
            account=AccountConfig(
                initial_capital=initial_capital,
                leverage=leverage,
                maintenance_ratio=0.005,
            ),
            execution=ExecutionConfig(slippage_bps=2.0),
            fee_rate=0.0005,
            use_funding=True,
            target_runtime=target_runtime,
        )
    )


def test_target_units_three_way_parity_with_independent_oracle_and_numba_production():
    index, closes, highs, lows, funding, funding_mask, cache, template = _target_fixture(symbols=2)
    targets = np.array(
        [
            [0.0, 0.0], [1.37, -0.62], [1.37, -0.62], [0.74, 0.31],
            [-1.12, 1.42], [-1.12, 1.42], [0.0, 0.0], [2.26, -1.74],
            [2.26, -1.74], [-0.49, 0.88], [-0.49, 0.88], [0.0, 0.0],
        ],
        dtype=np.float64,
    )
    qty_step = np.array([0.25, 0.10], dtype=np.float64)
    min_qty = np.array([0.25, 0.10], dtype=np.float64)
    min_notional = np.array([20.0, 20.0], dtype=np.float64)
    oracle = _independent_units_oracle(
        closes=closes,
        highs=highs,
        lows=lows,
        targets=targets,
        funding=funding,
        funding_mask=funding_mask,
        initial_capital=10_000.0,
        leverage=np.full(2, 3.0),
        maintenance_ratio=0.005,
        fee_rate=np.full(2, 0.0005),
        contract_size=np.full(2, 1.5),
        slippage=0.0002,
        use_funding=True,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )
    rust = _direct_payload(
        cache,
        template,
        targets=targets,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )
    for field in ("equity", "fees", "turnover", "funding", "initial_margin", "maintenance_margin"):
        np.testing.assert_allclose(np.asarray(rust[field]), oracle[field], rtol=0.0, atol=1.0e-11)
    np.testing.assert_allclose(
        np.asarray(rust["positions"]).reshape(closes.shape), oracle["positions"], rtol=0.0, atol=1.0e-12
    )
    np.testing.assert_array_equal(rust["direct_target_rejected_by_bar"], oracle["rejected"])
    np.testing.assert_array_equal(rust["direct_target_reject_code_by_bar"], oracle["reject_code"])

    close_frame = {f"S{column}": pd.Series(closes[:, column], index=index) for column in range(2)}
    high_frame = {f"S{column}": pd.Series(highs[:, column], index=index) for column in range(2)}
    low_frame = {f"S{column}": pd.Series(lows[:, column], index=index) for column in range(2)}
    target_frame = {f"S{column}": pd.Series(targets[:, column], index=index) for column in range(2)}
    # The vectorized public facade infers funding-event bars from its public
    # schedule. This assertion therefore validates all non-funding accounting
    # fields and the same close target/constraint semantics against Numba.
    common = dict(
        datetime_index=index,
        target_units=target_frame,
        closes=close_frame,
        highs=high_frame,
        lows=low_frame,
        funding_rate={f"S{column}": pd.Series(funding[:, column], index=index) for column in range(2)},
        contract_size={"S0": 1.5, "S1": 1.5},
        leverage={"S0": 3.0, "S1": 3.0},
        qty_step={"S0": 0.25, "S1": 0.10},
        min_qty={"S0": 0.25, "S1": 0.10},
        min_notional={"S0": 20.0, "S1": 20.0},
        symbols=["S0", "S1"],
    )
    numba = _vector_backend(target_runtime="numba").run_target_units(**common)
    rust_public = _vector_backend(target_runtime="rust").run_target_units(**common)
    for field in ("equity", "positions", "fees", "funding", "margin", "diagnostics"):
        np.testing.assert_allclose(
            getattr(rust_public, field).to_numpy(),
            getattr(numba, field).to_numpy(),
            rtol=0.0,
            atol=1.0e-11,
        )
    assert rust_public.metadata["target_runtime"] == "rust_direct_target_v1"
    assert rust_public.metadata["native_target_execution"]["native_target_no_order_arena"] is True


def test_target_contracts_are_distinct_and_leverage_does_not_scale_weights():
    _, closes, _, _, _, _, cache, template = _target_fixture(symbols=1)
    zero_cost_template = cache.prepare_template(
        template.market,
        contract_sizes=np.array([1.0]),
        leverages=np.array([5.0]),
        fee_rates=np.array([0.0]),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
    )
    notionals = np.zeros((len(closes), 1), dtype=np.float64)
    notionals[1:4, 0] = 1_000.0
    notional = _direct_payload(cache, zero_cost_template, targets=notionals, target_kind="notional")
    positions = np.asarray(notional["positions"]).reshape(len(closes), 1)
    np.testing.assert_allclose(positions[1:4, 0], 1_000.0 / closes[1:4, 0], rtol=0.0, atol=1.0e-12)

    weights = np.zeros((len(closes), 1), dtype=np.float64)
    weights[1:4, 0] = 0.10
    weight = _direct_payload(cache, zero_cost_template, targets=weights, target_kind="weight")
    fraction = _direct_payload(
        cache,
        zero_cost_template,
        targets=np.where(weights > 0.0, 1.0, 0.0),
        target_kind="equity_fraction",
        equity_fraction=np.array([0.10]),
    )
    np.testing.assert_allclose(weight["positions"], fraction["positions"], rtol=0.0, atol=1.0e-12)
    # Changing leverage changes margin/buying power only. It does not alter a
    # weight denominator or silently multiply a target quantity.
    leverage_one = cache.prepare_template(
        template.market,
        contract_sizes=np.array([1.0]),
        leverages=np.array([1.0]),
        fee_rates=np.array([0.0]),
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
    )
    small_weight = weights * 0.10
    low_leverage = _direct_payload(cache, leverage_one, targets=small_weight, target_kind="weight")
    high_leverage = _direct_payload(cache, zero_cost_template, targets=small_weight, target_kind="weight")
    np.testing.assert_allclose(low_leverage["positions"], high_leverage["positions"], rtol=0.0, atol=1.0e-12)


def test_target_rejection_margin_and_liquidation_parity_are_explicit():
    index, closes, highs, lows, funding, _, cache, template = _target_fixture(symbols=1, initial_capital=1_000.0)
    targets = np.zeros((len(closes), 1), dtype=np.float64)
    targets[1, 0] = 10_000.0
    rust = _direct_payload(cache, template, targets=targets)
    assert int(np.asarray(rust["direct_target_rejected_by_bar"])[1]) == 1
    assert int(np.asarray(rust["direct_target_reject_code_by_bar"])[1]) == 1
    numba = _vector_backend(target_runtime="numba", initial_capital=1_000.0).run_target_units(
        datetime_index=index,
        target_units={"S0": pd.Series(targets[:, 0], index=index)},
        closes={"S0": pd.Series(closes[:, 0], index=index)},
        highs={"S0": pd.Series(highs[:, 0], index=index)},
        lows={"S0": pd.Series(lows[:, 0], index=index)},
        funding_rate={"S0": pd.Series(funding[:, 0], index=index)},
        contract_size=1.5,
        leverage=3.0,
        symbols=["S0"],
    )
    np.testing.assert_array_equal(
        np.asarray(rust["direct_target_rejected_by_bar"]),
        numba.diagnostics["rejected_orders"].to_numpy(),
    )

    # A carried long is admissible at bar 1 then liquidates against bar 2 low
    # before target processing. Rust and Numba must agree on the account event.
    short_index = index[:4]
    collapse_close = np.array([[100.0], [100.0], [100.0], [100.0]])
    collapse_high = collapse_close + 1.0
    collapse_low = np.array([[99.0], [99.0], [70.0], [99.0]])
    collapse_funding = np.zeros_like(collapse_close)
    collapse_mask = np.zeros(4, dtype=bool)
    collapse_market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(short_index.view("int64"), dtype=np.int64),
        opens=collapse_close,
        highs=collapse_high,
        lows=collapse_low,
        closes=collapse_close,
        volumes=np.ones_like(collapse_close),
        funding=collapse_funding,
        funding_mask=collapse_mask,
        symbols=["S0"],
    )
    collapse_template = cache.prepare_template(
        collapse_market,
        contract_sizes=np.array([1.0]),
        leverages=np.array([10.0]),
        fee_rates=np.array([0.0005]),
        initial_capital=100.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=False,
    )
    collapse_targets = np.array([[0.0], [5.0], [5.0], [0.0]])
    collapse_rust = _direct_payload(cache, collapse_template, targets=collapse_targets)
    assert collapse_rust["liquidated"] is True
    assert collapse_rust["liquidation_bar"] == 2
    collapse_numba = _vector_backend(target_runtime="numba", initial_capital=100.0, leverage=10.0).run_target_units(
        datetime_index=short_index,
        target_units={"S0": pd.Series(collapse_targets[:, 0], index=short_index)},
        closes={"S0": pd.Series(collapse_close[:, 0], index=short_index)},
        highs={"S0": pd.Series(collapse_high[:, 0], index=short_index)},
        lows={"S0": pd.Series(collapse_low[:, 0], index=short_index)},
        contract_size=1.0,
        leverage=10.0,
        symbols=["S0"],
    )
    assert collapse_numba.liquidated is True
    assert collapse_numba.liquidation_bar == 2
    np.testing.assert_allclose(collapse_rust["equity"], collapse_numba.equity.to_numpy(), rtol=0.0, atol=1.0e-12)


def test_invalid_target_masks_profiles_and_static_dca_contracts():
    index, closes, highs, lows, _, _, cache, template = _target_fixture(symbols=1)
    targets = np.zeros((len(closes), 1), dtype=np.float64)
    targets[1:4, 0] = 1.0
    with pytest.raises(ValueError, match="non-finite|finite|invalid"):
        _direct_payload(cache, template, targets=np.where(np.arange(len(closes))[:, None] == 2, np.nan, targets))
    with pytest.raises(NotImplementedError, match="next-open and next-close"):
        cache.direct_target_request(template, targets=targets, timing="next_open_v1")
    with pytest.raises(ValueError, match="timing"):
        cache.direct_target_request(template, targets=targets, timing=9)

    non_tradable = np.ones_like(targets, dtype=bool)
    non_tradable[1, 0] = False
    blocked = _direct_payload(cache, template, targets=targets, tradable=non_tradable)
    assert int(np.asarray(blocked["direct_target_rejected_by_bar"])[1]) == 1
    assert int(np.asarray(blocked["direct_target_reject_code_by_bar"])[1]) == 3
    stale = _direct_payload(cache, template, targets=targets, stale=~non_tradable)
    assert int(np.asarray(stale["direct_target_reject_code_by_bar"])[1]) == 4

    score = _direct_payload(cache, template, targets=targets, output_profile=0)
    compact = _direct_payload(cache, template, targets=targets, output_profile=1)
    audit = _direct_payload(cache, template, targets=targets, output_profile=2)
    for key in ("final_equity", "total_fee", "total_funding", "total_turnover", "liquidated"):
        assert score[key] == pytest.approx(compact[key])
        assert score[key] == pytest.approx(audit[key])
    assert compact["native_execution_runtime_class"] == "rust_direct_target_v1"
    assert compact["native_execution_workload"] == "target_units_v1"

    schedule = {index[1]: 1.0, index[4]: 2.0, index[8]: 0.0}
    compiled = compile_static_dca_target_tape(index, schedule)
    np.testing.assert_allclose(
        compiled.target_units.to_numpy(),
        np.array([0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0]),
    )
    backend = _vector_backend(target_runtime="rust")
    dca = backend.run_static_dca_schedule(
        index,
        symbol="S0",
        closes=pd.Series(closes[:, 0], index=index),
        schedule=schedule,
        contract_size=1.5,
        highs={"S0": pd.Series(highs[:, 0], index=index)},
        lows={"S0": pd.Series(lows[:, 0], index=index)},
        symbols=["S0"],
    )
    expected = pd.Series(0.0, index=index)
    for timestamp, target in schedule.items():
        expected.loc[timestamp:] = target
    direct = backend.run_target_units(
        index,
        target_units={"S0": expected},
        closes={"S0": pd.Series(closes[:, 0], index=index)},
        highs={"S0": pd.Series(highs[:, 0], index=index)},
        lows={"S0": pd.Series(lows[:, 0], index=index)},
        contract_size=1.5,
        symbols=["S0"],
    )
    np.testing.assert_allclose(dca.equity.to_numpy(), direct.equity.to_numpy(), rtol=0.0, atol=1.0e-12)
    assert dca.metadata["static_target_tape"]["execution_class"] == "static_schedule_target_v1"
    with pytest.raises(TypeError, match="StaticDcaTargetStepV1"):
        backend.run_static_dca_schedule(
            index,
            symbol="S0",
            closes=pd.Series(closes[:, 0], index=index),
            schedule=[object()],
        )
    # The historical Numba route still treats missing target entries as flat
    # compatibility input. An explicitly requested Rust target run preserves
    # the NaN and rejects the request instead of silently converting it to 0.
    invalid_public = pd.Series(0.0, index=index)
    invalid_public.iloc[3] = np.nan
    with pytest.raises(ValueError, match="non-finite|finite"):
        backend.run_target_units(
            index,
            target_units={"S0": invalid_public},
            closes={"S0": pd.Series(closes[:, 0], index=index)},
            highs={"S0": pd.Series(highs[:, 0], index=index)},
            lows={"S0": pd.Series(lows[:, 0], index=index)},
            symbols=["S0"],
        )


def test_target_wfo_uses_one_market_plan_and_audit_replays_selected_candidates():
    _, closes, _, _, _, _, cache, template = _target_fixture(symbols=1)
    folds = (
        NativeIRFold(10, 0, 0, 4, 4, 8),
        NativeIRFold(20, 0, 0, 8, 8, len(closes)),
    )
    runtime = NativeTargetWfoRuntimeV2(template, folds)
    targets = np.zeros((3, len(closes), 1), dtype=np.float64)
    targets[0, 4:8, 0] = 1.0
    targets[1, 4:8, 0] = -1.0
    targets[2, 8:, 0] = 1.0
    ids = np.asarray([101, 202, 303], dtype=np.uint64)
    try:
        score = runtime.score_shared(targets, candidate_ids=ids)
        prepared = runtime.prepare_shared(targets, candidate_ids=ids)
        repeated = runtime.score_prepared_batch(prepared)
        np.testing.assert_allclose(score.final_equity, repeated.final_equity, rtol=0.0, atol=1.0e-12)
        assert score.terminal_fingerprint == repeated.terminal_fingerprint
        assert score.metadata["market_copy_bytes"] == 0
        assert score.metadata["native_target_no_order_arena"] is True
        assert score.metadata["intent_kind"] == "direct_target_v1"
        assert prepared.intent_ingest_bytes > 0

        # Each candidate/fold starts from a fresh account over exactly its OOS
        # local template. Compare that detached batch row to an independently
        # constructed direct target request; no signal/command conversion is
        # allowed on either side.
        for fold in folds:
            local_template = cache.window_template(
                template,
                start=fold.test_start,
                end=fold.test_end,
            )
            for candidate_index, candidate_id in enumerate(ids):
                direct = _direct_payload(
                    cache,
                    local_template,
                    targets=targets[candidate_index, fold.test_start : fold.test_end],
                    output_profile=0,
                )
                row = (score.candidate_id == candidate_id) & (score.fold_id == fold.fold_id)
                assert int(row.sum()) == 1
                slot = int(np.flatnonzero(row)[0])
                assert score.final_equity[slot] == pytest.approx(direct["final_equity"])
                assert score.total_fee[slot] == pytest.approx(direct["total_fee"])
                assert score.total_funding[slot] == pytest.approx(direct["total_funding"])
                assert score.turnover[slot] == pytest.approx(direct["total_turnover"])
                assert score.terminal_fingerprint[slot] == direct["native_execution_terminal_fingerprint"]

        audit = runtime.audit_prepared_batch(
            prepared,
            selected_candidate_ids=np.asarray([202], dtype=np.uint64),
            expected_intent_fingerprint=score.intent_fingerprint,
        )
        audit.assert_audit_parity(score)
        assert audit.audit is True

        cube = np.repeat(targets[np.newaxis, ...], len(folds), axis=0)
        per_fold = runtime.score_per_fold(cube, candidate_ids=ids)
        np.testing.assert_allclose(score.final_equity, per_fold.final_equity, rtol=0.0, atol=1.0e-12)
        assert score.terminal_fingerprint == per_fold.terminal_fingerprint
        with pytest.raises(ValueError, match="workers must be 1"):
            NativeTargetWfoRuntimeV2(template, folds, workers=2)
    finally:
        runtime.close()


def test_target_wfo_remains_single_symbol_until_shared_account_portfolio_contract():
    _, _, _, _, _, _, cache, template = _target_fixture(symbols=2)
    folds = (NativeIRFold(1, 0, 0, 4, 4, 8),)
    with pytest.raises(NotImplementedError, match="single-symbol only"):
        NativeTargetWfoRuntimeV2(template, folds)
