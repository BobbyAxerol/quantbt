"""Synthetic transport parity, with no private alpha or search inputs."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from tools.mode5_research.compact_feedback import (
    CompactFeedbackCompiler, CompactFeedbackView, CompactTapeFeedback, decode_packet,
)
from tools.mode5_research.delta_feedback_tape import DeltaTapeRows
from tools.mode5_research.transactional_feedback import TransactionalTapeFeedback


_spec = importlib.util.spec_from_file_location("_compact_original_test_oracle",
    Path(__file__).parent / "mode5/test_transactional_feedback.py")
oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oracle)
prepared = oracle.prepared


def run(packed, commands, kind, *, start=0):
    if kind == "original":
        owner = TransactionalTapeFeedback(packed, index=packed.index, start=start, symbol="X")
    else:
        delta = DeltaTapeRows(packed.backend, packed.runner, packed.index, "X", packed.constraints)
        owner = CompactTapeFeedback(delta, index=packed.index, start=start, symbol="X", fused=kind=="fused")
    before = None
    try:
        for local in range(len(packed.index)):
            known = tuple(c for c in commands if c.timestamp <= packed.index[local])
            after = owner.begin_bar(start+local, known)
            checker = CompactFeedbackCompiler if kind != "original" else oracle.IncrementalFeedbackCompiler
            checker._prefix_unchanged(before, after, start+local)
            before = after
            assert owner(known) is after if kind != "original" else True
            owner.commit_bar(start+local)
        audit = owner.audit()
        if kind == "fused":
            assert owner.native_boundary_calls == len(packed.index)+1
        return audit
    finally:
        owner.close()


@oracle.requires_transaction
@pytest.mark.parametrize("kind", ["delta", "fused"])
@pytest.mark.parametrize("scenario", ["flat", "bracket", "amend_cancel", "reject", "funding", "liquidation"])
def test_actual_native_account_and_lifecycle(prepared, kind, scenario):
    if kind == "fused" and not hasattr(oracle._native.NativeFeedbackSessionCore, "advance_packed"):
        pytest.skip("packed companion native extension required")
    frame = oracle.market()
    kwargs = {}
    if scenario == "funding":
        frame["funding"] = 0.0001
        kwargs["funding"] = True
    if scenario == "liquidation":
        frame.loc[frame.index[3]:, ["open", "high", "low", "close"]] = [10., 11., 9., 10.]
        kwargs.update(capital=100., leverage=20.)
    reference, candidate = prepared(frame, **kwargs), prepared(frame, **kwargs)
    commands = () if scenario == "flat" else (oracle.order(frame.index, 1, "entry", qty=5.),)
    if scenario == "bracket":
        commands += oracle.bracket(frame.index, 1, "entry", price=100., qty=5.)
    elif scenario == "amend_cancel":
        commands += (
            oracle.order(frame.index, 2, "limit", order_type=oracle.OrderType.LIMIT, price=95.),
            oracle.action(frame.index, 3, "change", oracle.OrderAction.AMEND, target_order_id="limit", price=96.),
            oracle.action(frame.index, 4, "cancel", oracle.OrderAction.CANCEL, target_order_id="limit"),
            oracle.order(frame.index, 5, "exit", side=oracle.OrderSide.SELL, qty=5., reduce_only=True),
        )
    elif scenario == "reject":
        commands += (oracle.order(frame.index, 2, "reject", side=oracle.OrderSide.SELL, qty=100., reduce_only=True),)
    expected = run(reference, commands, "original", start=37)
    actual = run(candidate, commands, kind, start=37)
    oracle.assert_audit(actual, expected)
    assert actual.id_values == expected.id_values
    for field in oracle.PATHS + oracle.EVENTS + oracle.FILLS:
        assert not getattr(actual, field).flags.writeable


@oracle.requires_transaction
@pytest.mark.parametrize("kind", ["delta", "fused"])
def test_same_bar_actual_fill_feedback_retry(prepared, kind):
    if kind == "fused" and not hasattr(oracle._native.NativeFeedbackSessionCore, "advance_packed"):
        pytest.skip("packed companion native extension required")
    packed = prepared()
    delta = DeltaTapeRows(packed.backend, packed.runner, packed.index, "X", packed.constraints)
    owner = CompactTapeFeedback(delta, index=packed.index, start=0, symbol="X", fused=kind=="fused")
    entry = oracle.order(packed.index, 1, "entry")
    try:
        empty = owner.begin_bar(0, ())
        owner.commit_bar(0)
        first = owner.begin_bar(1, (entry,))
        assert first.events[0].kind == "fill"
        commands = (entry,) + oracle.bracket(packed.index, 1, "entry", price=100.)
        retry = owner(commands)
        CompactFeedbackCompiler._prefix_unchanged(first, retry, 1)
        assert retry.account_bytes == first.account_bytes
        assert owner.same_bar_steps == 1
        owner.commit_bar(1)
        for bar in range(2, len(packed.index)):
            owner.begin_bar(bar, commands)
            owner.commit_bar(bar)
        expected = oracle.reference_audit(prepared(), commands)
        oracle.assert_audit(owner.audit(), expected)
    finally:
        owner.close()


def test_packet_keeps_large_integer_ids_and_exact_float_bits():
    account = np.array([-0., 1., 2., 3., 4., 5., 6.], dtype=np.float64).tobytes()
    row = np.array([[4, 1, 2**53+3, -1, 0, 0]], dtype=np.int64).tobytes()
    terminal = np.array([0, -1, 0], dtype=np.int64).tobytes()
    step = decode_packet((account, row, b"", b"", terminal))
    assert step.event_order_id == (2**53+3,)
    assert np.signbit(step.equity)
    with pytest.raises(ValueError):
        decode_packet((account, row, b"", b"", b""))
    with pytest.raises(TypeError):
        decode_packet((bytearray(account), row, b"", b"", terminal))


def test_prefix_certificate_never_accepts_different_owners():
    left, right = object.__new__(CompactFeedbackView), object.__new__(CompactFeedbackView)
    left.owner, right.owner = object(), object()
    with pytest.raises(AssertionError, match="owner"):
        CompactFeedbackCompiler._prefix_unchanged(left, right, 1)
