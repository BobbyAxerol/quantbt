"""Exact ID-prefix/packing proofs; synthetic arrays and compilation, no finance."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from quantbt import AccountConfig, NativeEventBackend, NativeEventConfig
from quantbt import OrderCommand, OrderSide, OrderType
from quantbt.backends._native_event_rust import compile_rust_full_tape
from quantbt.core.constraints import build_quantity_constraints
from tools.mode5_research.incremental_feedback import IncrementalFeedbackCompiler
from tools.mode5_research.prepared_feedback import CachedTapeRows, LazyEngineFeedback


PATHS = ("equity", "positions", "fees", "funding", "turnover", "initial_margin", "maintenance_margin")
EVENTS = ("event_bar", "event_kind", "event_order_id", "event_target_id", "event_status", "event_symbol", "event_reject_code")
FILLS = ("fill_bar", "fill_order_id", "fill_symbol", "fill_side", "fill_qty", "fill_price", "fill_fee", "fill_reason", "fill_ambiguity", "fill_order_type")


def audit(size=8, names=("entry", "stop", "exit")):
    rows, fills = np.arange(size, dtype=np.int64), np.arange(size // 2, dtype=np.int64)
    result = SimpleNamespace(id_values=names, event_bar=rows.copy(), event_kind=rows % 8,
        event_order_id=rows % len(names), event_target_id=np.where(rows % 2, 0, -1),
        event_status=rows % 4, event_symbol=rows % 2, event_reject_code=rows % 3,
        fill_bar=fills.copy(), fill_order_id=fills % len(names), fill_symbol=fills % 2,
        fill_side=np.ones(len(fills), dtype=np.int64), fill_qty=fills.astype(float) + 1,
        fill_price=fills.astype(float) + 100, fill_fee=fills.astype(float) / 100,
        fill_reason=fills % 4, fill_ambiguity=fills % 2, fill_order_type=fills % 3)
    for name in PATHS:
        setattr(result, name, np.arange(size + 1, dtype=float))
    return result


def feedback(value=None, cls=LazyEngineFeedback):
    value = audit() if value is None else value
    return cls(value, (), np.arange(len(value.equity)), 100, "SYNTHETIC")


def check(left, right, bar=108):
    IncrementalFeedbackCompiler._prefix_unchanged(left, right, bar)


def test_shared_immutable_namespace_uses_codes_not_string_projection():
    left, right = feedback(), feedback()
    assert left.id_namespace == ("entry", "stop", "exit")
    with patch.object(left, "_names", wraps=left._names) as names:
        check(left, right)
    assert len(names.call_args_list) == 3
    assert all(c.kwargs == dict(encoded=True) for c in names.call_args_list)
    assert left.events_before(108) == right.events_before(108)


def test_append_growth_and_all_negative_sentinels_keep_prior_identity():
    left, right = feedback(), feedback()
    right.audit.id_values += ("future",)
    right = feedback(right.audit)
    right.audit.event_target_id[right.audit.event_target_id < 0] = -999
    check(left, right)
    right.audit.event_order_id[-1] = 3
    check(left, right, 107)
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)
    assert left.events_before(107) == right.events_before(107)


@pytest.mark.parametrize("dtype", [np.int8, np.int32, np.uint64, ">i8", float, object, bool])
def test_id_dtype_conversion_retains_original_decoding(dtype):
    left, right = feedback(), feedback()
    for name in ("event_order_id", "event_target_id", "fill_order_id"):
        values = np.maximum(getattr(right.audit, name), 0).astype(dtype)
        setattr(right.audit, name, values)
        setattr(left.audit, name, values.astype(np.int64))
    check(left, right)
    assert left.events_before(108) == right.events_before(108)


def test_reordered_namespace_falls_back_to_exact_names():
    left, value = feedback(), audit(names=("stop", "entry", "exit"))
    for name in ("event_order_id", "event_target_id", "fill_order_id"):
        codes = getattr(value, name)
        setattr(value, name, np.where(codes == 0, 1, np.where(codes == 1, 0, codes)))
    right = feedback(value)
    with patch.object(left, "_names", wraps=left._names) as names:
        check(left, right)
    assert all(c.kwargs == dict(encoded=False) for c in names.call_args_list)
    right.audit.event_order_id[0] = 0
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)


def test_mutable_mapping_object_identity_is_not_a_namespace_witness():
    names = ["entry", "stop", "exit"]
    left = feedback(audit(names=names))
    names[0] = "reassigned"
    right = feedback(audit(names=names))
    assert left.audit.id_values is right.audit.id_values
    assert left.id_namespace is right.id_namespace is None
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)


def test_mutated_id_array_invalidates_immutable_namespace_witness():
    left, right = feedback(), feedback()
    right.ids[0] = "changed"
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)
    left.ids[0] = "changed"
    check(left, right)


def test_duplicate_and_nonstring_names_keep_original_identity_semantics():
    for names in (("entry", "entry", "exit"), (1, 2, 3)):
        left, right = feedback(audit(names=names)), feedback(audit(names=names))
        assert left.id_namespace is right.id_namespace is None
        check(left, right)
    left, right = feedback(audit(names=("entry", "entry", "exit"))), feedback(audit(names=("entry", "entry", "exit")))
    right.audit.event_order_id[0] = 1
    check(left, right)


@pytest.mark.parametrize("field", EVENTS + FILLS)
def test_every_committed_event_and_fill_field_is_still_checked(field):
    left, right = feedback(), feedback()
    getattr(right.audit, field)[0] += 1
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)


@pytest.mark.parametrize("field", PATHS)
def test_every_account_prefix_path_is_still_checked(field):
    left, right = feedback(), feedback()
    getattr(right.audit, field)[0] += 1
    with pytest.raises(AssertionError, match="account"):
        check(left, right)


def test_original_nan_bytes_path_nan_and_stable_event_order():
    left, right = feedback(), feedback()
    left.audit.fill_price[0] = right.audit.fill_price[0] = np.nan
    check(left, right)
    right.audit.fill_price.view(np.uint64)[0] ^= np.uint64(1)
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)
    left, right = feedback(), feedback()
    for field in EVENTS:
        setattr(right.audit, field, getattr(right.audit, field)[::-1])
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)
    left, right = feedback(), feedback()
    left.audit.equity[0] = right.audit.equity[0] = np.nan
    with pytest.raises(AssertionError, match="account"):
        check(left, right)


def test_optional_liquidity_invalid_codes_and_generic_feedback_fallback():
    left, right = feedback(), feedback()
    left.audit.fill_order_type = right.audit.fill_order_type = None
    check(left, right)
    right.audit.fill_order_type = np.zeros(4, dtype=np.int64)
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, right)
    right.audit.event_order_id = right.audit.event_order_id.astype(np.uint64)
    right.audit.event_order_id[-1] = np.iinfo(np.uint64).max
    with pytest.raises(OverflowError):
        right.same_events_before(left, 108)
    right.audit.event_order_id[-1] = 3
    with pytest.raises(IndexError):
        right.same_events_before(left, 108)
    calls = []
    generic = SimpleNamespace(paths=left.paths, events_before=lambda bar: (calls.append(bar), "generic"))
    with pytest.raises(AssertionError, match="lifecycle"):
        check(left, generic)
    assert calls == [108]


def tape_fixture(count=12, cls=CachedTapeRows):
    index = pd.date_range("2020-01-01", periods=max(8, count), freq="h")
    backend = NativeEventBackend(NativeEventConfig(account=AccountConfig(initial_capital=20_000.)))
    runner = SimpleNamespace(market_arrays=SimpleNamespace(closes=np.full((len(index), 1), 100.)), contract_sizes=np.ones(1))
    constraints = build_quantity_constraints(["BTC"], qty_step=.01, min_qty=.01)
    cache = cls(backend, runner, index, "BTC", constraints)
    commands = tuple(OrderCommand(timestamp=index[i // 3], symbol="BTC", side=OrderSide.BUY,
        qty=1.234, order_type=OrderType.LIMIT, price=100. + i, order_id=f"order-{i}") for i in range(count))
    return cache, commands


def assert_tape(actual, expected):
    for a, b in zip(actual[:4], expected[:4]):
        assert a.dtype == b.dtype and a.shape == b.shape
    for field in (0, 2, 3):
        assert actual[field].tobytes() == expected[field].tobytes()
    ordinary = [i for i in range(16) if i not in (6, 7, 8, 9, 10)]
    np.testing.assert_array_equal(actual[1][:, ordinary], expected[1][:, ordinary])
    for column in (6, 7, 8, 9, 10):
        decode = lambda codes, names: tuple(None if code < 0 else names[code] for code in codes)
        assert decode(actual[1][:, column], actual[4]) == decode(expected[1][:, column], expected[4])


def original_pack(cache, commands):
    effective, _ = cache.backend._apply_command_quantity_constraints(idx=cache.index, commands=commands,
        closes=cache.runner.market_arrays.closes, symbol_list=[cache.symbol], contract_sizes=cache.runner.contract_sizes, constraints=cache.constraints)
    compiled = cache.backend.compile_order_commands(cache.index, effective, symbols=[cache.symbol])
    return (*compile_rust_full_tape(compiled), tuple(compiled.id_values))


def test_packing_scans_changes_rollbacks_removals_and_same_bar_reordering():
    cache, commands = tape_fixture()
    first = cache.pack(commands[:6])
    prior_names = first[4]
    assert type(prior_names) is tuple and cache.pack(commands[:6])[4] is prior_names
    sequences = [commands, commands[:3], commands[:1] + (replace(commands[1], price=999.),) + commands[2:],
                 (commands[2], commands[0], commands[1]) + commands[3:], commands[3:], (), commands]
    for selected in sequences:
        assert_tape(cache.pack(selected), original_pack(cache, selected))
    assert prior_names == first[4] and cache.id_namespace[:len(prior_names)] == prior_names
    assert_tape(first, original_pack(cache, commands[:6]))
    compiled = cache.compiled_rows
    cache.pack(tuple(replace(command) for command in commands))
    assert cache.compiled_rows == compiled
    with pytest.raises(ValueError, match="chronological"):
        cache.pack(commands[::-1])
    with pytest.raises(ValueError, match="unique explicit"):
        cache.pack((commands[0], commands[0]))


def test_packing_retains_nan_and_equality_error_behavior():
    cache, commands = tape_fixture()
    command = replace(commands[0], price=float("nan"))
    assert_tape(cache.pack((command,)), original_pack(cache, (command,)))
    calls = cache.compiled_rows
    cache.pack((command,))
    assert cache.compiled_rows == calls
    left = replace(commands[0], metadata={"array": np.array([1, 2])})
    right = replace(commands[0], metadata={"array": np.array([1, 2])})
    cache.pack((left,))
    with pytest.raises(ValueError, match="truth value"):
        cache.pack((right,))


def benchmark(reference_file, *, event_count=8000, repeats=100, command_count=1200, pack_repeats=200):
    """Explicit bounded old/new benchmark; not a timing-sensitive pytest gate."""
    import importlib.util
    from pathlib import Path
    from statistics import median
    from time import perf_counter

    def load(path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    reference_file = Path(reference_file)
    old = load(reference_file, "feedback_prefix_baseline")
    old_compiler = load(reference_file.with_name("incremental_feedback.py"), "incremental_prefix_baseline")
    timings = {}
    for label, feedback_class, compiler, cache_class in (
            ("old", old.LazyEngineFeedback, old_compiler.IncrementalFeedbackCompiler, old.CachedTapeRows),
            ("new", LazyEngineFeedback, IncrementalFeedbackCompiler, CachedTapeRows)):
        left, right = feedback(audit(event_count), feedback_class), feedback(audit(event_count), feedback_class)
        compiler._prefix_unchanged(left, right, 100 + event_count)
        samples = []
        for _ in range(3):
            start = perf_counter()
            for _ in range(repeats):
                compiler._prefix_unchanged(left, right, 100 + event_count)
            samples.append(perf_counter() - start)
        cache, commands = tape_fixture(command_count, cache_class)
        assert_tape(cache.pack(commands), original_pack(cache, commands))
        pack_samples = []
        for _ in range(3):
            start = perf_counter()
            for _ in range(pack_repeats):
                cache.pack(commands)
            pack_samples.append(perf_counter() - start)
        assert cache.compiled_rows == command_count
        timings[label] = dict(prefix_seconds=median(samples), pack_seconds=median(pack_samples),
                              prefix_samples=samples, pack_samples=pack_samples)
    return dict(events=event_count, fills=event_count // 2, prefix_checks_per_sample=repeats,
                commands=command_count, pack_calls_per_sample=pack_repeats,
                samples=3, financial_executions=0, timings=timings)
