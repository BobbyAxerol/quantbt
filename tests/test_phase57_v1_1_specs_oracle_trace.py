from __future__ import annotations

import ast
from dataclasses import replace
import json
import math
from pathlib import Path

from hypothesis import given, settings, strategies as st
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderCommand,
    OrderSide,
    OrderType,
    prepare_market_tape,
    run_fill_replay_kernel,
)
from quantbt.core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN
from quantbt.core.intrabar_kernel import FillReplayTape
from quantbt.verification.canonical_trace_v2 import (
    CanonicalEventKindV2,
    CanonicalTraceRowV2,
    CanonicalTraceV2,
    adapt_legacy_trace_v1_to_v2,
    compare_canonical_traces_v2,
    default_linear_trace_tolerance_v2,
    terminal_fingerprint_v2,
)
from reference.python.fill_replay_oracle import ReplayFill, run_fill_replay
from reference.python.linear_accounting_oracle import (
    LinearAccountSpec,
    apply_fill,
    apply_funding,
    initial_state,
    mark_to_market,
    preview_fill_margin,
)
from reference.python.timing_oracle import (
    V2_NEXT_BAR_CLOSE,
    V3_NEXT_OPEN,
    exact_calendar_mapping,
    floor_to_step,
    funding_phase_for_timestamp,
    maintenance_breached,
    oco_sibling_cancellations,
    resolve_effective_command,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "v1_1_correctness_contract.json"
REFERENCE_ROOT = ROOT / "reference" / "python"


def test_phase57_machine_contract_and_docs_define_the_same_foundation() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert payload["contract_id"] == "quantbt-v1_1-correctness-foundation-v1"
    assert payload["canonical_trace_v2"]["schema_version"] == "canonical-trace-v2"
    assert payload["canonical_trace_v2"]["hash"] == "fnv1a-dual-128-v1"
    assert set(payload["mutation_catalog"]) == {
        "funding_sign",
        "fee_side",
        "fill_accounting_order",
        "next_open_vs_same_close",
        "quantity_rounding_direction",
        "maintenance_comparison",
        "oco_sibling_cancellation",
        "calendar_row_relabel",
    }
    for name in ("v1_1_execution_clock.md", "v1_1_linear_accounting.md", "v1_1_canonical_trace_v2.md"):
        document = ROOT / "docs" / "contracts" / name
        assert document.is_file()
        assert "v1_1_correctness_contract.json" in document.read_text(encoding="utf-8")


def test_phase57_oracle_tree_has_no_production_or_acceleration_imports() -> None:
    forbidden = {"quantbt", "numba", "numpy", "pandas", "_quantbt_native"}
    for path in sorted(REFERENCE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".", 1)[0]]
            else:
                continue
            assert not (set(names) & forbidden), f"independent oracle imports production/accelerated code: {path}"


def test_phase57_hand_computable_linear_scale_reduce_reverse_fee_and_funding() -> None:
    spec = LinearAccountSpec(initial_cash=1_000.0, leverage=5.0, maintenance_ratio=0.005)
    state = initial_state(spec)
    opened = apply_fill(state, signed_qty=2.0, price=100.0, fee=0.20, spec=spec).after
    scaled = apply_fill(opened, signed_qty=1.0, price=110.0, fee=0.11, spec=spec).after
    reduced = apply_fill(scaled, signed_qty=-1.0, price=120.0, fee=0.12, spec=spec).after
    closed = apply_fill(reduced, signed_qty=-2.0, price=90.0, fee=0.18, spec=spec).after

    assert opened.cash == pytest.approx(999.80)
    assert scaled.average_entry == pytest.approx(103.33333333333333)
    assert reduced.cumulative_realized_pnl == pytest.approx(16.66666666666667)
    assert reduced.position_qty == pytest.approx(2.0)
    assert closed.position_qty == 0.0
    assert closed.average_entry == 0.0
    assert closed.cumulative_realized_pnl == pytest.approx(-10.0)
    assert closed.cumulative_fees == pytest.approx(0.61)
    assert closed.cash == pytest.approx(989.39)

    reverse = apply_fill(opened, signed_qty=-3.0, price=90.0, fee=0.27, spec=spec).after
    assert reverse.position_qty == pytest.approx(-1.0)
    assert reverse.average_entry == pytest.approx(90.0)
    assert reverse.cumulative_realized_pnl == pytest.approx(-20.0)

    funding = apply_funding(opened, rate=0.001, mark_price=110.0, spec=spec)
    assert funding.charge == pytest.approx(0.22)
    assert funding.after.cash == pytest.approx(opened.cash - 0.22)
    short = apply_fill(initial_state(spec), signed_qty=-2.0, price=100.0, fee=0.0, spec=spec).after
    assert apply_funding(short, rate=0.001, mark_price=110.0, spec=spec).charge == pytest.approx(-0.22)


