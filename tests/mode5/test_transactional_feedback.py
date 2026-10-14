"""Synthetic transaction differentials; no private alpha or optimizer inputs.

Native cases must be run against the qualified candidate extension. An older
wheel skips only those cases, not the explicit unsupported-capability tests.
"""

from copy import deepcopy
from dataclasses import replace
import importlib
import importlib.util
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
)
from quantbt import (
    OrderAction,
    OrderActivationPolicy,
    OrderCommand,
    OrderSide,
    OrderType,
)
from quantbt import TimeInForce
from quantbt.backends._native_event_rust import RustFullAuditResult
from quantbt.core.constraints import build_quantity_constraints
from tools.mode5_research.incremental_feedback import IncrementalFeedbackCompiler
from tools.mode5_research.prepared_feedback import CachedTapeRows, LazyEngineFeedback
from tools.mode5_research.transactional_feedback import TransactionalTapeFeedback


_native = (
    importlib.import_module("_quantbt_native")
    if importlib.util.find_spec("_quantbt_native") is not None
    else None
)
requires_transaction = pytest.mark.skipif(
    not hasattr(_native, "NativeFeedbackSessionCore"),
    reason="candidate NativeFeedbackSessionCore absent; native transaction parity NOT qualified",
)

PATHS = (
    "equity",
    "positions",
    "fees",
    "funding",
    "turnover",
    "initial_margin",
    "maintenance_margin",
)
EVENTS = (
    "event_bar",
    "event_kind",
    "event_status",
    "event_order_id",
    "event_target_id",
    "event_symbol",
    "event_reject_code",
)
FILLS = (
    "fill_bar",
    "fill_order_id",
    "fill_symbol",
    "fill_side",
    "fill_qty",
    "fill_price",
    "fill_fee",
    "fill_reason",
    "fill_ambiguity",
    "fill_order_type",
)
ID_FIELDS = ("event_order_id", "event_target_id", "fill_order_id")
TERMINAL = ("liquidated", "liquidation_bar", "liquidation_reason")
FLOAT_FIELDS = frozenset(PATHS + ("fill_qty", "fill_price", "fill_fee"))
TRANSACTION_ERRORS = (ValueError, RuntimeError)


def decoded(audit, field):
    return tuple(
        None if int(code) < 0 else audit.id_values[int(code)]
        for code in getattr(audit, field)
    )


def assert_audit(actual, reference):
    for field in PATHS + EVENTS + FILLS:
        left, right = getattr(actual, field), getattr(reference, field)
        assert isinstance(left, np.ndarray), field
        assert isinstance(right, np.ndarray), field
        assert left.dtype == right.dtype, field
        assert left.shape == right.shape, field
        if field in ID_FIELDS:
            assert decoded(actual, field) == decoded(reference, field), field
        else:
            np.testing.assert_array_equal(left, right, err_msg=field)
    for field in TERMINAL:
        assert getattr(actual, field) == getattr(reference, field), field


def reference_audit(packed, commands):
    payload, ids = packed.execute(tuple(commands))
    return RustFullAuditResult.from_audit_payload(
        payload, n_bars=len(packed.index), n_symbols=1, id_values=ids
    )


def market(*, size=12, **overrides):
    index = pd.date_range("2024-01-01", periods=size, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "funding": 0.0},
        index=index,
    )
    for name, values in overrides.items():
        frame[name] = values
    return frame


@pytest.fixture
def prepared():
    owners = []

    def create(
        frame=None, *, capital=20_000.0, leverage=5.0, funding=False, qty_step=0.01
    ):
        frame = market() if frame is None else frame
        backend = NativeEventBackend(
            NativeEventConfig(
                account=AccountConfig(
                    initial_capital=capital, leverage=leverage, maintenance_ratio=0.005
                ),
                execution=ExecutionConfig(slippage_bps=0.0),
                fee_rate=0.0002,
                use_funding=funding,
                native_backend="rust",
                execution_contract="event_lifecycle_v3_next_open",
            )
        )
        runner = backend.prepare_rust_batched_runner(
            frame.index,
            closes={"X": frame.close},
            highs={"X": frame.high},
            lows={"X": frame.low},
            opens={"X": frame.open},
            funding_rate={"X": frame.funding},
            symbols=["X"],
            contract_size=1.0,
        )
        owners.append((backend, runner))
        constraints = build_quantity_constraints(
            ["X"], qty_step=qty_step, min_qty=qty_step
        )
        return CachedTapeRows(backend, runner, frame.index, "X", constraints)

    try:
        yield create
    finally:
        for backend, runner in reversed(owners):
            runner.clear_caches()
            backend.clear_prepared_caches()


