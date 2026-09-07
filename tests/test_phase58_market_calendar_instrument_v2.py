from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    CalendarPolicyV2,
    ExecutionConfig,
    InstrumentSpec,
    MissingObservationPolicyV1,
    OrderCommand,
    OrderSide,
    OrderType,
    PreparedMarketCacheV2,
    PricePurposeV2,
    QuantBTEndpoint,
    QuantityPurposeV2,
)
from quantbt.api.event_driven import execute_native_event_lifecycle
from quantbt.backends.native_portfolio_package import (
    run_atomic_package_market,
    run_atomic_package_market_v2,
    run_portfolio_target_market,
    run_portfolio_target_market_v2,
)
from quantbt.core.market_calendar_v2 import prepare_market_handle_v2
from quantbt.walkforward import WalkForwardConfig, WalkForwardEngine, _align_data_to_datetime_index
from reference.python.calendar_oracle import build_calendar_plan
from reference.python.instrument_oracle import quantize_price as oracle_price
from reference.python.instrument_oracle import quantize_quantity as oracle_quantity


ROOT = Path(__file__).resolve().parents[1]


def _index(*hours: int) -> pd.DatetimeIndex:
    return pd.to_datetime([f"2024-01-01 {hour:02d}:00:00" for hour in hours], utc=True)


def _frame(index: pd.DatetimeIndex, base: float) -> pd.DataFrame:
    close = np.arange(len(index), dtype=float) + base
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.arange(len(index), dtype=float) + 10.0,
            "funding_rate": np.full(len(index), 0.0001),
            "funding_event_mask": [False] * max(len(index) - 1, 0) + [True],
        },
        index=index,
    )


def _two_frames() -> dict[str, pd.DataFrame]:
    return {
        "ETH": _frame(_index(0, 2, 3), 200.0),
        "BTC": _frame(_index(0, 1, 3), 100.0),
    }


def _run_static_lifecycle(
    frame: pd.DataFrame,
    *,
    market=None,
    registry=None,
    contract_size: float = 1.0,
    leverage: float = 3.0,
    fee_rate: float = 0.0005,
    native_backend: str = "python",
):
    return execute_native_event_lifecycle(
        datetime_index=frame.index,
        commands=(
            OrderCommand(
                timestamp=frame.index[0],
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=1.0,
                order_id="entry",
            ),
        ),
        closes={"BTC": frame.close},
        highs={"BTC": frame.high},
        lows={"BTC": frame.low},
        opens={"BTC": frame.open},
        volumes={"BTC": frame.volume},
        symbols=("BTC",),
        account=AccountConfig(initial_capital=10_000.0, leverage=3.0),
        execution=ExecutionConfig(),
        native_backend=native_backend,
        backend_policy="certified_only",
        execution_contract="event_lifecycle_v3_next_open",
        report_level="audit",
        audit_sink="memory",
        audit_sink_path=None,
        funding_rate={"BTC": frame.funding_rate},
        use_funding=True,
        contract_size=contract_size,
        leverage=leverage,
        fee_rate=fee_rate,
        instruments=None,
        qty_step=None,
        lot_size=None,
        slot_size=None,
        min_qty=None,
        min_notional=None,
        market_handle=market,
        instrument_registry=registry,
    )


def test_phase58_exact_rejects_equal_length_timestamp_relabel_with_first_divergence() -> None:
    frames = _two_frames()
    with pytest.raises(ValueError, match=r"Exact mismatch.*row 1") as error:
        QuantBTEndpoint.prepare_market(frames, calendar_policy="exact")
    assert "2024-01-01 01:00:00+00:00" in str(error.value)


def test_phase58_wfo_exact_rejects_equal_length_shift_before_strategy_runs() -> None:
    calls = []

    def strategy(data, params, train_index, test_index, fold):
        calls.append(fold.fold_id)
        return pd.Series(0.0, index=test_index)

    engine = WalkForwardEngine(
        strategy,
        WalkForwardConfig(split_mode="2024-01-01 02:00:00+00:00", split_frequency="single", calendar_contract="exact_v2"),
    )
    with pytest.raises(ValueError, match=r"CalendarPlanV2 Exact mismatch.*row 1"):
        engine.run(_two_frames())
    assert calls == []


