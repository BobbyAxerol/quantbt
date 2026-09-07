from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st
import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    FillReplayTapeV2 as PublicFillReplayTapeV2,
    FundingReplayTapeV2 as PublicFundingReplayTapeV2,
    QuantBTEndpoint,
    prepare_market_tape,
    run_fill_replay_kernel,
)
from quantbt.core.fill_replay_v2 import (
    FillReplayTapeV2,
    FillReplayV2Error,
    FundingReplayTapeV2,
    run_fill_replay_v2_native,
)
from quantbt.core.intrabar_kernel import FillReplayTape
from quantbt.verification.canonical_trace_v2 import (
    CanonicalEventKindV2,
    CanonicalTraceRowV2,
    CanonicalTraceV2,
    compare_canonical_traces_v2,
)
from reference.python.fill_replay_v2_oracle import (
    EventKind,
    LinearReplaySpecV2,
    ReplayFillV2,
    ReplayFundingV2,
    run_fill_replay_v2,
)


pytest.importorskip("_quantbt_native")


def _index(bars: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-07-01", periods=bars, freq="1h", tz="UTC")


def _frame(index: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    values = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
        },
        index=index,
    )


def _fill_frame(rows: list[ReplayFillV2], symbols: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bar_index": row.bar_index,
                "sequence": row.sequence,
                "event_id": row.event_id,
                "symbol": symbols[row.symbol],
                "signed_qty": row.signed_qty,
                "price": row.price,
                "fee": row.fee,
            }
            for row in rows
        ]
    )


def _funding_frame(rows: list[ReplayFundingV2], symbols: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bar_index": row.bar_index,
                "sequence": row.sequence,
                "event_id": row.event_id,
                "symbol": symbols[row.symbol],
                "rate": row.rate,
            }
            for row in rows
        ]
    )


def _oracle_trace(rows) -> CanonicalTraceV2:
    return CanonicalTraceV2.from_rows(
        CanonicalTraceRowV2(
            sequence=row.sequence,
            bar_index=row.bar_index,
            event_timestamp_ns=row.event_timestamp_ns,
            effective_timestamp_ns=row.effective_timestamp_ns,
            event_kind=CanonicalEventKindV2(row.event_kind),
            symbol_id=row.symbol_id,
            account_id=0,
            reason_code=row.reason_code,
            order_status_code=row.order_status_code,
            qty=row.qty,
            price=row.price,
            fee=row.fee,
            cash_before=row.cash_before,
            cash_after=row.cash_after,
            position_before=row.position_before,
            position_after=row.position_after,
            realized_pnl_before=row.realized_pnl_before,
            realized_pnl_after=row.realized_pnl_after,
            initial_margin_before=row.initial_margin_before,
            initial_margin_after=row.initial_margin_after,
            maintenance_margin_before=row.maintenance_margin_before,
            maintenance_margin_after=row.maintenance_margin_after,
            state_hash_before=row.state_hash_before,
            state_hash_after=row.state_hash_after,
        )
        for row in rows
    )


def _run_rust_v2(
    *,
    marks: list[list[float]],
    symbols: tuple[str, ...],
    fills: list[ReplayFillV2],
    funding: list[ReplayFundingV2],
    initial_capital: float,
    leverage: float,
    maintenance_ratio: float,
    contract_sizes: tuple[float, ...],
    funding_phase: str = "after_fills_at_close",
    liquidation_fee_rate: float = 0.0,
):
    index = _index(len(marks))
    frames = {symbol: _frame(index, [row[column] for row in marks]) for column, symbol in enumerate(symbols)}
    data = frames[symbols[0]] if len(symbols) == 1 else frames
    endpoint = QuantBTEndpoint.fill_replay(
        accounting_backend="rust_v2",
        initial_capital=initial_capital,
        leverage=leverage,
        maintenance_ratio=maintenance_ratio,
        contract_size={symbol: contract_sizes[column] for column, symbol in enumerate(symbols)},
        report_level="audit",
        funding_phase=funding_phase,
        liquidation_fee_rate=liquidation_fee_rate,
        invariant_checks=True,
    )
    return endpoint.backtest(
        data=data,
        symbols=list(symbols),
        fill_replay=_fill_frame(fills, symbols),
        funding_replay=_funding_frame(funding, symbols),
    )


