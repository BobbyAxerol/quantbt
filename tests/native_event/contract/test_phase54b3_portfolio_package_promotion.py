"""Phase 54B.3 bounded Rust portfolio/package promotion evidence.

The tests intentionally cover only the advertised V2 target-units and
same-bar atomic package contracts.  They do not treat generic allocation,
best-effort packages, cross-venue settlement or partial fills as promoted.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt.backends.native_portfolio_package import (
    run_atomic_package_market,
    run_portfolio_target_market,
)
from quantbt.backends.native_event import NativeEventBackend, NativeEventConfig
from quantbt.core.native_event_capabilities import native_event_semantic_descriptor
from quantbt.core.native_event_promotion import NativePromotionContext, resolve_native_event_promotion
from quantbt.core.schema import AccountConfig, ExecutionConfig, OrderSide, OrderType, TimeInForce
from quantbt.core.orders import OrderCommand
from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native wheel is required for Phase 54B.3 promotion evidence",
)


def _market() -> tuple[pd.DataFrame, dict[str, object]]:
    index = pd.date_range("2025-01-01", periods=5, freq="1h", tz="UTC")
    close = np.array(
        [
            [100.0, 50.0],
            [101.0, 49.0],
            [102.0, 51.0],
            [101.0, 52.0],
            [103.0, 51.0],
        ],
        dtype=np.float64,
    )
    frame = pd.DataFrame({"open": close[:, 0], "high": close[:, 0] + 1.0, "low": close[:, 0] - 1.0, "close": close[:, 0], "volume": 1_000.0}, index=index)
    common = {
        "timestamps_ns": index.asi8,
        "opens": close,
        "highs": close + 1.0,
        "lows": close - 1.0,
        "closes": close,
        "volumes": np.full_like(close, 1_000.0),
        "funding": np.zeros_like(close),
        "funding_mask": np.zeros(len(index), dtype=np.bool_),
        "symbols": ("BTC", "ETH"),
        "contract_sizes": np.ones(2, dtype=np.float64),
        "leverages": np.full(2, 5.0, dtype=np.float64),
        "fee_rates": np.full(2, 0.0002, dtype=np.float64),
        "initial_capital": 10_000.0,
        "maintenance_ratio": 0.005,
        "slippage_rate": 0.0001,
        "use_funding": False,
    }
    return frame, common


def test_local_native_wheel_preserves_the_generated_portfolio_semantic_contract() -> None:
    import _quantbt_native

    assert _quantbt_native.semantic_descriptor()["portfolio"] == native_event_semantic_descriptor()["portfolio"]


def _python_backend() -> NativeEventBackend:
    return NativeEventBackend(
        NativeEventConfig(
            account=AccountConfig(initial_capital=10_000.0, leverage=5.0, maintenance_ratio=0.005),
            execution=ExecutionConfig(slippage_bps=1.0),
            fee_rate=0.0002,
            use_funding=False,
            native_backend="python",
        )
    )


def _python_result(frame: pd.DataFrame, commands: tuple[OrderCommand, ...]):
    return _python_backend().run_order_commands(
        datetime_index=frame.index,
        commands=commands,
        closes={"BTC": frame["close"], "ETH": pd.Series([50.0, 49.0, 51.0, 52.0, 51.0], index=frame.index)},
        highs={"BTC": frame["high"], "ETH": pd.Series([51.0, 50.0, 52.0, 53.0, 52.0], index=frame.index)},
        lows={"BTC": frame["low"], "ETH": pd.Series([49.0, 48.0, 50.0, 51.0, 50.0], index=frame.index)},
        symbols=["BTC", "ETH"],
        report_level="audit",
    )


def _market_command(timestamp, symbol: str, side: OrderSide, qty: float, order_id: str) -> OrderCommand:
    return OrderCommand(
        timestamp=timestamp,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        qty=qty,
        tif=TimeInForce.GTC,
        order_id=order_id,
    )


def test_portfolio_target_market_matches_python_event_oracle_and_has_no_replay() -> None:
    frame, common = _market()
    targets = np.array(
        [[0.0, 0.0], [1.0, -1.0], [-1.0, 1.0], [0.0, 0.0], [0.0, 0.0]],
        dtype=np.float64,
    )
    rust = run_portfolio_target_market(target_units=targets, **common)
    commands = (
        _market_command(frame.index[1], "BTC", OrderSide.BUY, 1.0, "p1-btc"),
        _market_command(frame.index[1], "ETH", OrderSide.SELL, 1.0, "p1-eth"),
        _market_command(frame.index[2], "BTC", OrderSide.SELL, 2.0, "p2-btc"),
        _market_command(frame.index[2], "ETH", OrderSide.BUY, 2.0, "p2-eth"),
        _market_command(frame.index[3], "BTC", OrderSide.BUY, 1.0, "p3-btc"),
        _market_command(frame.index[3], "ETH", OrderSide.SELL, 1.0, "p3-eth"),
    )
    python = _python_result(frame, commands)
    np.testing.assert_allclose(rust.payload["equity"], python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        np.asarray(rust.payload["positions"]).reshape(len(frame), 2),
        python.positions[["Position_BTC", "Position_ETH"]].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(rust.payload["fees"], python.fees.to_numpy(), rtol=0.0, atol=1e-12)
    assert rust.payload["fill_count"] == 6
    assert rust.payload["native_execution_workload"] == "portfolio_target_market_v1"
    assert rust.payload["portfolio_target_decision_count"] == 3
    assert rust.payload["python_callbacks"] == 0
    audit = rust.to_audit_result()
    assert audit.external_id_values
    assert set(audit.external_id_values).issuperset(set(audit.fill_order_id.tolist()))
    report = audit.to_backtest_result(
        datetime_index=frame.index,
        closes=pd.DataFrame(common["closes"], index=frame.index, columns=["BTC", "ETH"]),
        symbols=("BTC", "ETH"),
        initial_capital=10_000.0,
        leverage=5.0,
    )
    np.testing.assert_allclose(report.equity.to_numpy(), rust.payload["equity"], rtol=0.0, atol=1e-12)
    assert len(report.fills) == rust.payload["fill_count"]
    assert report.metadata["fills_report"]["order_id"].notna().all()

    score = run_portfolio_target_market(target_units=targets, report_level="score", **common)
    compact = run_portfolio_target_market(target_units=targets, report_level="compact", **common)
    for payload in (score.payload, compact.payload):
        assert payload["final_equity"] == pytest.approx(rust.payload["final_equity"])
        assert payload["total_fee"] == pytest.approx(rust.payload["total_fee"])
        assert payload["total_funding"] == pytest.approx(rust.payload["total_funding"])
        assert payload["fill_count"] == rust.payload["fill_count"]
    assert "equity" not in score.payload
    assert "fill_bar" not in compact.payload
    with pytest.raises(ValueError, match="report_level='audit'"):
        score.to_audit_result()


def test_portfolio_target_stale_and_post_cost_rejection_leave_no_partial_target() -> None:
    _, common = _market()
    stale = np.zeros((5, 2), dtype=np.bool_)
    stale[1, 1] = True
    targets = np.array([[0.0, 0.0], [1.0, -1.0], [1.0, -1.0], [0.0, 0.0], [0.0, 0.0]])
    result = run_portfolio_target_market(target_units=targets, stale=stale, **common)
    positions = np.asarray(result.payload["positions"]).reshape(5, 2)
    np.testing.assert_allclose(positions[1], [0.0, 0.0], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(positions[2], [1.0, -1.0], rtol=0.0, atol=1e-12)
    assert result.payload["portfolio_target_rejected_decision_count"] == 1

    rejected = run_portfolio_target_market(
        target_units=np.array([[0.0, 0.0], [100.0, -100.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]),
        **{**common, "initial_capital": 10.0, "leverages": np.ones(2)},
    )
    assert rejected.payload["fill_count"] == 0
    np.testing.assert_allclose(rejected.payload["final_positions"], [0.0, 0.0], rtol=0.0, atol=0.0)
    assert np.any(np.asarray(rejected.payload["portfolio_target_rejection_code"]) == 6)


def test_portfolio_target_invalid_value_fails_before_any_execution_state_exists() -> None:
    _, common = _market()
    targets = np.array(
        [[0.0, 0.0], [1.0, np.nan], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
        dtype=np.float64,
    )
    with pytest.raises(ValueError, match="portfolio target tape values must be finite"):
        run_portfolio_target_market(target_units=targets, **common)


def test_atomic_package_matches_python_market_tape_and_rolls_back_stale_leg() -> None:
    frame, common = _market()
    kwargs = dict(
        command_bar=1,
        package_id=44,
        order_ids=np.array([401, 402], dtype=np.int64),
        symbol_ids=np.array([0, 1], dtype=np.uint32),
        signed_qty=np.array([1.0, -1.0]),
        source_age_ns=np.zeros(2, dtype=np.int64),
        venue_codes=np.array([1, 1], dtype=np.uint16),
        venue_sequence=np.array([0, 1], dtype=np.uint32),
    )
    rust = run_atomic_package_market(**kwargs, **common)
    python = _python_result(
        frame,
        (
            _market_command(frame.index[1], "BTC", OrderSide.BUY, 1.0, "pkg-btc"),
            _market_command(frame.index[1], "ETH", OrderSide.SELL, 1.0, "pkg-eth"),
        ),
    )
    np.testing.assert_allclose(rust.payload["equity"], python.equity.to_numpy(), rtol=0.0, atol=1e-12)
    assert rust.payload["package_accepted"].tolist() == [True, True]
    assert rust.payload["package_reserved_margin"] == pytest.approx(rust.payload["package_released_margin"])

    score = run_atomic_package_market(**kwargs, report_level="score", **common)
    assert score.payload["final_equity"] == pytest.approx(rust.payload["final_equity"])
    assert score.payload["total_fee"] == pytest.approx(rust.payload["total_fee"])
    assert "equity" not in score.payload

    stale = run_atomic_package_market(
        **{**kwargs, "source_age_ns": np.array([0, 10], dtype=np.int64), "max_staleness_ns": 0},
        **common,
    )
    assert stale.payload["fill_count"] == 0
    assert stale.payload["package_accepted"].tolist() == [False, False]
    assert stale.payload["package_reserved_margin"] == stale.payload["package_released_margin"] == 0.0

    post_cost = run_atomic_package_market(
        **kwargs,
        **{**common, "initial_capital": 10.0, "leverages": np.ones(2, dtype=np.float64)},
    )
    assert post_cost.payload["fill_count"] == 0
    assert post_cost.payload["package_accepted"].tolist() == [False, False]
    assert np.all(np.asarray(post_cost.payload["package_rejection_code"]) == 5)


def test_prepared_requests_have_content_signatures_and_promoted_rows_fail_closed() -> None:
    _, common = _market()
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=4_000_000, max_entries=8))
    target = np.zeros((5, 2), dtype=np.float64)
    first = run_portfolio_target_market(target_units=target, cache=cache, **common)
    direct = run_portfolio_target_market(target_units=target, **common)
    np.testing.assert_allclose(first.payload["equity"], direct.payload["equity"], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first.payload["positions"], direct.payload["positions"], rtol=0.0, atol=1e-12)
    target[1, 0] = 1.0
    second = run_portfolio_target_market(target_units=target, cache=cache, **common)
    assert first.request_signature != second.request_signature
    assert cache.diagnostics["cache_hit"] >= 1

    package_kwargs = dict(
        command_bar=1,
        package_id=54,
        order_ids=np.array([541, 542], dtype=np.int64),
        symbol_ids=np.array([0, 1], dtype=np.uint32),
        signed_qty=np.array([1.0, -1.0]),
        source_age_ns=np.zeros(2, dtype=np.int64),
        venue_codes=np.ones(2, dtype=np.uint16),
        venue_sequence=np.array([0, 1], dtype=np.uint32),
    )
    prepared_package = run_atomic_package_market(**package_kwargs, cache=cache, **common)
    direct_package = run_atomic_package_market(**package_kwargs, **common)
    np.testing.assert_allclose(
        prepared_package.payload["equity"], direct_package.payload["equity"], rtol=0.0, atol=1e-12
    )
    np.testing.assert_allclose(
        prepared_package.payload["positions"], direct_package.payload["positions"], rtol=0.0, atol=1e-12
    )

    context = NativePromotionContext(
        requested_backend="auto",
        backend_policy=None,
        workload_id="portfolio_target_market_v1",
        execution_contract_id="event_lifecycle_v2_next_bar_close",
        strategy_mode="portfolio_target_market",
        profile="audit",
        account_model="linear_quote_settled_gross_cross",
        bars=2_000,
        symbol_count=2,
        native_available=True,
        native_compatible=True,
        native_executable=True,
        native_capabilities=("native_event_v2_full_contract", "native_portfolio_target_market_v1"),
        platform_tags=("cpython-3.12+", "linux-x86_64-local"),
    )
    auto_decision = resolve_native_event_promotion(context, environment={})
    assert auto_decision.resolved_backend == "python"
    assert auto_decision.reason == "auto_python_release_policy"
    explicit_decision = resolve_native_event_promotion(
        NativePromotionContext(
            requested_backend="rust",
            backend_policy=None,
            workload_id="portfolio_target_market_v1",
            execution_contract_id="event_lifecycle_v2_next_bar_close",
            strategy_mode="portfolio_target_market",
            profile="audit",
            account_model="linear_quote_settled_gross_cross",
            bars=2_000,
            symbol_count=2,
            required_capabilities=(
                "native_event_v2_full_contract",
                "native_portfolio_target_market_v1",
            ),
            native_available=True,
            native_compatible=True,
            native_executable=True,
            native_capabilities=("native_event_v2_full_contract", "native_portfolio_target_market_v1"),
            platform_tags=("cpython-3.12+", "linux-x86_64-local"),
        ),
        environment={},
    )
    assert explicit_decision.resolved_backend == "rust"
    unsupported = NativePromotionContext(
        requested_backend="auto",
        backend_policy=None,
        workload_id="package_transaction_preflight_v1",
        execution_contract_id="event_lifecycle_v3_next_open",
        strategy_mode="package_transaction_preflight",
        profile="audit",
        account_model="linear_quote_settled_gross_cross",
        bars=10_000,
        symbol_count=2,
        native_available=True,
        native_compatible=True,
        native_executable=True,
        native_capabilities=("native_event_v2_full_contract", "native_package_atomic_market_v1"),
        platform_tags=("cpython-3.12+", "linux-x86_64-local"),
    )
    decision = resolve_native_event_promotion(unsupported, environment={})
    assert decision.resolved_backend == "python"
    assert decision.reason == "auto_python_release_policy"