def test_phase58_explicit_legacy_wfo_contract_preserves_historical_row_count_adapter() -> None:
    frames = _two_frames()
    canonical = _index(0, 1, 3)
    aligned = _align_data_to_datetime_index(frames, canonical, calendar_contract="legacy_v1")
    assert aligned["ETH"].index.equals(canonical)


@pytest.mark.parametrize("policy", ["intersection", "union", "primary_clock"])
def test_phase58_calendar_policies_match_independent_oracle(policy: str) -> None:
    frames = _two_frames()
    primary = "BTC" if policy == "primary_clock" else None
    handle = QuantBTEndpoint.prepare_market(
        frames,
        calendar_policy=policy,
        primary_symbol=primary,
        missing_policy="mark_to_last_no_execution",
    )
    source = {symbol: tuple(frame.index.view("int64")) for symbol, frame in frames.items()}
    canonical, maps = build_calendar_plan(
        source,
        policy=policy,
        primary_symbol=primary,
        missing_policy="mark_to_last_no_execution",
    )
    assert tuple(handle.calendar.timestamps_ns) == canonical
    for symbol, oracle in maps.items():
        actual = handle.calendar.map_for(symbol)
        assert tuple(None if item < 0 else int(item) for item in actual.canonical_to_local) == oracle.canonical_to_local
        assert tuple(None if item < 0 else int(item) for item in actual.local_to_canonical) == oracle.local_to_canonical
        assert tuple(actual.observed) == oracle.observed
        assert tuple(actual.stale) == oracle.stale
        assert tuple(actual.tradable) == oracle.tradable


def test_phase58_union_never_fabricates_ohlc_and_marking_is_separate() -> None:
    handle = QuantBTEndpoint.prepare_market(
        _two_frames(),
        calendar_policy=CalendarPolicyV2.UNION,
        missing_policy=MissingObservationPolicyV1.MARK_TO_LAST_NO_EXECUTION,
    )
    eth = handle.symbols.index("ETH")
    missing_row = 1
    assert not handle.observed[missing_row, eth]
    assert handle.stale[missing_row, eth]
    assert not handle.tradable[missing_row, eth]
    assert np.isnan(handle.opens[missing_row, eth])
    assert np.isnan(handle.closes[missing_row, eth])
    assert np.isfinite(handle.mark_closes[missing_row, eth])
    with pytest.raises(NotImplementedError, match="every symbol observation"):
        handle.execution_view()


def test_phase58_reorder_future_cutoff_cache_and_close_are_deterministic() -> None:
    frames = _two_frames()
    cache = PreparedMarketCacheV2(max_entries=2, max_bytes=10_000_000)
    first = QuantBTEndpoint.prepare_market(frames, calendar_policy="intersection", cache=cache)
    reversed_frames = {"BTC": frames["BTC"], "ETH": frames["ETH"]}
    second = QuantBTEndpoint.prepare_market(reversed_frames, calendar_policy="intersection", cache=cache)
    assert first is second
    assert cache.stats["hits"] == 1
    future = {symbol: pd.concat([frame, _frame(_index(5), float(frame.close.iloc[-1] + 1.0))]) for symbol, frame in frames.items()}
    cut_a = QuantBTEndpoint.prepare_market(frames, calendar_policy="intersection", cutoff_timestamp="2024-01-01 03:00:00+00:00")
    cut_b = QuantBTEndpoint.prepare_market(future, calendar_policy="intersection", cutoff_timestamp="2024-01-01 03:00:00+00:00")
    assert cut_a.fingerprint == cut_b.fingerprint
    view = cut_a.execution_view()
    assert np.shares_memory(view.closes, cut_a.closes)
    assert np.shares_memory(view.funding_event_mask, cut_a.shared_funding_event_mask)
    cut_a.close()
    with pytest.raises(RuntimeError, match="closed"):
        cut_a.execution_view()