def test_phase57_post_cost_margin_preview_is_immutable_and_rejects() -> None:
    spec = LinearAccountSpec(initial_cash=100.0, leverage=1.0, maintenance_ratio=0.005)
    state = initial_state(spec)
    preview = preview_fill_margin(
        state,
        signed_qty=2.0,
        price=100.0,
        fee=0.10,
        mark_price=100.0,
        spec=spec,
    )
    assert preview.accepted is False
    assert preview.reason_code == "POST_COST_MARGIN"
    assert state == initial_state(spec)
    assert preview.projected_margin.available_equity < 0.0


def test_phase57_fill_replay_oracle_matches_bounded_production_accounting_anchor() -> None:
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 102.0],
            "high": [101.0, 103.0, 104.0],
            "low": [99.0, 99.0, 101.0],
            "close": [100.0, 102.0, 103.0],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC"),
    )
    spec = LinearAccountSpec(initial_cash=10_000.0)
    oracle = run_fill_replay(
        marks=frame["close"].tolist(),
        fills=(
            ReplayFill(bar_index=1, sequence=0, signed_qty=1.0, price=100.0, fee=0.1),
            ReplayFill(bar_index=2, sequence=0, signed_qty=-1.0, price=103.0, fee=0.103),
        ),
        spec=spec,
    )
    tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    production = run_fill_replay_kernel(
        tape=tape,
        fill_tape=FillReplayTape.from_frame(
            pd.DataFrame(
                [
                    {"bar_index": 1, "sequence": 0, "side": 1, "qty": 1.0, "price": 100.0, "fee": 0.1},
                    {"bar_index": 2, "sequence": 0, "side": -1, "qty": 1.0, "price": 103.0, "fee": 0.103},
                ]
            )
        ),
        account=AccountConfig(initial_capital=10_000.0),
    )
    assert oracle.snapshots[-1].margin.equity == pytest.approx(10_002.797)
    assert oracle.state.position_qty == 0.0
    assert production.equity.iloc[-1] == pytest.approx(oracle.snapshots[-1].margin.equity)
    assert production.position.iloc[-1] == pytest.approx(oracle.state.position_qty)


def test_phase57_timing_hand_examples_cover_first_bar_last_bar_and_funding_boundary() -> None:
    assert resolve_effective_command(contract_id=V2_NEXT_BAR_CLOSE, observed_bar=1, bar_count=4).effective_phase == "NEXT_BAR_CLOSE"
    assert resolve_effective_command(contract_id=V3_NEXT_OPEN, observed_bar=1, bar_count=4).effective_phase == "NEXT_BAR_OPEN"
    assert resolve_effective_command(contract_id=V3_NEXT_OPEN, observed_bar=0, bar_count=4).outcome == "OUTSIDE_TAPE"
    assert resolve_effective_command(contract_id=V3_NEXT_OPEN, observed_bar=3, bar_count=4).outcome == "OUTSIDE_TAPE"
    assert funding_phase_for_timestamp(timestamp_semantics="close") == "AFTER_INTRABAR_BEFORE_COMMAND_MATCHING"
    assert funding_phase_for_timestamp(timestamp_semantics="open") == "BEFORE_OPEN_COMMAND_MATCHING"