def _assert_oracle_matches_rust(result, oracle) -> None:
    actual_trace = result.metadata["canonical_trace_v2"]
    expected_trace = _oracle_trace(oracle.trace)
    comparison = compare_canonical_traces_v2(expected_trace, actual_trace)
    assert comparison["passed"], comparison
    assert expected_trace.fingerprint() == oracle.trace_fingerprint
    assert actual_trace.fingerprint() == result.metadata["trace_fingerprint"]
    assert result.equity.iloc[-1] == pytest.approx(oracle.account.equity)
    assert result.metadata["accepted_fill_count"] == oracle.accepted_fill_count
    assert result.metadata["rejected_fill_count"] == oracle.rejected_fill_count
    assert result.metadata["accepted_funding_count"] == oracle.accepted_funding_count
    assert result.metadata["rejected_funding_count"] == oracle.rejected_funding_count


def test_phase59_three_way_single_symbol_legacy_oracle_and_rust_v2_terminal_parity() -> None:
    symbols = ("BTC",)
    marks = [[100.0], [102.0], [101.0], [104.0]]
    fills = [
        ReplayFillV2(0, 0, 1, 0, 1.0, 100.0, 0.10),
        ReplayFillV2(1, 0, 2, 0, 1.0, 102.0, 0.102),
        ReplayFillV2(2, 0, 3, 0, -0.5, 101.0, 0.0505),
    ]
    index = _index(len(marks))
    frame = _frame(index, [row[0] for row in marks])
    oracle = run_fill_replay_v2(
        timestamps_ns=tuple(index.view("int64")),
        marks=marks,
        fills=fills,
        funding=(),
        spec=LinearReplaySpecV2(1_000.0, 0.005, (1.0,), (5.0,)),
    )
    rust = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=[],
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
    )
    _assert_oracle_matches_rust(rust, oracle)
    assert rust.metadata["execution_contract_id"] == "fill_replay_v2"
    assert rust.metadata["execution_contract"]["engine_id"] == "fill_replay_v2"
    assert rust.metadata["execution_contract"]["funding_phase"] == "position_at_close"

    legacy_tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    legacy = run_fill_replay_kernel(
        tape=legacy_tape,
        fill_tape=FillReplayTape.from_frame(
            pd.DataFrame(
                [
                    {
                        "bar_index": row.bar_index,
                        "sequence": row.sequence,
                        "side": 1.0 if row.signed_qty > 0.0 else -1.0,
                        "qty": abs(row.signed_qty),
                        "price": row.price,
                        "fee": row.fee,
                    }
                    for row in fills
                ]
            )
        ),
        account=AccountConfig(initial_capital=1_000.0, leverage=5.0),
        contract_size=1.0,
    )
    # V1 does not emit a full V2 account trace or funding/margin state. Its
    # controlled overlap is terminal price/position/fee arithmetic only.
    assert legacy.equity.iloc[-1] == pytest.approx(oracle.account.equity)
    assert legacy.position.iloc[-1] == pytest.approx(oracle.account.qty[0])
    assert legacy.fees.sum() == pytest.approx(oracle.account.fees_paid)


def test_phase59_factory_preserves_explicit_v2_provenance_and_rejects_conflicts() -> None:
    assert PublicFillReplayTapeV2 is FillReplayTapeV2
    assert PublicFundingReplayTapeV2 is FundingReplayTapeV2
    endpoint = QuantBTEndpoint.fill_replay(accounting_backend="rust_v2", invariant_checks=True)
    assert endpoint.config.metadata["execution_contract_id"] == "fill_replay_v2"
    assert endpoint.config.metadata["fill_replay_accounting_backend"] == "rust_v2"
    assert endpoint.config.metadata["fill_replay_funding_phase"] == "after_fills_at_close"
    assert endpoint.config.metadata["fill_replay_invariant_checks"] is True

    legacy = QuantBTEndpoint.fill_replay()
    assert legacy.config.metadata["execution_contract_id"] == "fill_replay_v1"
    assert legacy.config.metadata["fill_replay_accounting_backend"] == "numba_v1"

    with pytest.raises(ValueError, match="conflicts"):
        QuantBTEndpoint.fill_replay(
            accounting_backend="rust_v2",
            metadata={"fill_replay_accounting_backend": "numba_v1"},
        )
    with pytest.raises(ValueError, match="conflicts"):
        QuantBTEndpoint.fill_replay(
            accounting_backend="rust_v2",
            metadata={"execution_contract_id": "fill_replay_v1"},
        )