def test_phase58_market_fingerprint_covers_volume_funding_and_event_clock() -> None:
    frame = _frame(_index(0, 1, 2), 100.0)
    baseline = QuantBTEndpoint.prepare_market({"BTC": frame})
    changed_volume = frame.copy()
    changed_volume.loc[changed_volume.index[1], "volume"] += 1.0
    changed_funding = frame.copy()
    changed_funding.loc[changed_funding.index[1], "funding_rate"] += 0.0001
    changed_event = frame.copy()
    changed_event.loc[changed_event.index[0], "funding_event_mask"] = True
    assert QuantBTEndpoint.prepare_market({"BTC": changed_volume}).fingerprint != baseline.fingerprint
    assert QuantBTEndpoint.prepare_market({"BTC": changed_funding}).fingerprint != baseline.fingerprint
    assert QuantBTEndpoint.prepare_market({"BTC": changed_event}).fingerprint != baseline.fingerprint


def test_phase58_duplicate_unsorted_ohlc_and_invalid_volume_fail_at_preparation() -> None:
    duplicate = _frame(_index(0, 1), 100.0)
    duplicate.index = pd.DatetimeIndex([duplicate.index[0], duplicate.index[0]])
    with pytest.raises(ValueError, match="duplicate"):
        prepare_market_handle_v2({"BTC": duplicate})
    invalid = _frame(_index(0, 1), 100.0)
    invalid.loc[invalid.index[0], "volume"] = -1.0
    with pytest.raises(ValueError, match="invalid volume"):
        prepare_market_handle_v2({"BTC": invalid})


def test_phase58_instrument_registry_quantization_matches_independent_oracle_and_minima() -> None:
    registry = QuantBTEndpoint.prepare_instruments(
        specs={
            "BTC": InstrumentSpec(
                symbol="BTC",
                tick_size=0.1,
                lot_size=0.25,
                min_qty=0.25,
                min_notional=5.0,
                contract_size=2.0,
                metadata={"max_qty": 10.0, "settlement_currency": "USDT", "venue": "BINANCE"},
            )
        },
        leverage=5.0,
        fee_rate=0.0005,
    )
    rule = registry.rule_for("BTC")
    assert rule.quantize_price(10.04, PricePurposeV2.LIMIT_BUY) == oracle_price(10.04, 0.1, side="buy", purpose="limit")
    assert rule.quantize_price(10.04, PricePurposeV2.STOP_SELL) == oracle_price(10.04, 0.1, side="sell", purpose="stop")
    assert rule.quantize_quantity(0.41, QuantityPurposeV2.RISK_INCREASING) == oracle_quantity(0.41, 0.25, purpose="risk_increasing")
    assert rule.quantize_quantity(3.0, QuantityPurposeV2.RISK_REDUCING, current_position=-0.31) == oracle_quantity(
        3.0, 0.25, purpose="risk_reducing", current_position=-0.31
    )
    assert rule.validate(10.0, 0.25).value == "accepted"
    assert rule.validate(1.0, 0.25).value == "min_notional"
    assert rule.contract_multiplier == 2.0
    assert registry.prepared_table().symbols == ("BTC",)


def test_phase58_v2_prepared_plan_rejects_symbol_mismatch_and_binds_matching_handles() -> None:
    market = QuantBTEndpoint.prepare_market({"BTC": _frame(_index(0, 1, 2), 100.0)})
    matching = QuantBTEndpoint.prepare_instruments(symbols=["BTC"], contract_size=1.0)
    plan = QuantBTEndpoint.prepare_execution_plan(market=market, instruments=matching)
    assert plan.metadata()["market_fingerprint"] == market.fingerprint
    mismatch = QuantBTEndpoint.prepare_instruments(symbols=["ETH"], contract_size=1.0)
    with pytest.raises(ValueError, match="symbols differ"):
        QuantBTEndpoint.prepare_execution_plan(market=market, instruments=mismatch)