def test_phase57_current_python_and_rust_emit_normalized_legacy_v2_rows_without_promotion_claim() -> None:
    pytest.importorskip("_quantbt_native")
    index = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 108.0, 103.0, 96.0, 104.0],
            "high": [103.0, 114.0, 110.0, 106.0, 110.0],
            "low": [98.0, 104.0, 99.0, 91.0, 99.0],
            "close": [101.0, 112.0, 105.0, 103.0, 102.0],
        },
        index=index,
    )
    command = (
        OrderCommand(timestamp=index[1], symbol="BTC", side=OrderSide.BUY, order_type=OrderType.MARKET, qty=1.0, order_id="entry"),
    )

    def run(backend: str):
        engine = NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(initial_capital=10_000.0, leverage=5.0),
                execution=ExecutionConfig(slippage_bps=3.0),
                fee_rate=0.0005,
                report_level="audit",
                native_backend=backend,
                execution_contract=EVENT_LIFECYCLE_V3_NEXT_OPEN,
            )
        )
        return engine.run_order_commands(
            index,
            command,
            closes={"BTC": frame.close},
            highs={"BTC": frame.high},
            lows={"BTC": frame.low},
            opens={"BTC": frame.open},
            symbols=["BTC"],
        )

    python_trace = adapt_legacy_trace_v1_to_v2(run("python").metadata["canonical_trace_v1"])
    rust_trace = adapt_legacy_trace_v1_to_v2(run("rust").metadata["canonical_trace_v1"])
    assert python_trace.rows and rust_trace.rows
    assert python_trace.schema_version == rust_trace.schema_version == "canonical-trace-v2"
    assert len(python_trace.fingerprint()) == len(rust_trace.fingerprint()) == 32
    assert all(row.effective_timestamp_ns >= -1 for row in python_trace.rows + rust_trace.rows)


def _trace_rows() -> tuple[CanonicalTraceRowV2, ...]:
    return (
        CanonicalTraceRowV2(
            sequence=0,
            bar_index=1,
            event_timestamp_ns=1_000,
            effective_timestamp_ns=1_000,
            event_kind=CanonicalEventKindV2.FILL_COMMITTED,
            symbol_id=7,
            order_id=11,
            order_status_code=3,
            qty=1.0,
            price=100.0,
            fee=0.05,
            cash_before=1_000.0,
            cash_after=999.95,
            position_before=0.0,
            position_after=1.0,
            realized_pnl_before=0.0,
            realized_pnl_after=0.0,
            initial_margin_before=0.0,
            initial_margin_after=20.0,
            maintenance_margin_before=0.0,
            maintenance_margin_after=1.0,
        ),
        CanonicalTraceRowV2(
            sequence=1,
            bar_index=1,
            event_timestamp_ns=1_000,
            effective_timestamp_ns=1_000,
            event_kind=CanonicalEventKindV2.ACCOUNT_SNAPSHOT,
            symbol_id=7,
            qty=0.0,
            cash_before=999.95,
            cash_after=999.95,
            position_before=1.0,
            position_after=1.0,
            initial_margin_before=20.0,
            initial_margin_after=20.0,
            maintenance_margin_before=1.0,
            maintenance_margin_after=1.0,
        ),
    )


def test_phase57_canonical_trace_v2_uses_field_specific_tolerance_and_terminal_identity() -> None:
    policy = default_linear_trace_tolerance_v2()
    base = CanonicalTraceV2.from_rows(_trace_rows())
    perturbed_rows = list(_trace_rows())
    perturbed_rows[0] = replace(perturbed_rows[0], fee=perturbed_rows[0].fee + 4e-11)
    perturbed = CanonicalTraceV2.from_rows(perturbed_rows)
    assert compare_canonical_traces_v2(base, perturbed, policy=policy)["passed"] is True
    assert base.fingerprint(policy) == perturbed.fingerprint(policy)

    changed_rows = list(_trace_rows())
    changed_rows[0] = replace(changed_rows[0], qty=changed_rows[0].qty + 2e-12)
    difference = compare_canonical_traces_v2(base, CanonicalTraceV2.from_rows(changed_rows), policy=policy)
    assert difference["passed"] is False
    assert difference["field"] == "qty"

    score = terminal_fingerprint_v2(base, metrics={"sharpe": 1.25, "return": 0.1}, policy=policy)
    compact = terminal_fingerprint_v2(base, metrics={"return": 0.1, "sharpe": 1.25}, policy=policy)
    audit = terminal_fingerprint_v2(base, metrics={"sharpe": 1.25, "return": 0.1}, policy=policy)
    assert score == compact == audit
    assert score.trace_hash == base.fingerprint(policy)