def order(index, bar, name, **kwargs):
    defaults = dict(
        symbol="X",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1.0,
        tif=TimeInForce.GTC,
    )
    defaults.update(kwargs)
    return OrderCommand(timestamp=index[bar], order_id=name, **defaults)


def action(index, bar, name, kind, **kwargs):
    return OrderCommand(timestamp=index[bar], order_id=name, action=kind, **kwargs)


def bracket(index, bar, entry, *, price, qty=1.0):
    common = dict(
        side=OrderSide.SELL,
        qty=qty,
        reduce_only=True,
        parent_order_id=entry,
        group_id="campaign",
        oco_group_id="bracket",
        activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
    )
    return (
        order(
            index,
            bar,
            "stop",
            order_type=OrderType.STOP_MARKET,
            trigger_price=price - 3.0,
            **common,
        ),
        order(
            index, bar, "tp", order_type=OrderType.LIMIT, price=price + 3.0, **common
        ),
    )


def run_executor(packed, commands, *, start=0, incremental=False):
    executor = TransactionalTapeFeedback(
        packed, index=packed.index, start=start, symbol="X"
    )
    try:
        known = () if incremental else tuple(commands)
        for local in range(len(packed.index)):
            executor.begin_bar(start + local, known)
            if incremental:
                known = tuple(c for c in commands if c.timestamp <= packed.index[local])
            executor(known)
            executor.commit_bar(start + local)
        return executor.audit()
    finally:
        executor.close()


def oracle_stub():
    result = SimpleNamespace(
        id_values=("entry", "stop"),
        liquidated=False,
        liquidation_bar=-1,
        liquidation_reason=0,
    )
    for field in PATHS + EVENTS + FILLS:
        dtype = np.float64 if field in FLOAT_FIELDS else np.int64
        shape = (2, 1) if field == "positions" else (2,)
        setattr(result, field, np.zeros(shape, dtype=dtype))
    return result


def test_differential_decodes_ids_instead_of_requiring_namespace_order():
    left, right = oracle_stub(), oracle_stub()
    right.id_values = ("unused", "stop", "entry")
    for field in ID_FIELDS:
        getattr(right, field)[:] = 2
    assert_audit(left, right)
    right.fill_order_id[0] = 1
    with pytest.raises(AssertionError, match="fill_order_id"):
        assert_audit(left, right)


@pytest.mark.parametrize("field", PATHS + EVENTS + FILLS + TERMINAL)
def test_differential_checks_every_account_and_lifecycle_field(field):
    left, right = oracle_stub(), oracle_stub()
    if field in TERMINAL:
        setattr(right, field, getattr(right, field) + 1)
    else:
        getattr(right, field).flat[0] += 1
    with pytest.raises(AssertionError):
        assert_audit(left, right)


def test_old_native_module_fails_closed_before_any_preparation_or_execution():
    class OldModule:
        @staticmethod
        def FullReactiveSessionCore(*args, **kwargs):
            pytest.fail("transaction request silently used legacy native session")

    packed = SimpleNamespace(runner=SimpleNamespace(_module=OldModule()))
    with pytest.raises(NotImplementedError, match="transactional_feedback_v1"):
        TransactionalTapeFeedback(packed, index=pd.RangeIndex(3), start=0, symbol="X")


def test_native_factory_failure_is_not_converted_to_unsupported_fallback():
    class BrokenFactory:
        @staticmethod
        def from_template(template):
            raise RuntimeError("candidate template failure")

    module = SimpleNamespace(NativeFeedbackSessionCore=BrokenFactory)
    packed = SimpleNamespace(
        runner=SimpleNamespace(_module=module, _typed_template=object())
    )
    with pytest.raises(RuntimeError, match="candidate template failure"):
        TransactionalTapeFeedback(packed, index=pd.RangeIndex(3), start=0, symbol="X")


