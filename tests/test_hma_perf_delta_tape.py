"""Input-packing differentials only: no alpha, account execution or optimizer."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    NativeEventBackend,
    NativeEventConfig,
    OrderAction,
    OrderActivationPolicy,
    OrderCommand,
    OrderSide,
    OrderType,
    TimeInForce,
)
from quantbt.backends._native_event_rust import compile_rust_full_tape
from quantbt.core.constraints import build_quantity_constraints
from tools.mode5_research.delta_feedback_tape import DeltaTapeRows
from tools.mode5_research.prepared_feedback import CachedTapeRows


@pytest.fixture
def tape():
    index = pd.date_range("2024-01-01", periods=32, freq="h", tz="UTC")
    backend = NativeEventBackend(
        NativeEventConfig(account=AccountConfig(initial_capital=20_000.0))
    )
    runner = SimpleNamespace(
        market_arrays=SimpleNamespace(closes=np.full((len(index), 1), 100.0)),
        contract_sizes=np.ones(1),
    )
    constraints = build_quantity_constraints(["X"], qty_step=0.01, min_qty=0.01)
    return SimpleNamespace(
        index=index,
        backend=backend,
        runner=runner,
        constraints=constraints,
        delta=DeltaTapeRows(backend, runner, index, "X", constraints),
        reference=CachedTapeRows(backend, runner, index, "X", constraints),
    )


def order(tape, bar, name, **overrides):
    fields = dict(
        timestamp=tape.index[bar],
        symbol="X",
        side=OrderSide.BUY,
        qty=1.234,
        order_type=OrderType.LIMIT,
        price=100.0,
        order_id=name,
    )
    fields.update(overrides)
    return OrderCommand(**fields)


def action(tape, bar, name, kind, **kwargs):
    return OrderCommand(timestamp=tape.index[bar], order_id=name, action=kind, **kwargs)


def compare(tape, commands, bar):
    actual = tape.delta.pack_bar(commands, bar)
    ptr, codes, values, expiry, ids = tape.reference.pack(commands)
    start = int(ptr[bar])
    stop = start if bar == 0 else int(ptr[bar + 1])
    for left, right in zip(actual, (codes[start:stop], values[start:stop], expiry[start:stop])):
        assert left.dtype == right.dtype
        assert left.shape == right.shape
        assert left.tobytes() == right.tobytes()
        assert left.flags.c_contiguous and not left.flags.writeable
    assert tape.delta.id_namespace == ids
    assert dict(tape.delta.command_map) == {command.order_id: command for command in commands}
    return actual


def test_append_slices_equal_full_original_pack_and_global_ordinals(tape):
    commands = ()
    for bar in range(len(tape.index)):
        additions = tuple(order(tape, bar, f"entry-{bar}-{i}") for i in range(bar % 4))
        commands += additions
        actual = compare(tape, commands, bar)
        if bar and additions:
            assert tuple(actual[0][:, 12]) == tuple(range(len(commands) - len(additions), len(commands)))
        compare(tape, commands, bar)
    assert tape.delta.compiled_rows == len(commands)
    assert tape.delta.counters["original_compiler_calls"] == 24
    assert tape.delta.counters["full_tape_gathers"] == 0
    assert tape.delta.counters["sequence_rows_copied"] == 0


def test_current_bar_add_amend_cancel_replace_parent_oco_and_expiry(tape):
    entry = order(tape, 1, "entry")
    common = dict(
        side=OrderSide.SELL,
        parent_order_id="entry",
        oco_group_id="pair",
        group_id="campaign",
        activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
        reduce_only=True,
    )
    stop = order(tape, 1, "stop", order_type=OrderType.STOP_MARKET, trigger_price=95.0, **common)
    limit = order(tape, 1, "limit", price=105.0, expires_at=tape.index[7], tif=TimeInForce.GTD, **common)
    amend = action(tape, 1, "amend", OrderAction.AMEND, target_order_id="limit", price=106.0)
    cancel = action(tape, 1, "cancel", OrderAction.CANCEL, target_order_id="stop")
    replacement = order(tape, 1, "replacement", action=OrderAction.REPLACE, target_order_id="limit")
    cancel_all = action(tape, 1, "cancel-all", OrderAction.CANCEL_ALL, symbol="X")
    commands = (entry, stop, limit, amend, cancel, replacement, cancel_all)
    compare(tape, (), 0)
    for stop in range(1, len(commands) + 1):
        compare(tape, commands[:stop], 1)
    assert tape.delta.compiled_rows == len(commands)
    # Compare directly against an uncached original compiler as well.
    effective, _ = tape.backend._apply_command_quantity_constraints(
        idx=tape.index, commands=commands, closes=tape.runner.market_arrays.closes,
        symbol_list=["X"], contract_sizes=tape.runner.contract_sizes, constraints=tape.constraints,
    )
    compiled = tape.backend.compile_order_commands(tape.index, effective, symbols=["X"])
    _, original_codes, original_values, original_expiry = compile_rust_full_tape(compiled)
    codes, values, expiry = compare(tape, commands, 1)
    np.testing.assert_array_equal(values, original_values)
    np.testing.assert_array_equal(expiry, original_expiry)
    for col in (6, 7, 8, 9, 10):
        decode = lambda rows, names: tuple(None if value < 0 else names[value] for value in rows[:, col])
        assert decode(codes, tape.delta.id_namespace) == decode(original_codes, compiled.id_values)
    assert values[0, 0] == 1.23


def test_same_bar_rollback_reorder_and_restored_suffix(tape):
    entry = order(tape, 1, "entry")
    future = order(tape, 3, "future", target_order_id="outside-namespace")
    initial = (entry, future)
    compare(tape, (), 0)
    compare(tape, initial, 1)
    namespace = tape.delta.id_namespace
    compare(tape, (), 1)
    assert tape.delta.id_namespace == namespace
    compare(tape, initial, 1)
    assert tape.delta.compiled_rows == 2
    compare(tape, initial, 2)
    other = order(tape, 3, "other")
    selected = (entry, future, other)
    compare(tape, selected, 3)
    compare(tape, (entry, other, future), 3)
    compare(tape, (entry, other), 3)
    compare(tape, selected, 3)
    assert tape.delta.compiled_rows == 3


def test_changed_current_row_recompiles_only_changed_row(tape):
    commands = tuple(order(tape, 1, f"entry-{i}") for i in range(20))
    compare(tape, (), 0)
    compare(tape, commands, 1)
    changed = commands[:10] + (replace(commands[10], price=110.0),) + commands[11:]
    compare(tape, changed, 1)
    assert tape.delta.compiled_rows == 21
    compare(tape, commands, 1)
    assert tape.delta.compiled_rows == 22
    compare(tape, tuple(replace(command) for command in commands), 1)
    assert tape.delta.compiled_rows == 22


@pytest.mark.parametrize("kind", ["edit", "drop", "reorder", "late-add", "retime"])
def test_committed_prefix_is_exact_and_bad_update_does_not_poison_retry(tape, kind):
    a, b = order(tape, 1, "a"), order(tape, 1, "b")
    future = order(tape, 4, "future")
    commands = (a, b, future)
    compare(tape, (), 0)
    compare(tape, commands, 1)
    compare(tape, commands, 2)
    variants = {
        "edit": (replace(a, qty=2.0), b, future),
        "drop": (b, future),
        "reorder": (b, a, future),
        "late-add": (a, b, order(tape, 1, "late"), future),
        "retime": (a, b, replace(future, timestamp=tape.index[1])),
    }
    namespace = tape.delta.id_namespace
    rows = tape.delta.compiled_rows
    with pytest.raises(ValueError, match="committed"):
        tape.delta.pack_bar(variants[kind], 2)
    assert tape.delta.id_namespace == namespace
    assert tape.delta.compiled_rows == rows
    compare(tape, commands, 2)


def test_stable_chronology_error_cannot_silently_sort_or_poison_namespace(tape):
    compare(tape, (), 0)
    a, b = order(tape, 2, "later"), order(tape, 1, "earlier")
    with pytest.raises(ValueError, match="chronological"):
        tape.delta.pack_bar((a, b), 1)
    assert tape.delta.id_namespace == ()
    assert tape.delta.compiled_rows == 0
    compare(tape, (b, a), 1)


@pytest.mark.parametrize("duplicate_prefix", [False, True])
def test_duplicate_ids_fail_before_compiler_without_prefix_copy(tape, duplicate_prefix):
    a = order(tape, 1, "a")
    b = replace(a, price=101.0)
    compare(tape, (), 0)
    if duplicate_prefix:
        compare(tape, (a,), 1)
    calls = tape.delta.counters["original_compiler_calls"]
    with pytest.raises(ValueError, match="unique explicit"):
        tape.delta.pack_bar((a, b), 1)
    assert tape.delta.counters["original_compiler_calls"] == calls


@pytest.mark.parametrize("name", [None, "", 123])
def test_explicit_original_string_ids_required(tape, name):
    compare(tape, (), 0)
    with pytest.raises(ValueError, match="explicit string"):
        tape.delta.pack_bar((order(tape, 1, name),), 1)


def test_unchanged_tuple_avoids_source_scans_and_all_numeric_history_gathers(tape):
    commands = tuple(order(tape, 1, f"name-{i}") for i in range(100))
    compare(tape, (), 0)
    compare(tape, commands, 1)
    before = dict(tape.delta.counters)
    for bar in range(2, 32):
        codes, values, expiry = tape.delta.pack_bar(commands, bar)
        assert codes.shape == (0, 16) and values.shape == (0, 3) and expiry.shape == (0,)
    after = dict(tape.delta.counters)
    assert after["source_rows_checked"] == before["source_rows_checked"]
    assert after["original_compiler_calls"] == before["original_compiler_calls"]
    assert after["identical_tuple_calls"] - before["identical_tuple_calls"] == 30
    assert after["full_tape_gathers"] == 0


def test_equal_new_tuple_requires_exact_row_checks_not_only_length(tape):
    commands = tuple(order(tape, 1, f"name-{i}") for i in range(10))
    compare(tape, (), 0)
    compare(tape, commands, 1)
    before = tape.delta.counters["source_rows_checked"]
    compare(tape, tuple(replace(command) for command in commands), 2)
    assert tape.delta.counters["source_rows_checked"] - before == len(commands)
    assert tape.delta.compiled_rows == len(commands)


def test_returned_buffers_and_public_maps_cannot_mutate_cached_rows(tape):
    commands = (order(tape, 1, "entry"),)
    compare(tape, (), 0)
    outputs = compare(tape, commands, 1)
    copies = tuple(array.tobytes() for array in outputs)
    for array in outputs:
        with pytest.raises(ValueError):
            array.setflags(write=True)
    with pytest.raises(TypeError):
        tape.delta.command_map["entry"] = None
    with pytest.raises(TypeError):
        tape.delta.counters["compiled_rows"] = 100
    compare(tape, (replace(commands[0], price=999.0),), 1)
    assert tuple(array.tobytes() for array in outputs) == copies


def test_next_open_timestamp_stays_on_activation_bar_without_double_shift(tape):
    next_open = order(tape, 2, "activation")
    compare(tape, (next_open,), 0)
    assert compare(tape, (next_open,), 1)[0].shape == (0, 16)
    assert compare(tape, (next_open,), 2)[0].shape == (1, 16)


def test_bar_zero_empty_policy_does_not_skip_preflight_or_compiler_errors(tape):
    at_zero = order(tape, 0, "at-zero")
    assert compare(tape, (at_zero,), 0)[0].shape == (0, 16)
    with pytest.raises(ValueError, match="committed"):
        tape.delta.pack_bar((), 1)
    tape.delta.reset()
    with pytest.raises(ValueError, match="dropped quantity"):
        tape.delta.pack_bar((replace(at_zero, qty=0.001),), 0)
    assert tape.delta.id_namespace == ()
    with pytest.raises(ValueError, match="after the available data"):
        tape.delta.pack_bar((replace(at_zero, timestamp=tape.index[-1] + pd.Timedelta(hours=1)),), 0)
    assert tape.delta.compiled_rows == 0


def test_symbol_constraint_error_is_not_bypassed(tape):
    with pytest.raises(ValueError, match="not in symbols"):
        tape.delta.pack_bar((order(tape, 0, "wrong-symbol", symbol="UNKNOWN"),), 0)


@pytest.mark.parametrize("bad", [-1, 32, True, 1.0, "1"])
def test_invalid_bar_and_uninitialized_nonzero_fail_without_rows(tape, bad):
    with pytest.raises((ValueError, TypeError)):
        tape.delta.pack_bar((), bad)
    assert tape.delta.compiled_rows == 0
    with pytest.raises(ValueError, match="start at local bar zero"):
        tape.delta.pack_bar((), 1)


def test_lists_are_detached_and_backward_requires_explicit_new_session_reset(tape):
    commands = [order(tape, 1, "entry")]
    compare(tape, (), 0)
    tape.delta.pack_bar(commands, 1)
    commands.clear()
    assert "entry" in tape.delta.command_map
    with pytest.raises(ValueError, match="committed"):
        tape.delta.pack_bar(commands, 2)
    tape.delta.pack_bar(tuple(tape.delta.command_map.values()), 2)
    with pytest.raises(ValueError, match="backward"):
        tape.delta.pack_bar((), 1)
    tape.delta.reset()
    assert tape.delta.id_namespace == () and tape.delta.compiled_rows == 0
    assert not tape.delta.command_map and tape.delta.counters["pack_calls"] == 0
    tape.reference = CachedTapeRows(tape.backend, tape.runner, tape.index, "X", tape.constraints)
    compare(tape, (), 0)
    compare(tape, (order(tape, 1, "entry"),), 1)


def test_independent_owners_share_no_mutable_slots_or_id_lifetimes(tape):
    other = DeltaTapeRows(tape.backend, tape.runner, tape.index, "X", tape.constraints)
    tape.delta.pack_bar((order(tape, 0, "left"),), 0)
    other.pack_bar((order(tape, 0, "right"),), 0)
    assert tape.delta.id_namespace == ("left",)
    assert other.id_namespace == ("right",)
    tape.delta.reset()
    assert other.compiled_rows == 1 and other.id_namespace == ("right",)


def test_nan_and_equality_errors_retain_existing_compiler_behavior(tape):
    command = order(tape, 1, "nan", price=float("nan"))
    compare(tape, (), 0)
    compare(tape, (command,), 1)
    compare(tape, (command,), 1)
    assert tape.delta.compiled_rows == 1
    left = order(tape, 1, "array-meta", metadata={"array": np.array([1, 2])})
    right = replace(left, metadata={"array": np.array([1, 2])})
    compare(tape, (command, left), 1)
    with pytest.raises(ValueError, match="truth value"):
        tape.delta.pack_bar((command, right), 1)
    compare(tape, (command, left), 1)


def test_future_change_and_speculative_rollback_keep_namespace_and_ordinals(tape):
    entry = order(tape, 1, "entry")
    future = order(tape, 4, "future", parent_order_id="parent")
    compare(tape, (), 0)
    compare(tape, (entry, future), 1)
    speculative = order(tape, 2, "speculative", parent_order_id="speculative-parent")
    compare(tape, (entry, speculative), 1)
    compare(tape, (entry, future), 1)
    changed = replace(future, parent_order_id="new-parent", expires_at=tape.index[10])
    compare(tape, (entry, changed), 2)
    compare(tape, (entry, changed), 3)
    codes, _, expiry = compare(tape, (entry, changed), 4)
    assert codes[0, 12] == 1 and expiry[0] == 10
    assert tape.delta.id_namespace == (
        "entry", "future", "parent", "speculative", "speculative-parent", "new-parent"
    )


def test_unsupported_tif_and_noncanonical_commands_fail_closed(tape):
    with pytest.raises(NotImplementedError, match="unsupported tif"):
        tape.delta.pack_bar((order(tape, 0, "bad-tif", tif="unsupported"),), 0)
    assert tape.delta.id_namespace == () and tape.delta.compiled_rows == 0
    with pytest.raises(TypeError, match="frozen OrderCommand"):
        tape.delta.pack_bar((SimpleNamespace(order_id="not-a-command"),), 0)
