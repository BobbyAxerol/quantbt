"""Phase 68 bounded Rust package authority and Python-oracle conformance."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("_quantbt_native")

from quantbt.backends.native_portfolio_package import run_bounded_package_market
from quantbt.backends.native_package_arbitrage import compile_bounded_linear_arbitrage_package_tape
from quantbt.core.arbitrage import (
    ArbExecutionPolicy,
    ArbitrageLeg,
    BasisArbitrageSpec,
    ContractType,
    CrossExchangeArbSpec,
    HedgePolicy,
    HedgePolicyKind,
    PackageExecutionKind,
    SizingPolicy,
    SizingPolicyKind,
    TriangularArbSpec,
    build_arbitrage_order_plan,
)
from quantbt.core.package_execution_v2 import (
    LegQuantitySourceV1,
    PackageExecutionPolicyV2,
    PackageIntentV2,
    PackageLegIntentV2,
    ResidualRiskPolicyV1,
    execute_package_intent_v2_reference,
)
from quantbt.preparation.native_execution import NativeExecutionPreparationCache


def _market(symbol_count: int = 2, bars: int = 9) -> dict[str, object]:
    timestamps = np.arange(bars, dtype=np.int64) * 3_600_000_000_000
    base = np.arange(symbol_count, dtype=np.float64) * 25.0 + 100.0
    closes = base[None, :] + np.arange(bars, dtype=np.float64)[:, None]
    return {
        "timestamps_ns": timestamps,
        "opens": closes,
        "highs": closes * 1.01,
        "lows": closes * 0.99,
        "closes": closes,
        "volumes": np.full_like(closes, 10_000.0),
        "funding": np.zeros_like(closes),
        "funding_mask": np.zeros(bars, dtype=np.bool_),
        "symbols": tuple(f"S{index}" for index in range(symbol_count)),
        "contract_sizes": np.ones(symbol_count, dtype=np.float64),
        "leverages": np.full(symbol_count, 3.0, dtype=np.float64),
        "fee_rates": np.full(symbol_count, 0.0005, dtype=np.float64),
        "initial_capital": 20_000.0,
        "maintenance_ratio": 0.005,
        "slippage_rate": 0.0002,
        "use_funding": False,
    }


def _intent(
    *,
    policy: PackageExecutionPolicyV2,
    residual: ResidualRiskPolicyV1 = ResidualRiskPolicyV1.RECORD,
    leg_count: int = 2,
    primary_fraction: float = 1.0,
    secondary_min_notional: float = 0.0,
) -> PackageIntentV2:
    legs: list[PackageLegIntentV2] = []
    for index in range(leg_count):
        if index == 0:
            legs.append(
                PackageLegIntentV2(
                    order_id=10,
                    symbol_id=0,
                    signed_qty=2.0,
                    quantity_source=LegQuantitySourceV1.FIXED,
                    source_leg=-1,
                    quantity_ratio=1.0,
                    fill_fraction=primary_fraction,
                    qty_step=0.1,
                    min_qty=0.0,
                    min_notional=0.0,
                    source_age_ns=0,
                    venue_code=1,
                    venue_sequence=0,
                )
            )
            continue
        legs.append(
            PackageLegIntentV2(
                order_id=10 + index,
                symbol_id=index,
                signed_qty=-1.0,
                quantity_source=(
                    LegQuantitySourceV1.PROPORTION_OF_ACTUAL_FILL
                    if policy is PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY
                    else LegQuantitySourceV1.FIXED
                ),
                source_leg=0 if policy is PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY else -1,
                quantity_ratio=-0.5 if policy is PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY else 1.0,
                fill_fraction=1.0,
                qty_step=0.1,
                min_qty=0.0,
                min_notional=secondary_min_notional if index == 1 else 0.0,
                source_age_ns=0,
                venue_code=1,
                venue_sequence=index,
            )
        )
    return PackageIntentV2(
        package_id=7,
        command_bar=1,
        execution_policy=policy,
        residual_policy=residual,
        legs=tuple(legs),
        max_staleness_ns=0,
    )


def _arrays(intents: list[PackageIntentV2]) -> dict[str, np.ndarray]:
    command_bars = []
    package_ids = []
    policies = []
    residual_policies = []
    max_staleness = []
    offsets = [0]
    order_ids = []
    symbol_ids = []
    signed_qty = []
    quantity_sources = []
    source_legs = []
    quantity_ratios = []
    fill_fractions = []
    qty_step = []
    min_qty = []
    min_notional = []
    source_age = []
    venue_codes = []
    venue_sequence = []
    for intent in intents:
        command_bars.append(intent.command_bar)
        package_ids.append(intent.package_id)
        policies.append(intent.execution_policy.value)
        residual_policies.append(intent.residual_policy.value)
        max_staleness.append(intent.max_staleness_ns)
        for leg in intent.legs:
            order_ids.append(leg.order_id)
            symbol_ids.append(leg.symbol_id)
            signed_qty.append(leg.signed_qty)
            quantity_sources.append(leg.quantity_source.value)
            source_legs.append(leg.source_leg)
            quantity_ratios.append(leg.quantity_ratio)
            fill_fractions.append(leg.fill_fraction)
            qty_step.append(leg.qty_step)
            min_qty.append(leg.min_qty)
            min_notional.append(leg.min_notional)
            source_age.append(leg.source_age_ns)
            venue_codes.append(leg.venue_code)
            venue_sequence.append(leg.venue_sequence)
        offsets.append(len(order_ids))
    return {
        "command_bars": np.asarray(command_bars, dtype=np.uint64),
        "package_ids": np.asarray(package_ids, dtype=np.uint64),
        "package_leg_offsets": np.asarray(offsets, dtype=np.uint64),
        "execution_policies": np.asarray(policies),
        "residual_policies": np.asarray(residual_policies),
        "max_staleness_ns": np.asarray(max_staleness, dtype=np.int64),
        "order_ids": np.asarray(order_ids, dtype=np.int64),
        "symbol_ids": np.asarray(symbol_ids, dtype=np.uint32),
        "signed_qty": np.asarray(signed_qty, dtype=np.float64),
        "quantity_sources": np.asarray(quantity_sources),
        "source_legs": np.asarray(source_legs, dtype=np.int64),
        "quantity_ratios": np.asarray(quantity_ratios, dtype=np.float64),
        "fill_fractions": np.asarray(fill_fractions, dtype=np.float64),
        "qty_step": np.asarray(qty_step, dtype=np.float64),
        "min_qty": np.asarray(min_qty, dtype=np.float64),
        "min_notional": np.asarray(min_notional, dtype=np.float64),
        "source_age_ns": np.asarray(source_age, dtype=np.int64),
        "venue_codes": np.asarray(venue_codes, dtype=np.uint16),
        "venue_sequence": np.asarray(venue_sequence, dtype=np.uint32),
    }


def _scenario_arrays(scenarios: list[list[PackageIntentV2]]) -> dict[str, np.ndarray]:
    flat = [intent for scenario in scenarios for intent in scenario]
    arrays = _arrays(flat)
    offsets = [0]
    for scenario in scenarios:
        offsets.append(offsets[-1] + len(scenario))
    arrays["scenario_package_offsets"] = np.asarray(offsets, dtype=np.uint64)
    return arrays


def _prepared_template(
    cache: NativeExecutionPreparationCache,
    market: dict[str, object],
):
    prepared_market = cache.prepare_market(
        timestamps_ns=market["timestamps_ns"],
        opens=market["opens"],
        highs=market["highs"],
        lows=market["lows"],
        closes=market["closes"],
        volumes=market["volumes"],
        funding=market["funding"],
        funding_mask=market["funding_mask"],
        symbols=market["symbols"],
    )
    return cache.prepare_template(
        prepared_market,
        contract_sizes=market["contract_sizes"],
        leverages=market["leverages"],
        fee_rates=market["fee_rates"],
        initial_capital=float(market["initial_capital"]),
        maintenance_ratio=float(market["maintenance_ratio"]),
        slippage_rate=float(market["slippage_rate"]),
        use_funding=bool(market["use_funding"]),
    )


def _run(
    intents: list[PackageIntentV2],
    *,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
    market: dict[str, object] | None = None,
):
    market = (
        _market(max(leg.symbol_id for intent in intents for leg in intent.legs) + 1)
        if market is None
        else market
    )
    return run_bounded_package_market(
        **market,
        **_arrays(intents),
        report_level=report_level,
        cache=cache,
    )


def _reference(intent: PackageIntentV2, market: dict[str, object]):
    closes = np.asarray(market["closes"], dtype=float)
    return execute_package_intent_v2_reference(
        intent,
        previous_units=np.zeros(closes.shape[1]),
        close_prices=closes[intent.command_bar],
        contract_sizes=np.asarray(market["contract_sizes"], dtype=float),
        leverages=np.asarray(market["leverages"], dtype=float),
        fee_rates=np.asarray(market["fee_rates"], dtype=float),
        slippage_rate=float(market["slippage_rate"]),
        equity=float(market["initial_capital"]),
    )


def test_hedge_after_primary_uses_actual_fill_and_matches_reference() -> None:
    intent = _intent(
        policy=PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY,
        primary_fraction=0.5,
    )
    market = _market()
    reference = _reference(intent, market)
    rust = _run([intent])
    payload = rust.payload

    np.testing.assert_allclose(
        payload["package_v2_leg_requested_qty"],
        [item.requested_signed_qty for item in reference.legs],
    )
    np.testing.assert_allclose(
        payload["package_v2_leg_filled_qty"],
        [item.filled_signed_qty for item in reference.legs],
    )
    np.testing.assert_allclose(payload["final_positions"], [1.0, -0.5])
    assert int(payload["package_v2_final_state_code"][0]) == 11
    assert payload["package_v2_residual_gross_notional_total"] == pytest.approx(
        reference.residual_gross_notional
    )
    assert payload["package_v2_outstanding_residual_gross_notional_total"] == pytest.approx(
        reference.outstanding_residual_gross_notional
    )
    assert payload["package_v2_package_fee_total"] == pytest.approx(reference.package_fee)
    assert payload["total_fee"] == pytest.approx(reference.package_fee)
    assert reference.invariants()["passed"]


def test_atomic_partial_fill_rejects_without_position_mutation() -> None:
    intent = _intent(
        policy=PackageExecutionPolicyV2.ATOMIC_BAR_SIMULATION,
        primary_fraction=0.5,
    )
    rust = _run([intent])
    payload = rust.payload
    np.testing.assert_allclose(payload["final_positions"], [0.0, 0.0])
    assert payload["fill_count"] == 0
    assert int(payload["package_v2_final_state_code"][0]) == 12
    assert payload["package_v2_reservation_created_total"] == 0.0
    assert payload["package_v2_reservation_consumed_total"] == 0.0
    assert payload["package_v2_reservation_released_total"] == 0.0


def test_best_effort_visible_residual_and_unwind_has_no_orphan_exposure() -> None:
    best_effort = _intent(
        policy=PackageExecutionPolicyV2.BEST_EFFORT,
        secondary_min_notional=1_000_000.0,
    )
    best = _run([best_effort])
    assert best.payload["package_v2_residual_package_count"] == 1
    np.testing.assert_allclose(best.payload["final_positions"], [2.0, 0.0])
    assert best.payload["package_v2_outstanding_residual_gross_notional_total"] > 0.0

    unwind = _intent(
        policy=PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY,
        residual=ResidualRiskPolicyV1.UNWIND_PACKAGE,
        primary_fraction=0.5,
    )
    unwrapped = _run([unwind])
    np.testing.assert_allclose(unwrapped.payload["final_positions"], [0.0, 0.0])
    assert unwrapped.payload["package_v2_outstanding_residual_gross_notional_total"] == pytest.approx(0.0)
    assert list(unwrapped.payload["fill_order_id"])[:2] == [10, 11]
    assert len(unwrapped.payload["fill_order_id"]) == 4
    assert unwrapped.payload["package_v2_reservation_created_total"] == pytest.approx(
        unwrapped.payload["package_v2_reservation_consumed_total"]
    )


@pytest.mark.parametrize("leg_count", [2, 4, 20])
def test_low_to_high_leg_counts_match_oracle_and_keep_flat_audit(leg_count: int) -> None:
    intent = _intent(policy=PackageExecutionPolicyV2.SEQUENTIAL, leg_count=leg_count)
    market = _market(leg_count)
    reference = _reference(intent, market)
    rust = _run([intent])
    payload = rust.payload
    np.testing.assert_allclose(
        payload["package_v2_leg_filled_qty"],
        [item.filled_signed_qty for item in reference.legs],
    )
    np.testing.assert_allclose(
        payload["final_positions"],
        [item.filled_signed_qty for item in reference.legs],
    )
    assert len(payload["package_v2_leg_order_id"]) == leg_count
    assert payload["native_workload_audit_kind"] == "package_market_v2"


def test_score_compact_audit_terminal_and_prepared_cache_parity() -> None:
    intent = _intent(policy=PackageExecutionPolicyV2.SEQUENTIAL)
    cache = NativeExecutionPreparationCache()
    score = _run([intent], report_level="score", cache=cache)
    compact = _run([intent], report_level="compact", cache=cache)
    audit = _run([intent], report_level="audit", cache=cache)
    for field in ("final_equity", "total_fee", "total_turnover", "fill_count"):
        assert score.payload[field] == pytest.approx(compact.payload[field])
        assert score.payload[field] == pytest.approx(audit.payload[field])
    np.testing.assert_allclose(score.payload["final_positions"], compact.payload["final_positions"])
    np.testing.assert_allclose(score.payload["final_positions"], audit.payload["final_positions"])
    assert cache.diagnostics["cache_hit"] >= 2


def test_native_package_scenario_batch_has_one_boundary_and_isolated_accounts() -> None:
    first = _intent(policy=PackageExecutionPolicyV2.SEQUENTIAL)
    second = replace(
        first,
        package_id=8,
        command_bar=3,
        legs=tuple(
            replace(leg, order_id=20 + index) for index, leg in enumerate(first.legs)
        ),
    )
    market = _market()
    cache = NativeExecutionPreparationCache()
    batch = cache.package_market_v2_scenario_batch(
        _prepared_template(cache, market),
        **_scenario_arrays([[first], [second]]),
    )
    repeated = cache.package_market_v2_scenario_batch(
        _prepared_template(cache, market),
        **_scenario_arrays([[first], [second]]),
    )
    assert batch is repeated
    payload = dict(batch.core.execute())
    expected_first = _run([first], report_level="score", market=market).payload
    expected_second = _run([second], report_level="score", market=market).payload
    np.testing.assert_allclose(
        payload["final_equity"],
        [expected_first["final_equity"], expected_second["final_equity"]],
    )
    np.testing.assert_allclose(
        payload["total_fee"],
        [expected_first["total_fee"], expected_second["total_fee"]],
    )
    np.testing.assert_array_equal(payload["scenario_id"], [0, 1])
    assert payload["native_entry_calls"] == 1
    assert payload["worker_count"] == 1
    assert payload["market_copy_bytes"] == 0
    assert payload["fingerprint_width"] == 32
    assert payload["terminal_fingerprint_bytes"].size == 64
    assert not any(key.startswith("package_v2_leg_") for key in payload)
    assert cache.diagnostics["cache_hit"] >= 2
    with pytest.raises(TypeError, match="scalar-only"):
        cache.new_runner(batch)


def test_multiple_packages_reuse_one_tape_and_prepared_path_matches_direct() -> None:
    first = _intent(policy=PackageExecutionPolicyV2.SEQUENTIAL)
    second = replace(
        first,
        package_id=8,
        command_bar=3,
        legs=tuple(
            replace(leg, order_id=20 + index) for index, leg in enumerate(first.legs)
        ),
    )
    direct = _run([first, second])
    cache = NativeExecutionPreparationCache()
    prepared = _run([first, second], cache=cache)
    prepared_repeat = _run([first, second], cache=cache)
    for field in (
        "final_equity",
        "total_fee",
        "total_turnover",
        "package_v2_package_fee_total",
        "package_v2_reservation_created_total",
        "package_v2_reservation_consumed_total",
        "package_v2_reservation_released_total",
    ):
        assert direct.payload[field] == pytest.approx(prepared.payload[field])
    np.testing.assert_allclose(direct.payload["final_positions"], [4.0, -2.0])
    np.testing.assert_allclose(
        direct.payload["final_positions"], prepared.payload["final_positions"]
    )
    np.testing.assert_allclose(
        prepared.payload["final_positions"], prepared_repeat.payload["final_positions"]
    )
    assert direct.payload["package_v2_package_count"] == 2
    assert direct.payload["package_v2_accepted_package_count"] == 2
    assert list(direct.payload["package_v2_package_id"]) == [7, 8]
    assert list(direct.payload["package_v2_leg_order_id"]) == [10, 11, 20, 21]
    assert direct.payload["package_v2_reservation_created_total"] == pytest.approx(
        direct.payload["package_v2_reservation_consumed_total"]
        + direct.payload["package_v2_reservation_released_total"]
    )
    assert direct.payload["package_v2_package_fee_total"] == pytest.approx(
        direct.payload["total_fee"]
    )
    assert cache.diagnostics["cache_hit"] >= 1


def test_post_cost_margin_reject_is_immutable_and_reconciles_reservation() -> None:
    intent = _intent(policy=PackageExecutionPolicyV2.ATOMIC_BAR_SIMULATION)
    constrained_market = _market()
    constrained_market["initial_capital"] = 20.0
    output = _run([intent], market=constrained_market).payload
    np.testing.assert_allclose(output["final_positions"], [0.0, 0.0])
    assert output["fill_count"] == 0
    assert int(output["package_v2_final_state_code"][0]) == 12  # PackageStateV2::Aborted
    assert int(output["package_v2_leg_rejection_code"][0]) == 7  # POST_COST_MARGIN
    assert output["package_v2_reservation_created_total"] == 0.0
    assert output["package_v2_reservation_consumed_total"] == 0.0
    assert output["package_v2_reservation_released_total"] == 0.0


def test_invalid_same_bar_bundle_and_stale_package_fail_closed() -> None:
    first = _intent(policy=PackageExecutionPolicyV2.SEQUENTIAL)
    second = replace(first, package_id=8, legs=tuple(replace(leg, order_id=100 + index) for index, leg in enumerate(first.legs)))
    with pytest.raises(ValueError, match="one package per bar"):
        _run([first, second])

    atomic = _intent(policy=PackageExecutionPolicyV2.ATOMIC_BAR_SIMULATION)
    stale_leg = replace(atomic.legs[0], source_age_ns=1)
    stale = replace(atomic, legs=(stale_leg, *atomic.legs[1:]))
    output = _run([stale]).payload
    assert output["fill_count"] == 0
    assert int(output["package_v2_final_state_code"][0]) == 12


def test_selected_linear_arbitrage_adapter_is_typed_and_not_auto_promoted() -> None:
    index = pd.date_range("2025-01-01", periods=5, freq="h", tz="UTC")
    spec = BasisArbitrageSpec(
        arb_id="basis",
        legs=(
            ArbitrageLeg("PERP", -1.0, contract_type=ContractType.LINEAR, qty_step=0.1),
            ArbitrageLeg("FUT", 1.0, contract_type=ContractType.LINEAR, qty_step=0.1),
        ),
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_BASE_QTY,
            base_qty=2.0,
            reference_symbol="PERP",
        ),
        execution_policy=ArbExecutionPolicy(PackageExecutionKind.ATOMIC_ALL_OR_NONE),
    )
    plan = build_arbitrage_order_plan(
        index,
        spec,
        pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=index),
        {
            "PERP": pd.Series([100.0] * len(index), index=index),
            "FUT": pd.Series([102.0] * len(index), index=index),
        },
    )
    tape = compile_bounded_linear_arbitrage_package_tape(
        plan,
        symbol_to_id={"PERP": 0, "FUT": 1},
    )
    assert tape.metadata["adapter"] == "bounded_linear_arbitrage_package_v1"
    assert tape.metadata["auto_promoted"] is False
    assert tape.command_bars.tolist() == [1, 3]
    assert tape.package_leg_offsets.tolist() == [0, 2, 4]
    assert tape.execution_policies.tolist() == ["atomic_bar_simulation"] * 2


@pytest.mark.parametrize("spec_kind", ["triangular", "cross_exchange"])
def test_multi_currency_and_multi_venue_arbitrage_fail_closed(spec_kind: str) -> None:
    common = dict(
        arb_id=spec_kind,
        hedge_policy=HedgePolicy(HedgePolicyKind.BASE_QTY_EQUAL),
        sizing_policy=SizingPolicy(
            SizingPolicyKind.TARGET_BASE_QTY,
            base_qty=1.0,
            reference_symbol="A",
        ),
        execution_policy=ArbExecutionPolicy(PackageExecutionKind.SEQUENTIAL),
    )
    if spec_kind == "triangular":
        spec = TriangularArbSpec(
            legs=(
                ArbitrageLeg("A", 1.0, base_currency="BTC", quote_currency="USDT"),
                ArbitrageLeg("B", -1.0, base_currency="ETH", quote_currency="BTC"),
                ArbitrageLeg("C", 1.0, base_currency="ETH", quote_currency="USDT"),
            ),
            **common,
        )
        expected = "currency conservation"
    else:
        spec = CrossExchangeArbSpec(
            legs=(
                ArbitrageLeg("A", 1.0, venue="A"),
                ArbitrageLeg("B", -1.0, venue="B"),
            ),
            **common,
        )
        expected = "multi-venue prefunding"
    plan = type("Plan", (), {"spec": spec, "orders": (), "target_units": pd.DataFrame()})()
    with pytest.raises(NotImplementedError, match=expected):
        compile_bounded_linear_arbitrage_package_tape(plan, symbol_to_id={"A": 0, "B": 1, "C": 2})


def test_actual_fill_dependency_mutation_corpus_has_no_requested_actual_confusion() -> None:
    """Small deterministic fuzz corpus for the common package hedge mistake."""

    rng = np.random.default_rng(68)
    market = _market()
    for case in range(24):
        primary_qty = float(rng.choice(np.array([0.7, 1.1, 1.7, 2.3])))
        fraction = float(rng.choice(np.array([0.25, 0.5, 0.75, 1.0])))
        ratio = float(rng.choice(np.array([-1.5, -0.75, -0.5, 0.5])))
        step = float(rng.choice(np.array([0.0, 0.05, 0.1])))
        first = PackageLegIntentV2(
            order_id=1000 + case * 2,
            symbol_id=0,
            signed_qty=primary_qty,
            fill_fraction=fraction,
            qty_step=step,
            venue_sequence=0,
        )
        second = PackageLegIntentV2(
            order_id=1001 + case * 2,
            symbol_id=1,
            signed_qty=ratio * primary_qty,
            quantity_source=LegQuantitySourceV1.PROPORTION_OF_ACTUAL_FILL,
            source_leg=0,
            quantity_ratio=ratio,
            fill_fraction=1.0,
            qty_step=step,
            venue_sequence=1,
        )
        intent = PackageIntentV2(
            package_id=100 + case,
            command_bar=1,
            execution_policy=PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY,
            residual_policy=ResidualRiskPolicyV1.RECORD,
            legs=(first, second),
        )
        reference = _reference(intent, market)
        rust = _run([intent]).payload
        expected = np.asarray([item.filled_signed_qty for item in reference.legs])
        np.testing.assert_allclose(rust["package_v2_leg_filled_qty"], expected, atol=1e-12)
        assert float(rust["package_v2_leg_requested_qty"][1]) == pytest.approx(
            reference.legs[1].requested_signed_qty,
            abs=1e-12,
        )