@requires_transaction
@pytest.mark.parametrize("incremental", [False, True], ids=["preloaded", "growing"])
@pytest.mark.parametrize("start", [0, 100])
def test_empty_and_growing_tapes_keep_offset_account_and_bar_zero_contract(
    prepared, incremental, start
):
    packed = prepared()
    index = packed.index
    empty = run_executor(packed, (), start=start, incremental=incremental)
    assert_audit(empty, reference_audit(packed, ()))
    commands = (
        order(index, 0, "ignored-at-zero"),
        order(index, 1, "entry"),
        order(index, 5, "exit", side=OrderSide.SELL, reduce_only=True),
    )
    actual = run_executor(packed, commands, start=start, incremental=incremental)
    assert_audit(actual, reference_audit(packed, commands))
    assert decoded(actual, "fill_order_id") == ("entry", "exit")
    assert "ignored-at-zero" not in decoded(actual, "event_order_id")


@requires_transaction
@pytest.mark.parametrize(
    "outcome", ["same-tp", "same-stop", "ambiguous", "gap-tp", "gap-stop"]
)
def test_actual_gap_fill_adds_bracket_and_retries_only_current_bar(prepared, outcome):
    frame = market()
    frame.loc[frame.index[3], ["open", "high", "low", "close"]] = [
        90.0,
        91.0,
        89.0,
        90.0,
    ]
    if outcome in {"same-tp", "ambiguous"}:
        frame.loc[frame.index[3], "high"] = 96.0
    if outcome in {"same-stop", "ambiguous"}:
        frame.loc[frame.index[3], "low"] = 86.0
    if outcome == "gap-stop":
        frame.loc[frame.index[4], ["open", "high", "low", "close"]] = [
            80.0,
            82.0,
            78.0,
            80.0,
        ]
    packed = prepared(frame)
    index = packed.index
    entry = order(
        index,
        1,
        "entry",
        order_type=OrderType.LIMIT,
        price=98.0,
        metadata={"campaign_id": "actual-fill-owner"},
    )
    commands = (entry,)
    executor = TransactionalTapeFeedback(packed, index=index, start=0, symbol="X")
    try:
        for bar in range(len(index)):
            before = {field: executor.paths[field][:bar].copy() for field in PATHS}
            prefix = executor.events_before(bar)
            view = executor.begin_bar(bar, commands)
            if bar == 3:
                (event,) = view.events_at(bar)
                assert event.order_id == "entry" and event.kind == "fill"
                assert event.fill.price == 90.0 and event.fill.timestamp == index[bar]
                assert event.fill.metadata == entry.metadata
                commands += bracket(index, bar, "entry", price=event.fill.price)
                view = executor(commands)
                snapshot = {
                    field: np.asarray(getattr(view.step, field)).copy()
                    for field in ("fill_order_id", "fill_qty", "fill_price")
                }
                repeated = executor(commands)
                for field, values in snapshot.items():
                    np.testing.assert_array_equal(getattr(repeated.step, field), values)
                if outcome.startswith("same") or outcome == "ambiguous":
                    assert len(view.events_at(bar)) >= 2
                assert executor.events_before(bar) == prefix
            for field in PATHS:
                np.testing.assert_array_equal(
                    executor.paths[field][:bar], before[field]
                )
            executor.commit_bar(bar)
        actual = executor.audit()
        assert_audit(actual, reference_audit(packed, commands))
        assert len(actual.fill_bar) == 2
        assert actual.fill_bar[0] == 3
        assert actual.fill_bar[1] == (
            3 if outcome.startswith("same") or outcome == "ambiguous" else 4
        )
        assert actual.positions[-1, 0] == 0.0
        if outcome == "gap-stop":
            assert actual.fill_price[-1] == 80.0
        if outcome == "gap-tp":
            assert actual.fill_price[-1] == 100.0
        assert executor.transactions == len(index)
        assert executor.same_bar_steps == 1
        assert executor.native_step_calls == len(index) + 1
        assert executor.full_tape_executions == 0
    finally:
        executor.close()


