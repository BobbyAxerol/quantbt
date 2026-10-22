"""Callback-only differential checks; no financial engine execution."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from quantbt.wfo_execution import WfoExecutionWindow, _FoldCallbacks


@dataclass(frozen=True)
class Context:
    timestamp: object
    bar_index: int = 999


class ReferenceCallbacks:
    """Frozen pre-cursor dispatch contract, independent of the optimized lookup."""

    def __init__(self, window):
        self.parts = window.parts or (window,)
        self.current = self.child = None

    def on_bar_close(self, context):
        part = next((p for p in self.parts if p.index[0] <= context.timestamp <= p.index[-1]), None)
        if part is None:
            return ()
        local = replace(context, bar_index=int(part.index.get_loc(context.timestamp)))
        if part is not self.current:
            self.current, self.child = part, part.strategy_factory()
            if not callable(getattr(self.child, "on_bar_close", None)):
                raise TypeError("strategy_factory must return the event_driven callback protocol")
            initial = getattr(self.child, "initialize", lambda c: ())(local)
            return tuple(initial or ()) + tuple(self.child.on_bar_close(local) or ())
        return self.child.on_bar_close(local)

    def finalize(self, context):
        if self.child is None:
            return ()
        local = replace(context, bar_index=int(self.current.index.get_indexer([context.timestamp])[0]))
        return getattr(self.child, "finalize", lambda c: ())(local)


def window(indexes, log, *, generic=False):
    def factory(label):
        def make():
            log.append((label, "new"))

            class Child:
                def initialize(self, context):
                    log.append((label, "initialize", context.bar_index, context.timestamp))
                    return ((label, "initial"),)

                def on_bar_close(self, context):
                    log.append((label, "close", context.bar_index, context.timestamp))
                    return ((label, context.bar_index),)

                def finalize(self, context):
                    log.append((label, "finalize", context.bar_index, context.timestamp))
                    return ((label, "final", context.bar_index),)

            return Child()
        return make

    kind = SimpleNamespace if generic else WfoExecutionWindow
    parts = tuple(kind(route="event_driven", index=index, strategy_factory=factory(i))
                  for i, index in enumerate(indexes))
    return SimpleNamespace(parts=parts)


def outcome(call):
    try:
        return ("returned", call())
    except Exception as error:
        return type(error), str(error)


@pytest.mark.parametrize("layout", ("ordinary", "overlap", "unsorted", "microseconds"))
def test_cursor_matches_reference_with_gaps_repeats_and_backwards_callbacks(layout):
    index = pd.date_range("2022-01-01", periods=13, freq="h", tz="UTC")
    indexes = [index[2:5], index[7:10]]
    if layout == "overlap":
        indexes = [index[2:8], index[5:10]]
    elif layout == "unsorted":
        indexes.reverse()
    elif layout == "microseconds":
        indexes = [part.as_unit("us") for part in indexes]
    actual_log, expected_log = [], []
    actual = _FoldCallbacks(window(indexes, actual_log))
    expected = ReferenceCallbacks(window(indexes, expected_log))
    assert actual.finalize(Context(index[0])) == expected.finalize(Context(index[0])) == ()
    sequence = [*index, index[8], index[8], index[2], index[4], index[7]]
    for timestamp in sequence:
        context = Context(timestamp)
        assert outcome(lambda: actual.on_bar_close(context)) == outcome(lambda: expected.on_bar_close(context))
        assert actual_log == expected_log
    for timestamp in (index[7], index[7], index[-1], index[0]):
        assert actual.finalize(Context(timestamp)) == expected.finalize(Context(timestamp))
        assert actual_log == expected_log


@pytest.mark.parametrize("timestamp", (
    pd.Timestamp("2022-01-01T02:30:00Z"),
    pd.Timestamp("2022-01-01T03:00:00Z"),
    pd.Timestamp("2022-01-01T02:00:00"),
    "2022-01-01T02:00:00Z", None, pd.NaT,
    datetime(2022, 1, 1, 2, tzinfo=timezone.utc),
    pd.Timestamp("2022-01-01T09:00:00+07:00"),
    pd.Timestamp("2500-01-01", tz="UTC"),
))
def test_timestamp_fallback_and_internal_calendar_holes_preserve_reference_failures(timestamp):
    index = pd.date_range("2022-01-01", periods=8, freq="h", tz="UTC")
    indexes = [index[[2, 4, 5]]]
    actual_log, expected_log = [], []
    actual = _FoldCallbacks(window(indexes, actual_log))
    expected = ReferenceCallbacks(window(indexes, expected_log))
    assert outcome(lambda: actual.on_bar_close(Context(timestamp))) == outcome(
        lambda: expected.on_bar_close(Context(timestamp)))
    assert actual_log == expected_log


def test_finalize_missing_timestamp_returns_original_minus_one_and_keeps_child():
    index = pd.date_range("2022-01-01", periods=6, freq="h", tz="UTC")
    log = []
    callbacks = _FoldCallbacks(window([index[[0, 2, 4]]], log))
    callbacks.on_bar_close(Context(index[0]))
    child = callbacks.child
    for timestamp in (index[1], index[-1], pd.Timestamp("2022-01-01")):
        assert callbacks.finalize(Context(timestamp)) == ((0, "final", -1),)
        assert callbacks.child is child


@pytest.mark.parametrize("index", (
    pd.DatetimeIndex(["2022-01-01T00:00Z", "2022-01-01T00:00Z", "2022-01-01T02:00Z"]),
    pd.DatetimeIndex(["2022-01-01T02:00Z", "2022-01-01T00:00Z", "2022-01-01T03:00Z"]),
))
def test_noncanonical_generic_parts_keep_original_lookup_behavior(index):
    actual_log, expected_log = [], []
    actual = _FoldCallbacks(window([index], actual_log, generic=True))
    expected = ReferenceCallbacks(window([index], expected_log, generic=True))
    for timestamp in index:
        assert outcome(lambda: actual.on_bar_close(Context(timestamp))) == outcome(
            lambda: expected.on_bar_close(Context(timestamp)))
        assert actual_log == expected_log


def test_valid_callbacks_and_finalize_do_not_use_pandas_scalar_or_list_lookup(monkeypatch):
    index = pd.date_range("2022-01-01", periods=20, freq="h", tz="UTC")
    log = []
    callbacks = _FoldCallbacks(window([index[3:9], index[12:18]], log))

    def forbidden(*args, **kwargs):
        raise AssertionError("hot pandas calendar lookup")

    monkeypatch.setattr(pd.DatetimeIndex, "get_loc", forbidden)
    monkeypatch.setattr(pd.DatetimeIndex, "get_indexer", forbidden)
    for offset in (0, 3, 3, 4, 8, 10, 12, 16, 17, 12, 5, 5):
        callbacks.on_bar_close(Context(index[offset], bar_index=-1000))
    assert callbacks.finalize(Context(index[5])) == ((0, "final", 2),)


def test_bad_factory_protocol_and_failed_initialize_keep_original_repeat_behavior():
    index = pd.date_range("2022-01-01", periods=2, freq="h", tz="UTC")
    for factory in (lambda: object(), lambda: None):
        part = WfoExecutionWindow("event_driven", index, strategy_factory=factory)
        actual, expected = _FoldCallbacks(part), ReferenceCallbacks(part)
        for _ in range(2):
            assert outcome(lambda: actual.on_bar_close(Context(index[0]))) == outcome(
                lambda: expected.on_bar_close(Context(index[0])))

    class Child:
        def initialize(self, context):
            raise RuntimeError("initialize failed")

        def on_bar_close(self, context):
            return (context.bar_index,)

    part = WfoExecutionWindow("event_driven", index, strategy_factory=Child)
    actual, expected = _FoldCallbacks(part), ReferenceCallbacks(part)
    for _ in range(2):
        assert outcome(lambda: actual.on_bar_close(Context(index[0]))) == outcome(
            lambda: expected.on_bar_close(Context(index[0])))