def test_phase59_split_fill_metamorphism_and_zero_quantity_boundary() -> None:
    symbols = ("BTC",)
    marks = [[100.0], [101.0]]
    aggregate = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=[ReplayFillV2(0, 0, 1, 0, 2.0, 100.0, 0.125)],
        funding=[],
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
    )
    split = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=[
            ReplayFillV2(0, 0, 1, 0, 1.0, 100.0, 0.0625),
            ReplayFillV2(0, 1, 2, 0, 1.0, 100.0, 0.0625),
        ],
        funding=[],
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
    )
    assert split.equity.iloc[-1] == pytest.approx(aggregate.equity.iloc[-1])
    assert split.positions.iloc[-1, 0] == pytest.approx(aggregate.positions.iloc[-1, 0])
    assert split.fees.sum() == pytest.approx(aggregate.fees.sum())

    with pytest.raises(FillReplayV2Error, match="signed_qty"):
        FillReplayTapeV2.from_frame(
            pd.DataFrame(
                [{"bar_index": 0, "sequence": 0, "event_id": 1, "signed_qty": 0.0, "price": 100.0, "fee": 0.0}]
            ),
            symbols=symbols,
            contract_sizes=(1.0,),
        )


def test_phase59_funding_phase_changes_only_the_declared_close_boundary_position() -> None:
    symbols = ("BTC",)
    marks = [[100.0], [100.0]]
    fills = [ReplayFillV2(0, 0, 1, 0, 1.0, 100.0, 0.0)]
    funding = [ReplayFundingV2(0, 1, 2, 0, 0.01)]
    before = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=funding,
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
        funding_phase="before_fills_at_close",
    )
    after = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=funding,
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
        funding_phase="after_fills_at_close",
    )
    assert before.funding.sum() == pytest.approx(0.0)
    assert after.funding.sum() == pytest.approx(1.0)
    assert after.equity.iloc[-1] == pytest.approx(before.equity.iloc[-1] - 1.0)


def test_phase59_endpoint_result_keeps_normal_metrics_surface_and_rejects_open_bar_labels() -> None:
    index = _index(2)
    frame = _frame(index, [100.0, 101.0])
    fills = pd.DataFrame(
        [{"bar_index": 0, "sequence": 0, "event_id": 1, "signed_qty": 1.0, "price": 100.0, "fee": 0.1}]
    )
    endpoint = QuantBTEndpoint.fill_replay(
        accounting_backend="rust_v2",
        initial_capital=1_000.0,
        leverage=5.0,
        report_level="audit",
    )
    result = endpoint.backtest(data=frame, symbols=["BTC"], fill_replay=fills)
    report = endpoint.full_report(trading_days=365)
    assert report["final_equity"] == pytest.approx(result.equity.iloc[-1])
    assert result.metadata["accounting_authority"] == "linear_gross_cross_v1"

    open_labeled = QuantBTEndpoint.fill_replay(
        accounting_backend="rust_v2",
        bar_timestamp_semantics="open",
    )
    with pytest.raises(NotImplementedError, match="close-timestamp"):
        open_labeled.backtest(data=frame, symbols=["BTC"], fill_replay=fills)