@settings(max_examples=60, deadline=None)
@given(
    quantity=st.floats(min_value=0.01, max_value=20.0, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    fee=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    fraction=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
)
def test_phase57_split_fill_metamorphism(quantity: float, price: float, fee: float, fraction: float) -> None:
    spec = LinearAccountSpec(initial_cash=100_000.0)
    one = apply_fill(initial_state(spec), signed_qty=quantity, price=price, fee=fee, spec=spec).after
    first = apply_fill(initial_state(spec), signed_qty=quantity * fraction, price=price, fee=fee * fraction, spec=spec).after
    split = apply_fill(first, signed_qty=quantity * (1.0 - fraction), price=price, fee=fee * (1.0 - fraction), spec=spec).after
    assert split.position_qty == pytest.approx(one.position_qty, abs=1e-10)
    assert split.average_entry == pytest.approx(one.average_entry, abs=1e-10)
    assert split.cash == pytest.approx(one.cash, abs=1e-9)
    assert mark_to_market(split, mark_price=price, spec=spec).equity == pytest.approx(
        mark_to_market(one, mark_price=price, spec=spec).equity,
        abs=1e-9,
    )


def test_phase57_mutation_catalog_is_killed_by_explicit_specification_fixtures() -> None:
    detected: set[str] = set()
    spec = LinearAccountSpec(initial_cash=1_000.0)
    long = apply_fill(initial_state(spec), signed_qty=1.0, price=100.0, fee=0.0, spec=spec).after
    expected_funding = apply_funding(long, rate=0.001, mark_price=100.0, spec=spec).after.cash
    mutated_funding = long.cash + long.position_qty * 100.0 * 0.001
    if mutated_funding != expected_funding:
        detected.add("funding_sign")

    expected_fee_cash = apply_fill(initial_state(spec), signed_qty=1.0, price=100.0, fee=0.25, spec=spec).after.cash
    if initial_state(spec).cash + 0.25 != expected_fee_cash:
        detected.add("fee_side")

    trace = CanonicalTraceV2.from_rows(_trace_rows())
    reversed_rows = tuple(reversed(_trace_rows()))
    if compare_canonical_traces_v2(trace, CanonicalTraceV2.from_rows(tuple(replace_sequence(row, position) for position, row in enumerate(reversed_rows))))["passed"] is False:
        detected.add("fill_accounting_order")

    if resolve_effective_command(contract_id=V3_NEXT_OPEN, observed_bar=1, bar_count=4).effective_phase != "SAME_CLOSE":
        detected.add("next_open_vs_same_close")
    if floor_to_step(quantity=0.0199, step=0.001) != math.ceil(0.0199 / 0.001) * 0.001:
        detected.add("quantity_rounding_direction")
    if maintenance_breached(equity=10.0, maintenance_margin=10.0) is not (10.0 < 10.0):
        detected.add("maintenance_comparison")
    if oco_sibling_cancellations(filled_order_id=2, sibling_order_ids=[1, 2, 3]) != ():
        detected.add("oco_sibling_cancellation")
    with pytest.raises(ValueError, match="divergence"):
        exact_calendar_mapping([10, 20], [10, 21])
    detected.add("calendar_row_relabel")

    assert detected == set(json.loads(CONTRACT.read_text(encoding="utf-8"))["mutation_catalog"])


def replace_sequence(row: CanonicalTraceRowV2, sequence: int) -> CanonicalTraceRowV2:
    return replace(row, sequence=sequence)