def test_phase58_static_event_v2_adapter_uses_prepared_market_and_registry(monkeypatch) -> None:
    frame = _frame(_index(0, 1, 2, 3), 100.0)
    market = QuantBTEndpoint.prepare_market({"BTC": frame})
    registry = QuantBTEndpoint.prepare_instruments(symbols=["BTC"], contract_size=1.0, leverage=3.0, fee_rate=0.0005)
    outcome = execute_native_event_lifecycle(
        datetime_index=frame.index,
        commands=(
            OrderCommand(timestamp=frame.index[0], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, order_id="entry"),
        ),
        closes={"BTC": frame.close},
        highs={"BTC": frame.high},
        lows={"BTC": frame.low},
        opens={"BTC": frame.open},
        volumes={"BTC": frame.volume},
        symbols=("BTC",),
        account=AccountConfig(initial_capital=10_000.0, leverage=3.0),
        execution=ExecutionConfig(),
        native_backend="python",
        backend_policy="certified_only",
        execution_contract="event_lifecycle_v3_next_open",
        report_level="minimal",
        audit_sink="none",
        audit_sink_path=None,
        funding_rate={"BTC": frame.funding_rate},
        use_funding=True,
        contract_size=1.0,
        leverage=3.0,
        fee_rate=0.0005,
        instruments=None,
        qty_step=None,
        lot_size=None,
        slot_size=None,
        min_qty=None,
        min_notional=None,
        market_handle=market,
        instrument_registry=registry,
        calendar_contract="exact_v2",
    )
    assert outcome.result.metadata["calendar_contract"] == "exact_v2"
    assert outcome.result.metadata["prepared_market_v2"]["fingerprint"] == market.fingerprint
    assert outcome.result.metadata["instrument_registry_v2"]["fingerprint"] == registry.fingerprint

    endpoint = QuantBTEndpoint.event_driven(
        input_mode="orders",
        profile="research",
        backend="python",
        initial_capital=10_000.0,
        leverage=3.0,
        fee_rate=0.0005,
        execution_contract="event_lifecycle_v3_next_open",
    )
    # A prepared V2 execution must not fall back to facade normalization or
    # reconstruct open/volume maps from pandas before entering the kernel.
    def unexpected_legacy_preparation(*args, **kwargs):
        raise AssertionError("prepared V2 route invoked a legacy market preparation helper")

    monkeypatch.setattr("quantbt.endpoint._normalize_single_data", unexpected_legacy_preparation)
    monkeypatch.setattr("quantbt.engines._market_open_volume", unexpected_legacy_preparation)
    public = endpoint.backtest(
        data=None,
        order_commands=(
            OrderCommand(timestamp=frame.index[0], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, order_id="public-entry"),
        ),
        symbols=["BTC"],
        prepared_market=market,
        prepared_instruments=registry,
        calendar_contract="exact_v2",
    )
    assert public.metadata["calendar_contract"] == "exact_v2"
    assert public.metadata["prepared_market_v2"]["fingerprint"] == market.fingerprint


def test_phase58_prepared_static_route_uses_registry_and_matches_legacy_trace() -> None:
    frame = _frame(_index(0, 1, 2, 3), 100.0)
    legacy = _run_static_lifecycle(frame, contract_size=2.0, leverage=5.0, fee_rate=0.001)
    market = QuantBTEndpoint.prepare_market({"BTC": frame})
    registry = QuantBTEndpoint.prepare_instruments(
        symbols=["BTC"],
        contract_size=2.0,
        leverage=5.0,
        fee_rate=0.001,
    )
    # Deliberately contradictory legacy values prove the certified V2 route
    # consumes the registry arrays rather than merely recording them.
    prepared = _run_static_lifecycle(
        frame,
        market=market,
        registry=registry,
        contract_size=1.0,
        leverage=1.0,
        fee_rate=0.0,
    )
    pd.testing.assert_series_equal(legacy.result.equity, prepared.result.equity)
    pd.testing.assert_frame_equal(legacy.result.positions, prepared.result.positions)
    pd.testing.assert_series_equal(legacy.result.fees, prepared.result.fees)
    pd.testing.assert_series_equal(legacy.result.funding, prepared.result.funding)
    pd.testing.assert_frame_equal(
        legacy.result.metadata["command_outcome_report_v1"],
        prepared.result.metadata["command_outcome_report_v1"],
    )
    pd.testing.assert_frame_equal(
        legacy.result.metadata["lifecycle_event_report_v1"],
        prepared.result.metadata["lifecycle_event_report_v1"],
    )
    resolved = prepared.result.metadata["instrument_constraints_resolved"]["BTC"]
    assert resolved["contract_size"] == 2.0
    assert resolved["leverage"] == 5.0
    assert resolved["fee_rate"] == 0.001
    assert prepared.result.metadata["calendar_contract_requested"] == "legacy_v1"
    assert prepared.result.metadata["calendar_contract_resolved"] == "exact_v2"


