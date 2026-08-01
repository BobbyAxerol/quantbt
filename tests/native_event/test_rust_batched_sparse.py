from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from quantbt import RustBatchedSession
from quantbt.backends._native_event_rust import NativeEventRustBackendError

from .test_rust_batched_full_tape import _fixture


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native sparse wheel is not installed in this environment",
)


def test_sparse_chunks_preserve_full_tape_accounting_and_ledger() -> None:
    _, _, _, _, compiled, runner = _fixture()
    full = runner.run_tape_audit(compiled)
    session = runner.open_sparse_session(compiled)

    chunks = [
        session.run_until(3),
        session.run_until(7),
        session.run_until(11),
    ]

    assert isinstance(session, RustBatchedSession)
    assert [(chunk.start_bar, chunk.stop_bar) for chunk in chunks] == [(0, 3), (4, 7), (8, 11)]
    assert session.next_bar == 12
    np.testing.assert_allclose(chunks[-1].final_equity, full.equity[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(chunks[-1].final_position, full.positions[-1], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(sum(chunk.total_fee for chunk in chunks), full.total_fee, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(
        sum(chunk.total_turnover for chunk in chunks), full.total_turnover, rtol=0.0, atol=1e-12
    )
    assert sum(chunk.fill_count for chunk in chunks) == full.fill_count
    assert sum(chunk.event_count for chunk in chunks) == full.event_count
    assert sum(chunk.rejected_count for chunk in chunks) == full.rejected_count
    assert sum(chunk.canceled_count for chunk in chunks) == full.canceled_count

    for name in (
        "fill_bar",
        "fill_order_id",
        "fill_side",
        "fill_qty",
        "fill_price",
        "fill_fee",
        "event_bar",
        "event_kind",
        "event_status",
        "event_order_id",
        "event_target_id",
    ):
        combined = np.concatenate([getattr(chunk, name) for chunk in chunks])
        np.testing.assert_array_equal(combined, getattr(full, name))
    assert all(chunk.wake_kind[-1] == 2 for chunk in chunks)


def test_sparse_wake_filters_do_not_change_accounting() -> None:
    _, _, _, _, compiled, runner = _fixture()
    session = runner.open_sparse_session(compiled)
    chunk = session.run_until(11, wake_on_fill=False, wake_on_order_event=False, wake_on_liquidation=False)

    np.testing.assert_array_equal(chunk.wake_kind, np.array([2], dtype=np.int64))
    assert chunk.liquidation_seen is False
    assert chunk.metadata["dense_paths_materialized"] is False


def test_sparse_session_rejects_missing_or_replaced_tape() -> None:
    _, _, _, _, compiled, runner = _fixture()
    with pytest.raises(NativeEventRustBackendError, match="compiled command tape"):
        runner.open_sparse_session().run_until(2)

    session = runner.open_sparse_session(compiled)
    session.run_until(2)
    with pytest.raises(NativeEventRustBackendError, match="replace the command tape"):
        session.run_until(3, _fixture()[4])
    with pytest.raises(ValueError, match="must advance"):
        session.run_until(2)