@requires_transaction
def test_partial_ladder_quantization_and_reduce_only_residual_match_full_audit(
    prepared,
):
    frame = market()
    frame.loc[frame.index[2], ["high", "low", "close"]] = [103.0, 99.0, 102.0]
    frame.loc[frame.index[3], ["open", "high", "low", "close"]] = [
        102.0,
        105.0,
        100.0,
        104.0,
    ]
    frame.loc[frame.index[4], ["open", "high", "low", "close"]] = [
        95.0,
        96.0,
        94.0,
        95.0,
    ]
    packed = prepared(frame, qty_step=0.25)
    index = packed.index
    common = dict(
        side=OrderSide.SELL,
        reduce_only=True,
        parent_order_id="entry",
        group_id="ladder",
        activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
    )
    commands = (
        order(index, 1, "entry", qty=3.13),
        order(
            index,
            1,
            "tp-1",
            qty=0.75,
            order_type=OrderType.LIMIT,
            price=102.0,
            **common,
        ),
        order(
            index,
            1,
            "tp-2",
            qty=0.75,
            order_type=OrderType.LIMIT,
            price=104.0,
            **common,
        ),
        order(
            index,
            1,
            "residual",
            qty=3.0,
            order_type=OrderType.STOP_MARKET,
            trigger_price=97.0,
            **common,
        ),
    )
    actual = run_executor(packed, commands, incremental=True)
    assert_audit(actual, reference_audit(packed, commands))
    assert decoded(actual, "fill_order_id") == ("entry", "tp-1", "tp-2", "residual")
    np.testing.assert_array_equal(actual.fill_qty, [3.0, 0.75, 0.75, 1.5])
    np.testing.assert_array_equal(actual.positions[1:5, 0], [3.0, 2.25, 1.5, 0.0])


@requires_transaction
def test_amend_cancel_replace_expiry_and_cancel_all_preserve_target_ids(prepared):
    packed = prepared()
    index = packed.index
    commands = (
        order(index, 1, "amended", order_type=OrderType.LIMIT, price=90.0),
        order(index, 1, "canceled", order_type=OrderType.LIMIT, price=89.0),
        order(index, 1, "replaced", order_type=OrderType.LIMIT, price=88.0),
        order(
            index,
            1,
            "expires",
            order_type=OrderType.LIMIT,
            price=80.0,
            tif=TimeInForce.GTD,
            expires_at=index[3],
        ),
        order(
            index,
            1,
            "waiting",
            order_type=OrderType.LIMIT,
            price=85.0,
            parent_order_id="missing-parent",
            activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
        ),
        action(
            index, 2, "amend", OrderAction.AMEND, target_order_id="amended", price=99.5
        ),
        action(index, 2, "cancel", OrderAction.CANCEL, target_order_id="canceled"),
        order(
            index,
            2,
            "replacement",
            action=OrderAction.REPLACE,
            target_order_id="replaced",
            order_type=OrderType.LIMIT,
            price=100.0,
        ),
        action(
            index,
            2,
            "unknown-target",
            OrderAction.CANCEL,
            target_order_id="missing-target",
        ),
        action(index, 4, "clear", OrderAction.CANCEL_ALL, symbol="X"),
    )
    actual = run_executor(packed, commands, incremental=True)
    assert_audit(actual, reference_audit(packed, commands))
    assert decoded(actual, "fill_order_id") == ("amended", "replacement")
    assert {"amended", "canceled", "replaced", "missing-target"}.issubset(
        set(decoded(actual, "event_target_id"))
    )
    assert np.any(actual.event_reject_code != 0)


@requires_transaction
def test_delayed_stop_amendment_keeps_original_parent_and_oco_owner(prepared):
    packed = prepared()
    index = packed.index
    commands = (
        (order(index, 1, "entry"),)
        + bracket(index, 1, "entry", price=100.0)
        + (
            action(
                index,
                2,
                "tighten",
                OrderAction.AMEND,
                target_order_id="stop",
                trigger_price=100.0,
            ),
        )
    )
    actual = run_executor(packed, commands, incremental=True)
    assert_audit(actual, reference_audit(packed, commands))
    assert decoded(actual, "fill_order_id") == ("entry", "stop")
    assert actual.fill_bar[-1] == 2
    assert "tp" in decoded(actual, "event_order_id")


@requires_transaction
@pytest.mark.parametrize("case", ["funding", "margin-reject", "liquidation"])
def test_funding_margin_and_liquidation_paths_are_engine_owned(prepared, case):
    frame = market()
    if case == "funding":
        frame.loc[frame.index[8], "funding"] = 0.001
        packed = prepared(frame, funding=True)
        qty = 10.0
    elif case == "margin-reject":
        packed = prepared(frame, capital=100.0, leverage=2.0)
        qty = 10.0
    else:
        frame.loc[frame.index[3], "low"] = 70.0
        packed = prepared(frame, capital=100.0, leverage=10.0)
        qty = 9.0
    commands = (order(packed.index, 1, "entry", qty=qty),)
    actual = run_executor(packed, commands, incremental=True)
    assert_audit(actual, reference_audit(packed, commands))
    if case == "funding":
        assert actual.funding[8] != 0.0
        assert actual.initial_margin[1] > 0.0 and actual.maintenance_margin[1] > 0.0
    elif case == "margin-reject":
        assert not len(actual.fill_bar) and np.any(actual.event_reject_code != 0)
    else:
        assert actual.liquidated and actual.liquidation_bar == 3