def test_phase58_prepared_static_registry_arrays_match_rust_when_available() -> None:
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension

    if not probe_native_event_rust_extension().available:
        pytest.skip("optional quantbt-native extension is not installed")
    frame = _frame(_index(0, 1, 2, 3), 100.0)
    market = QuantBTEndpoint.prepare_market({"BTC": frame})
    registry = QuantBTEndpoint.prepare_instruments(
        symbols=["BTC"],
        contract_size=2.0,
        leverage=5.0,
        fee_rate=0.001,
    )
    python = _run_static_lifecycle(
        frame,
        market=market,
        registry=registry,
        contract_size=1.0,
        leverage=1.0,
        fee_rate=0.0,
        native_backend="python",
    )
    rust = _run_static_lifecycle(
        frame,
        market=market,
        registry=registry,
        contract_size=1.0,
        leverage=1.0,
        fee_rate=0.0,
        native_backend="rust",
    )
    pd.testing.assert_series_equal(python.result.equity, rust.result.equity)
    pd.testing.assert_frame_equal(python.result.positions, rust.result.positions)
    pd.testing.assert_series_equal(python.result.fees, rust.result.fees)
    pd.testing.assert_series_equal(python.result.funding, rust.result.funding)


def test_phase58_v2_portfolio_and_package_adapters_are_parity_preserving() -> None:
    index = _index(0, 1, 2, 3)
    frames = {"BTC": _frame(index, 100.0), "ETH": _frame(index, 50.0)}
    market = QuantBTEndpoint.prepare_market(frames, calendar_policy="exact")
    registry = QuantBTEndpoint.prepare_instruments(
        symbols=["BTC", "ETH"], contract_size=1.0, leverage=5.0, fee_rate=0.0002
    )
    view = market.execution_view()
    arrays = registry.arrays()
    common = dict(
        timestamps_ns=view.timestamps_ns,
        opens=view.opens,
        highs=view.highs,
        lows=view.lows,
        closes=view.closes,
        volumes=view.volumes,
        funding=view.funding_rates,
        funding_mask=view.funding_event_mask,
        symbols=view.symbols,
        contract_sizes=arrays["contract_size"],
        leverages=arrays["leverage"],
        fee_rates=arrays["fee_rate"],
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
    )
    targets = np.array([[0.0, 0.0], [1.0, -1.0], [1.0, -1.0], [0.0, 0.0]])
    raw = run_portfolio_target_market(target_units=targets, **common)
    adapted = run_portfolio_target_market_v2(
        market=market,
        instruments=registry,
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
        target_units=targets,
    )
    np.testing.assert_allclose(raw.payload["equity"], adapted.payload["equity"], rtol=0.0, atol=1e-12)
    package = dict(
        command_bar=1,
        package_id=58,
        order_ids=np.array([581, 582], dtype=np.int64),
        symbol_ids=np.array([0, 1], dtype=np.uint32),
        signed_qty=np.array([1.0, -1.0]),
        source_age_ns=np.zeros(2, dtype=np.int64),
        venue_codes=np.ones(2, dtype=np.uint16),
        venue_sequence=np.array([0, 1], dtype=np.uint32),
    )
    raw_package = run_atomic_package_market(**package, **common)
    adapted_package = run_atomic_package_market_v2(
        market=market,
        instruments=registry,
        initial_capital=10_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
        **package,
    )
    np.testing.assert_allclose(raw_package.payload["equity"], adapted_package.payload["equity"], rtol=0.0, atol=1e-12)