def test_phase59_multisymbol_funding_scale_reduce_reverse_and_trace_parity() -> None:
    symbols = ("BTC", "ETH")
    marks = [[100.0, 50.0], [110.0, 45.0], [90.0, 60.0]]
    fills = [
        ReplayFillV2(0, 0, 1, 0, 2.0, 100.0, 0.20),
        ReplayFillV2(1, 0, 2, 1, -1.0, 45.0, 0.09),
        ReplayFillV2(2, 0, 3, 0, -3.0, 90.0, 0.27),
    ]
    funding = [ReplayFundingV2(1, 0, 8, 0, 0.001)]
    index = _index(len(marks))
    oracle = run_fill_replay_v2(
        timestamps_ns=tuple(index.view("int64")),
        marks=marks,
        fills=fills,
        funding=funding,
        spec=LinearReplaySpecV2(1_000.0, 0.005, (1.0, 2.0), (5.0, 5.0), 0.001),
    )
    rust = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=funding,
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0, 2.0),
        liquidation_fee_rate=0.001,
    )
    _assert_oracle_matches_rust(rust, oracle)
    assert rust.positions.iloc[-1].to_dict() == pytest.approx({"Position_BTC": -1.0, "Position_ETH": -1.0})
    assert rust.funding.sum() == pytest.approx(oracle.account.funding_paid)


def test_phase59_post_cost_margin_reject_is_immutable_and_canonical() -> None:
    symbols = ("BTC",)
    marks = [[100.0], [100.0]]
    fills = [ReplayFillV2(0, 0, 1, 0, 2.0, 100.0, 0.10)]
    index = _index(len(marks))
    oracle = run_fill_replay_v2(
        timestamps_ns=tuple(index.view("int64")),
        marks=marks,
        fills=fills,
        funding=(),
        spec=LinearReplaySpecV2(100.0, 0.005, (1.0,), (1.0,)),
    )
    rust = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=[],
        initial_capital=100.0,
        leverage=1.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
    )
    _assert_oracle_matches_rust(rust, oracle)
    assert oracle.account.cash == pytest.approx(100.0)
    assert oracle.account.qty == (0.0,)
    rejected = [row for row in rust.metadata["canonical_trace_v2"].rows if row.event_kind is CanonicalEventKindV2.COMMAND_REJECTED]
    assert len(rejected) == 1
    assert rejected[0].reason_code == 7


def test_phase59_funding_apply_once_and_phase_order_are_explicit() -> None:
    symbols = ("BTC",)
    marks = [[100.0], [110.0]]
    fills = [ReplayFillV2(0, 0, 1, 0, 1.0, 100.0, 0.0)]
    funding = [
        ReplayFundingV2(1, 0, 2, 0, 0.001),
        ReplayFundingV2(1, 1, 2, 0, 0.001),
    ]
    index = _index(len(marks))
    oracle = run_fill_replay_v2(
        timestamps_ns=tuple(index.view("int64")),
        marks=marks,
        fills=fills,
        funding=funding,
        spec=LinearReplaySpecV2(1_000.0, 0.005, (1.0,), (5.0,), funding_phase="after_fills_at_close"),
    )
    rust = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=funding,
        initial_capital=1_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=(1.0,),
    )
    _assert_oracle_matches_rust(rust, oracle)
    assert rust.funding.sum() == pytest.approx(0.11)
    assert any(
        row.event_kind is CanonicalEventKindV2.COMMAND_REJECTED and row.reason_code == 12
        for row in rust.metadata["canonical_trace_v2"].rows
    )


def test_phase59_liquidation_emits_executable_close_fills_and_terminal_state() -> None:
    symbols = ("BTC",)
    marks = [[100.0], [10.0]]
    fills = [ReplayFillV2(0, 0, 1, 0, 5.0, 100.0, 0.0)]
    index = _index(len(marks))
    oracle = run_fill_replay_v2(
        timestamps_ns=tuple(index.view("int64")),
        marks=marks,
        fills=fills,
        funding=(),
        spec=LinearReplaySpecV2(100.0, 0.1, (1.0,), (10.0,), 0.01),
    )
    rust = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=[],
        initial_capital=100.0,
        leverage=10.0,
        maintenance_ratio=0.1,
        contract_sizes=(1.0,),
        liquidation_fee_rate=0.01,
    )
    _assert_oracle_matches_rust(rust, oracle)
    assert rust.liquidated is True
    assert rust.positions.iloc[-1, 0] == pytest.approx(0.0)
    event_kinds = [row.event_kind for row in rust.metadata["canonical_trace_v2"].rows]
    assert EventKind.LIQUIDATION_STARTED in [int(value) for value in event_kinds]
    assert EventKind.LIQUIDATION_FILL in [int(value) for value in event_kinds]
    assert EventKind.LIQUIDATION_COMPLETED in [int(value) for value in event_kinds]


