from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from quantbt import (
    BarView,
    CommandOutcome,
    ExecutionContract,
    FillPhase,
    MarketFillPolicy,
    WorkingOrderView,
    EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
    EVENT_LIFECYCLE_V3_NEXT_OPEN,
    NATIVE_EVENT_CONTRACT_FINGERPRINT,
    decide_bar_fill,
    get_event_clock_contract,
    get_execution_contract,
    lifecycle_transitions,
    validate_lifecycle_transition,
)


ROOT = Path(__file__).resolve().parents[3]


def test_contract_registry_fingerprint_is_canonical() -> None:
    payload = json.loads((ROOT / "contracts/native_event_contract_registry.json").read_text())
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == NATIVE_EVENT_CONTRACT_FINGERPRINT
    assert get_event_clock_contract(EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE).contract_code == 2
    assert get_event_clock_contract(EVENT_LIFECYCLE_V3_NEXT_OPEN).contract_code == 3


def test_installed_native_extension_uses_same_generated_contract_registry() -> None:
    native = pytest.importorskip("_quantbt_native")
    assert native.contract_registry_fingerprint() == NATIVE_EVENT_CONTRACT_FINGERPRINT
    assert tuple(native.event_contract_ids()) == (
        EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
        EVENT_LIFECYCLE_V3_NEXT_OPEN,
    )
    capabilities = native.capabilities()
    assert capabilities["event_contract_registry_v1"]
    assert capabilities["event_lifecycle_v3_next_open"]


def test_execution_contract_names_historical_behavior_honestly() -> None:
    legacy = ExecutionContract.event_lifecycle()
    assert legacy.engine_id == EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE
    assert legacy.entry_fill_phase is FillPhase.NEXT_CLOSE
    assert legacy.market_fill_policy is MarketFillPolicy.NEXT_CLOSE
    assert get_execution_contract("event_lifecycle_v2") == legacy

    current = ExecutionContract.event_lifecycle_v3_next_open()
    assert current.engine_id == EVENT_LIFECYCLE_V3_NEXT_OPEN
    assert current.entry_fill_phase is FillPhase.NEXT_OPEN
    assert current.market_fill_policy is MarketFillPolicy.NEXT_OPEN


@pytest.mark.parametrize("side", [1, -1])
def test_market_fill_oracle_distinguishes_v2_close_from_v3_open(side: int) -> None:
    bar = BarView(open=100.0, high=115.0, low=95.0, close=110.0)
    order = WorkingOrderView(order_type=0, side=side)
    v2 = decide_bar_fill(order, bar, EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, slippage=0.001)
    v3 = decide_bar_fill(order, bar, EVENT_LIFECYCLE_V3_NEXT_OPEN, slippage=0.001)
    side_multiplier = 1.001 if side > 0 else 0.999
    assert v2.fill_price == pytest.approx(110.0 * side_multiplier)
    assert v3.fill_price == pytest.approx(100.0 * side_multiplier)
    assert v2.price_reason == "NEXT_BAR_CLOSE"
    assert v3.price_reason == "NEXT_OPEN"


@pytest.mark.parametrize(
    ("side", "bar", "limit_price", "expected"),
    [
        (1, BarView(95.0, 101.0, 94.0, 99.0), 100.0, 95.0),
        (-1, BarView(105.0, 106.0, 99.0, 101.0), 100.0, 105.0),
    ],
)
def test_v3_limit_gap_uses_open_price_improvement(side, bar, limit_price, expected) -> None:
    decision = decide_bar_fill(
        WorkingOrderView(order_type=1, side=side, price=limit_price),
        bar,
        EVENT_LIFECYCLE_V3_NEXT_OPEN,
    )
    assert decision.matched
    assert decision.fill_price == expected
    assert decision.price_reason == "LIMIT_OPEN_IMPROVEMENT"


@pytest.mark.parametrize(
    ("side", "bar", "trigger", "expected"),
    [
        (1, BarView(110.0, 112.0, 107.0, 109.0), 105.0, 110.11),
        (-1, BarView(90.0, 93.0, 88.0, 91.0), 95.0, 89.91),
    ],
)
def test_v3_adverse_stop_gap_uses_worse_open(side, bar, trigger, expected) -> None:
    decision = decide_bar_fill(
        WorkingOrderView(order_type=2, side=side, trigger_price=trigger),
        bar,
        EVENT_LIFECYCLE_V3_NEXT_OPEN,
        slippage=0.001,
    )
    assert decision.matched
    assert decision.triggered
    assert decision.fill_price == pytest.approx(expected)
    assert decision.price_reason == "STOP_OPEN_WORSE"


def test_v3_stop_limit_unknown_path_arms_without_same_bar_fill() -> None:
    decision = decide_bar_fill(
        WorkingOrderView(order_type=3, side=1, price=104.0, trigger_price=105.0),
        BarView(open=100.0, high=110.0, low=99.0, close=108.0),
        EVENT_LIFECYCLE_V3_NEXT_OPEN,
    )
    assert decision.triggered
    assert decision.ambiguous
    assert not decision.matched
    assert decision.ambiguity_code == "STOP_LIMIT_INTRABAR_PATH_UNKNOWN"


def test_lifecycle_vocabulary_and_transition_table_are_distinct() -> None:
    transitions = lifecycle_transitions()
    assert len(transitions) >= 25
    cancel = validate_lifecycle_transition("cancel", "active", "canceled")
    assert cancel.outcome is CommandOutcome.ACCEPTED
    terminal = validate_lifecycle_transition("cancel", "filled", "filled")
    assert terminal.outcome is CommandOutcome.REJECTED
    with pytest.raises(ValueError, match="invalid or ambiguous"):
        validate_lifecycle_transition("fill", "canceled")