@requires_transaction
@pytest.mark.parametrize(
    "invalid", ["reverse", "duplicate", "changed-past", "removed-past", "new-past"]
)
def test_executor_rejects_invalid_chronology_or_committed_command_rewrites(
    prepared, invalid
):
    packed = prepared()
    index = packed.index
    entry = order(index, 1, "entry")
    future = order(index, 4, "future", order_type=OrderType.LIMIT, price=90.0)
    commands = (entry, future)
    executor = TransactionalTapeFeedback(packed, index=index, start=0, symbol="X")
    try:
        for bar in range(2):
            executor.begin_bar(bar, commands)
            executor(commands)
            executor.commit_bar(bar)
        executor.begin_bar(2, commands)
        candidates = {
            "reverse": (future, entry),
            "duplicate": (entry, entry),
            "changed-past": (replace(entry, qty=2.0), future),
            "removed-past": (future,),
            "new-past": (entry, order(index, 1, "inserted-past"), future),
        }
        with pytest.raises(
            (ValueError, AssertionError),
            match="chronological|unique explicit|committed command",
        ):
            executor(candidates[invalid])
    finally:
        executor.close()


@requires_transaction
def test_executor_lifecycle_rejects_skips_nested_transactions_and_unfinished_audit(
    prepared,
):
    packed = prepared()
    executor = TransactionalTapeFeedback(
        packed, index=packed.index, start=20, symbol="X"
    )
    try:
        with pytest.raises(ValueError, match="active"):
            executor(())
        with pytest.raises(ValueError):
            executor.commit_bar(20)
        with pytest.raises(ValueError):
            executor.audit()
        with pytest.raises(ValueError):
            executor.begin_bar(21, ())
        executor.begin_bar(20, ())
        with pytest.raises(ValueError):
            executor.begin_bar(20, ())
        with pytest.raises(ValueError):
            executor.commit_bar(21)
        with pytest.raises(ValueError):
            executor.audit()
        executor.commit_bar(20)
        with pytest.raises(ValueError):
            executor.commit_bar(20)
        with pytest.raises(ValueError):
            executor.begin_bar(20, ())
    finally:
        executor.close()
    executor.close()
    with pytest.raises(ValueError):
        executor.begin_bar(21, ())
    with pytest.raises(ValueError):
        executor(())


@requires_transaction
def test_exported_audit_stays_read_only_and_detached_after_close(prepared):
    packed = prepared()
    commands = (order(packed.index, 1, "entry"),)
    actual = run_executor(packed, commands)
    assert_audit(actual, reference_audit(packed, commands))
    saved = actual.equity.copy()
    for field in PATHS + EVENTS + FILLS:
        assert not getattr(actual, field).flags.writeable
        if getattr(actual, field).size:
            with pytest.raises(ValueError):
                getattr(actual, field).flat[0] = -999.0
    run_executor(packed, ())
    np.testing.assert_array_equal(actual.equity, saved)


def bar_arrays(packed, commands, bar):
    ptr, codes, values, expiry, _ = packed.pack(tuple(commands))
    start, stop = (
        (int(ptr[1]), int(ptr[1])) if bar == 0 else (int(ptr[bar]), int(ptr[bar + 1]))
    )
    return codes[start:stop], values[start:stop], expiry[start:stop]


def step_snapshot(step):
    fields = (
        (
            "equity",
            "positions",
            "fee",
            "funding",
            "turnover",
            "initial_margin",
            "maintenance_margin",
        )
        + TERMINAL
        + EVENTS[1:]
        + FILLS[1:]
    )
    return {field: np.asarray(getattr(step, field)).copy() for field in fields}


def assert_step(actual, expected):
    left, right = step_snapshot(actual), step_snapshot(expected)
    for field in left:
        np.testing.assert_array_equal(left[field], right[field], err_msg=field)
    for field in EVENTS[1:] + FILLS[1:]:
        values = getattr(actual, field)
        kind = (float, np.floating) if field in FLOAT_FIELDS else (int, np.integer)
        assert all(
            isinstance(value, kind) and not isinstance(value, (bool, np.bool_))
            for value in values
        ), field