def test_phase59_score_compact_and_audit_share_terminal_fingerprint() -> None:
    index = _index(3)
    frame = _frame(index, [100.0, 102.0, 99.0])
    tape = prepare_market_tape(data=frame, symbols=["BTC"], use_funding=False)
    fill_frame = pd.DataFrame(
        [
            {"bar_index": 0, "sequence": 0, "event_id": 1, "signed_qty": 1.0, "price": 100.0, "fee": 0.1},
            {"bar_index": 2, "sequence": 0, "event_id": 2, "signed_qty": -1.0, "price": 99.0, "fee": 0.099},
        ]
    )
    fills = FillReplayTapeV2.from_frame(fill_frame, symbols=("BTC",), contract_sizes=(1.0,))
    account = AccountConfig(initial_capital=1_000.0, leverage=5.0, maintenance_ratio=0.005)
    runs = {
        profile: run_fill_replay_v2_native(
            tape=tape,
            fills=fills,
            funding=FundingReplayTapeV2.empty(),
            account=account,
            contract_sizes=(1.0,),
            leverages=(5.0,),
            output_profile=profile,
            invariant_checks=True,
        )
        for profile in ("score", "compact", "audit")
    }
    scalar_keys = ("final_cash", "final_equity", "total_realized_pnl", "total_fees", "total_funding")
    for key in scalar_keys:
        assert float(runs["score"].score[key]) == pytest.approx(float(runs["audit"].score[key]))
        assert float(runs["compact"].score[key]) == pytest.approx(float(runs["audit"].score[key]))
    assert runs["score"].score["account_fingerprint"] == runs["audit"].score["account_fingerprint"]
    assert runs["score"].score["trace_fingerprint"] == runs["audit"].score["trace_fingerprint"]
    assert runs["score"].equity is None
    assert runs["compact"].canonical_trace is None
    assert runs["audit"].canonical_trace is not None


@settings(max_examples=60, deadline=None)
@given(
    symbol_count=st.integers(min_value=1, max_value=3),
    bars=st.integers(min_value=2, max_value=5),
    seed=st.integers(min_value=1, max_value=10_000),
)
def test_phase59_randomized_small_streams_match_independent_oracle(symbol_count: int, bars: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    symbols = tuple(f"S{index}" for index in range(symbol_count))
    marks = (90.0 + rng.random((bars, symbol_count)) * 20.0).tolist()
    fills: list[ReplayFillV2] = []
    for bar in range(bars):
        symbol = int(rng.integers(0, symbol_count))
        quantity = float(rng.choice(np.asarray([-0.75, -0.5, -0.25, 0.25, 0.5, 0.75])))
        price = float(marks[bar][symbol] * (0.995 + rng.random() * 0.01))
        fills.append(ReplayFillV2(bar, 0, bar + 1, symbol, quantity, price, abs(quantity) * price * 0.0005))
    funding = [ReplayFundingV2(bars - 1, 0, 10_000 + seed, 0, 0.0001)]
    index = _index(bars)
    oracle = run_fill_replay_v2(
        timestamps_ns=tuple(index.view("int64")),
        marks=marks,
        fills=fills,
        funding=funding,
        spec=LinearReplaySpecV2(1_000_000.0, 0.005, tuple(1.0 + column for column in range(symbol_count)), (5.0,) * symbol_count),
    )
    rust = _run_rust_v2(
        marks=marks,
        symbols=symbols,
        fills=fills,
        funding=funding,
        initial_capital=1_000_000.0,
        leverage=5.0,
        maintenance_ratio=0.005,
        contract_sizes=tuple(1.0 + column for column in range(symbol_count)),
    )
    _assert_oracle_matches_rust(rust, oracle)
    assert math.isfinite(float(rust.equity.iloc[-1]))