@requires_transaction
def test_native_retry_restores_live_orders_fills_and_account_before_reprocessing(
    prepared,
):
    frame = market()
    frame.loc[frame.index[2], ["high", "low"]] = [105.0, 95.0]
    packed = prepared(frame)
    index = packed.index
    factory = packed.runner._module.NativeFeedbackSessionCore
    candidate = factory.from_template(packed.runner._typed_template)
    clean = factory.from_template(packed.runner._typed_template)
    # Keep the parent pending until bar 2; protections are attached in its
    # actual fill bar, not a later bar after terminal parent removal.
    commands = (order(index, 1, "entry", order_type=OrderType.LIMIT, price=98.0),)
    complete = commands + bracket(index, 2, "entry", price=98.0)
    try:
        for bar in range(len(index)):
            candidate.begin(bar)
            clean.begin(bar)
            if bar == 2:
                candidate.step(*bar_arrays(packed, commands, bar))
            actual = candidate.step(*bar_arrays(packed, complete, bar))
            expected = clean.step(*bar_arrays(packed, complete, bar))
            assert_step(actual, expected)
            if bar == 2:
                assert len(actual.fill_order_id) == 2
                snapshot = step_snapshot(actual)
                repeated = candidate.step(*bar_arrays(packed, complete, bar))
                assert_step(repeated, expected)
                for field, value in snapshot.items():
                    np.testing.assert_array_equal(
                        getattr(actual, field), value, err_msg=field
                    )
            candidate.commit()
            clean.commit()
            assert candidate.next_bar == clean.next_bar == bar + 1
    finally:
        candidate.close()
        clean.close()


@requires_transaction
def test_native_abort_discards_fills_and_reset_discards_active_checkpoint(prepared):
    packed = prepared()
    factory = packed.runner._module.NativeFeedbackSessionCore
    candidate = factory.from_template(packed.runner._typed_template)
    clean = factory.from_template(packed.runner._typed_template)
    entry = (order(packed.index, 1, "entry"),)
    try:
        for session in (candidate, clean):
            session.begin(0)
            session.step(*bar_arrays(packed, (), 0))
            session.commit()
        candidate.begin(1)
        filled = candidate.step(*bar_arrays(packed, entry, 1))
        assert len(filled.fill_order_id) == 1
        candidate.abort()
        assert candidate.next_bar == 1
        for session in (candidate, clean):
            session.begin(1)
        actual = candidate.step(*bar_arrays(packed, (), 1))
        expected = clean.step(*bar_arrays(packed, (), 1))
        assert_step(actual, expected)
        candidate.reset()
        clean.reset()
        assert candidate.next_bar == clean.next_bar == 0
        for bar in range(3):
            for session in (candidate, clean):
                session.begin(bar)
            actual = candidate.step(*bar_arrays(packed, entry, bar))
            expected = clean.step(*bar_arrays(packed, entry, bar))
            assert_step(actual, expected)
            candidate.commit()
            clean.commit()
    finally:
        candidate.close()
        clean.close()


@requires_transaction
@pytest.mark.parametrize(
    "invalid",
    ["step", "commit", "abort", "skip", "nested", "unstepped-commit", "stale"],
)
def test_native_invalid_transaction_lifecycle_fails_closed(prepared, invalid):
    packed = prepared()
    session = packed.runner._module.NativeFeedbackSessionCore.from_template(
        packed.runner._typed_template
    )
    try:
        if invalid in {"nested", "unstepped-commit", "stale"}:
            session.begin(0)
        if invalid == "stale":
            session.step(*bar_arrays(packed, (), 0))
            session.commit()
        operations = {
            "step": lambda: session.step(*bar_arrays(packed, (), 0)),
            "commit": session.commit,
            "abort": session.abort,
            "skip": lambda: session.begin(1),
            "nested": lambda: session.begin(0),
            "unstepped-commit": session.commit,
            "stale": lambda: session.begin(0),
        }
        with pytest.raises(TRANSACTION_ERRORS):
            operations[invalid]()
    finally:
        session.close()


@requires_transaction
@pytest.mark.parametrize("invalid", ["codes", "values", "expiry"])
def test_native_malformed_step_can_abort_without_poisoning_session(prepared, invalid):
    packed = prepared()
    session = packed.runner._module.NativeFeedbackSessionCore.from_template(
        packed.runner._typed_template
    )
    try:
        session.begin(0)
        arrays = [
            np.empty((0, 16), dtype=np.int64),
            np.empty((0, 3), dtype=np.float64),
            np.empty(0, dtype=np.int64),
        ]
        if invalid == "codes":
            arrays[0] = np.empty((0, 15), dtype=np.int64)
        elif invalid == "values":
            arrays[1] = np.empty((0, 2), dtype=np.float64)
        else:
            arrays[2] = np.zeros(1, dtype=np.int64)
        with pytest.raises(TRANSACTION_ERRORS):
            session.step(*arrays)
        session.abort()
        assert session.next_bar == 0
        session.begin(0)
        session.step(*bar_arrays(packed, (), 0))
        session.commit()
        assert session.next_bar == 1
    finally:
        session.close()


@requires_transaction
def test_native_close_discards_active_transaction_and_cannot_be_reset(prepared):
    packed = prepared()
    session = packed.runner._module.NativeFeedbackSessionCore.from_template(
        packed.runner._typed_template
    )
    try:
        session.begin(0)
        session.step(*bar_arrays(packed, (), 0))
    finally:
        session.close()
    session.close()
    for operation in (
        lambda: session.begin(0),
        session.commit,
        session.abort,
        session.reset,
        lambda: session.step(*bar_arrays(packed, (), 0)),
    ):
        with pytest.raises(TRANSACTION_ERRORS):
            operation()


class ActualFillBracketBinding:
    def __init__(self, index):
        self.index, self.start, self.stop = index, 0, len(index)
        self.rows, self.position, self.seen = (), 0.0, ()

    def snapshot(self):
        return deepcopy((self.rows, self.position, self.seen))

    def restore(self, snapshot):
        self.rows, self.position, self.seen = deepcopy(snapshot)

    def advance(self, bar, events):
        for event in events:
            if event.kind != "fill":
                continue
            self.position += event.fill.qty * event.fill.side.sign
            self.seen += (event.order_id,)
            if event.order_id == "entry":
                self.rows += bracket(self.index, bar, "entry", price=event.fill.price)
        if bar == 0:
            self.rows += (order(self.index, 1, "entry"),)

    def commands(self):
        return self.rows


@requires_transaction
def test_compiler_transactions_match_replay_decisions_actual_fill_state_and_final_audit(
    prepared,
):
    frame = market()
    frame.loc[frame.index[1], "high"] = 105.0
    packed = prepared(frame)
    index = packed.index
    original, candidate = (
        ActualFillBracketBinding(index),
        ActualFillBracketBinding(index),
    )

    def replay(commands):
        return LazyEngineFeedback(
            reference_audit(packed, commands), commands, index, 0, "X"
        )

    reference = IncrementalFeedbackCompiler(original, replay)
    reference.run()
    executor = TransactionalTapeFeedback(packed, index=index, start=0, symbol="X")
    try:
        compiler = IncrementalFeedbackCompiler(candidate, executor)
        compiler.run()
        assert candidate.commands() == original.commands()
        assert candidate.position == original.position == 0.0
        assert candidate.seen == original.seen == ("entry", "tp")
        assert compiler.bar_retries == reference.bar_retries
        assert_audit(executor.audit(), reference_audit(packed, original.commands()))
        assert executor.transactions == len(index)
        assert executor.full_tape_executions == 0
        assert executor.same_bar_steps >= 1
    finally:
        executor.close()


@requires_transaction
@pytest.mark.parametrize(
    "kind,tif",
    (
        (OrderType.STOP_LIMIT, TimeInForce.GTC),
        (OrderType.LIMIT, TimeInForce.IOC),
        (OrderType.LIMIT, TimeInForce.FOK),
    ),
)
@pytest.mark.parametrize("side", (OrderSide.BUY, OrderSide.SELL))
def test_trigger_and_time_in_force_state_match_static_account(
    prepared, kind, tif, side
):
    frame = market()
    frame.loc[frame.index[2], ["high", "low"]] = [105.0, 95.0]
    packed = prepared(frame)
    kwargs = dict(
        order_type=kind,
        tif=tif,
        side=side,
        price=102.0 if side == OrderSide.BUY else 98.0,
    )
    if kind == OrderType.STOP_LIMIT:
        kwargs["trigger_price"] = 103.0 if side == OrderSide.BUY else 97.0
    commands = (order(packed.index, 1, "trigger-or-tif", **kwargs),)
    assert_audit(run_executor(packed, commands), reference_audit(packed, commands))


@requires_transaction
def test_native_feedback_ids_never_round_through_float_rows(prepared):
    packed = prepared()
    session = packed.runner._module.NativeFeedbackSessionCore.from_template(
        packed.runner._typed_template
    )
    try:
        session.begin(0)
        session.step(*bar_arrays(packed, (), 0))
        session.commit()
        codes, values, expiry = bar_arrays(
            packed, (order(packed.index, 1, "opaque"),), 1
        )
        codes = codes.copy()
        opaque = 2**53 + 3
        codes[:, 6] = opaque
        session.begin(1)
        first = session.step(codes, values, expiry)
        second = session.step(codes, values, expiry)
        assert first.fill_order_id == second.fill_order_id == [opaque]
        assert type(first.fill_order_id[0]) is int
        session.commit()
    finally:
        session.close()


def test_foreign_prefix_certificate_does_not_authorize_changed_account():
    from tools.mode5_research.feedback_prefix import CommittedFeedbackPrefix

    certificate = CommittedFeedbackPrefix(1, (b"same claimed data",))
    before = SimpleNamespace(
        paths={"equity": np.array([100.0])},
        prefix_certificate=lambda bar: certificate,
        events_before=lambda bar: (),
    )
    after = SimpleNamespace(
        paths={"equity": np.array([80.0])},
        prefix_certificate=lambda bar: certificate,
        events_before=lambda bar: (),
    )
    with pytest.raises(AssertionError, match="committed account prefix"):
        IncrementalFeedbackCompiler._prefix_unchanged(before, after, 1)


@requires_transaction
def test_native_prefix_certificate_is_exact_owned_and_keeps_full_fallback(prepared):
    from tools.mode5_research.feedback_prefix import CommittedFeedbackPrefix

    packed = prepared()
    executor = TransactionalTapeFeedback(
        packed, index=packed.index, start=0, symbol="X"
    )
    try:
        first = executor.begin_bar(0, ())
        executor.commit_bar(0)
        second = executor.begin_bar(1, ())
        assert first.prefix_certificate(1) is second.prefix_certificate(1)
        assert first.prefix_certificate(1).stop == 1
        assert first.prefix_certificate(4) is None
        assert isinstance(first.prefix_after.payload[1], bytes)
        for array in executor.paths.values():
            with pytest.raises(ValueError):
                array.flat[0] = -1.0
            with pytest.raises(ValueError):
                array.setflags(write=True)
        with pytest.raises(TypeError):
            executor.paths["equity"] = np.zeros(len(packed.index))
        # The fast check must not allocate or scan dense account paths.
        del executor._path_cache
        executor._path_cache = None
        IncrementalFeedbackCompiler._prefix_unchanged(first, second, 1)
        assert executor._path_cache is None
        second.prefix_before = CommittedFeedbackPrefix(1, (b"foreign",))
        IncrementalFeedbackCompiler._prefix_unchanged(first, second, 1)
        assert executor._path_cache is not None  # Full comparison fallback.
        executor._path_cache = None
        second.prefix_before = CommittedFeedbackPrefix(2, (b"wrong stop",))
        IncrementalFeedbackCompiler._prefix_unchanged(first, second, 1)
        assert executor._path_cache is not None
    finally:
        executor.close()


@requires_transaction
@pytest.mark.parametrize("same_names", [False, True])
def test_native_compiler_cannot_splice_different_session_owners(prepared, same_names):
    packed_left, packed_right = prepared(), prepared()
    owners = [
        TransactionalTapeFeedback(packed, index=packed.index, start=0, symbol="X")
        for packed in (packed_left, packed_right)
    ]
    try:
        for slot, owner in enumerate(owners):
            name = "same" if same_names else f"different-{slot}"
            commands = (order(owner.index, 1, name),)
            owner.begin_bar(0, commands)
            owner.commit_bar(0)
            owner.begin_bar(1, commands)
            owner.commit_bar(1)
        with pytest.raises(AssertionError, match="native feedback owner changed"):
            IncrementalFeedbackCompiler._prefix_unchanged(
                owners[0].current, owners[1].current, 2
            )
    finally:
        for owner in owners:
            owner.close()
