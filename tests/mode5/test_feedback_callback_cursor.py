"""Callback plumbing only: synthetic fills, no alpha or financial account run."""

from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import OrderSide
from tools.mode5_admission.feedback import BarCloseBinding, UnsupportedFinancialBinding


class Adapter:
    def __init__(self, position=0.):
        self.state = SimpleNamespace(position=position, pending_entry_side=0, pending_exit=False)
        self.log, self.followups, self.intents = [], (), ()

    def prepare(self):
        self.log.append(("prepare",))

    def on_fill(self, fill):
        self.log.append(("fill", vars(fill)))
        self.state.position += fill.quantity
        return self.followups

    def on_bar_close(self, offset):
        self.log.append(("close", offset))
        return SimpleNamespace(intents=self.intents)


def binding(index=None, *, position=0., score_start=0):
    if index is None:
        index = pd.date_range("2022-01-01", periods=12, freq="h", tz="UTC")
    return BarCloseBinding(Adapter(position), symbol="X", index=index, score_start_bar=score_start,
        notional=2000., fill_factory=SimpleNamespace, kind_type=lambda kind: kind)


def context(timestamp, *, position=0., fills=(), events=()):
    return SimpleNamespace(timestamp=timestamp, positions={"X": position}, fills_this_bar=fills,
        order_events_this_bar=events, close=(100.,))


def result(call):
    try:
        call()
        return None
    except Exception as error:
        return type(error), str(error)


@pytest.mark.parametrize("index", (
    pd.date_range("2022-01-01", periods=12, freq="h", tz="UTC"),
    pd.date_range("2022-01-01", periods=12, freq="h", tz="UTC").as_unit("us"),
    pd.DatetimeIndex(["2022-01-01T03:00Z", "2022-01-01T01:00Z", "2022-01-01T05:00Z"]),
    pd.DatetimeIndex(["2022-01-01T00:00Z", pd.NaT, "2022-01-01T04:00Z"]),
    pd.Index([1, 3, 5]),
))
def test_offsets_match_original_indexer_for_gaps_repeats_jumps_and_generic_indexes(index):
    owner = binding(index)
    for timestamp in (*index, index[-1], index[0], index[0]):
        expected = int(index.get_indexer([timestamp])[0])
        if expected < 0:
            with pytest.raises(ValueError, match="outside the registered feature calendar"):
                owner.on_bar_close(context(timestamp))
            continue
        assert owner.on_bar_close(context(timestamp)) == ()
        assert owner.adapter.log[-1] == ("close", expected)


@pytest.mark.parametrize("timestamp", (
    pd.Timestamp("2022-01-01T01:30:00Z"), pd.Timestamp("2021-12-31T23:00:00Z"),
    pd.Timestamp("2022-01-01T01:00:00"), pd.Timestamp("2022-01-01T08:00:00+07:00"),
    pd.Timestamp("2500-01-01", tz="UTC"), pd.NaT, None,
    "2022-01-01T01:00:00Z", "not-a-time",
))
def test_mismatched_and_generic_timestamps_keep_original_fail_closed_behavior(timestamp):
    owner = binding()

    def original():
        offset = int(owner.index.get_indexer([timestamp])[0])
        if offset < 0:
            raise ValueError("engine callback is outside the registered feature calendar")

    expected = result(original)
    assert result(lambda: owner.on_bar_close(context(timestamp))) == expected
    if expected:
        assert owner.adapter.log == []


def test_duplicate_calendar_keeps_original_invalid_index_error():
    index = pd.DatetimeIndex(["2022-01-01T00:00Z", "2022-01-01T00:00Z"])
    owner = binding(index)
    assert result(lambda: owner.on_bar_close(context(index[0]))) == result(
        lambda: index.get_indexer([index[0]]))
    assert not owner.adapter.log


def test_replacing_calendar_invalidates_only_the_lookup_cursor():
    owner = binding()
    owner.on_bar_close(context(owner.index[2]))
    owner.index = owner.index + pd.Timedelta(days=1)
    owner.on_bar_close(context(owner.index[0]))
    assert owner.adapter.log == [("close", 2), ("close", 0)]


def test_valid_sequence_avoids_pandas_indexer_and_testing_assertion(monkeypatch):
    owner = binding(score_start=2)

    def forbidden(*args, **kwargs):
        raise AssertionError("hot lookup/testing call")

    monkeypatch.setattr(pd.DatetimeIndex, "get_indexer", forbidden)
    monkeypatch.setattr(np.testing, "assert_allclose", forbidden)
    for offset in (2, 3, 3, 7, 5, 5, 11):
        owner.on_bar_close(context(owner.index[offset]))
    for value in (float("nan"), float("inf"), -float("inf")):
        owner.adapter.state.position = value
        owner.on_bar_close(context(owner.index[11], position=value))
    owner.adapter.state.position = 0.
    owner.on_bar_close(context(owner.index[11], position=1e-12))


@pytest.mark.parametrize("actual,expected", (
    (0., 0.), (-0., 0.), (0., 1e-12), (0., np.nextafter(1e-12, 0.)),
    (0., np.nextafter(1e-12, np.inf)), (-1e-12, 0.), (1., 1. + 1e-12),
    (np.float64(0.), np.float64(1e-12)), (np.float64(2.), 2.),
    (float("nan"), float("nan")), (float("nan"), 0.), (0., float("nan")),
    (float("inf"), float("inf")), (-float("inf"), -float("inf")),
    (float("inf"), -float("inf")), (float("inf"), 1.), (1., float("inf")),
    (1e308, -1e308), (np.float64(1e308), np.float64(-1e308)),
    (np.float32(0.), np.float32(1e-12)), (np.float32(1.), np.float32(1.0001)),
    (np.int64(-(2**63)), np.int64(2**63 - 1)), (0, 0), (True, 1),
    (np.array([0., float("nan"), float("inf")]), np.array([0., float("nan"), float("inf")])),
    (np.array([0., 1.]), np.array([0., 2.])), (np.array(0.), 0.),
    (complex(1, 2), complex(1, 2)), (Decimal("1"), Decimal("1")), ("one", "one"),
))
def test_position_guard_preserves_original_numpy_semantics_and_errors(actual, expected):
    owner = binding(position=actual)
    expected_error = result(lambda: np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12,
        err_msg="strategy actual-fill feedback mismatch"))
    assert result(lambda: owner.on_bar_close(context(owner.index[0], position=expected))) == expected_error
    if expected_error:
        assert not owner.adapter.log
    else:
        assert owner.adapter.log == [("close", 0)]


def test_fill_and_reject_bookkeeping_precedes_position_check_then_decision():
    owner = binding(score_start=2)
    owner.entry_capacity = 20.
    owner.adapter.state.pending_entry_side = 1
    owner.adapter.state.pending_exit = True
    fill = SimpleNamespace(metadata=dict(admission_intent_kind="enter_long"), side=OrderSide.BUY,
        qty=2., price=101., fee=.1)
    owner.on_bar_close(context(owner.index[2], position=2., fills=(fill,),
        events=(SimpleNamespace(event_name="reject"),)))
    assert owner.fill_feedback_count == 1 and owner.entry_capacity == 20.
    assert owner.adapter.state.pending_entry_side == 0 and not owner.adapter.state.pending_exit
    assert owner.adapter.log == [("fill", dict(index=2, side=1, quantity=2., price=101.,
        intent_kind="enter_long", fee=.1)), ("close", 2)]
    owner.adapter.log.clear()
    with pytest.raises(AssertionError, match="strategy actual-fill feedback mismatch"):
        owner.on_bar_close(context(owner.index[3], position=3.))
    assert not owner.adapter.log


def test_preload_failure_keeps_prior_fill_processing_and_zeroes_entry_capacity():
    owner = binding(position=2., score_start=5)
    owner.entry_capacity = 20.
    fill = SimpleNamespace(metadata=dict(admission_intent_kind="exit_all"), side=OrderSide.SELL,
        qty=2., price=101., fee=.1)
    with pytest.raises(ValueError, match="financial run must exclude feature-only preload"):
        owner.on_bar_close(context(owner.index[4], fills=(fill,)))
    assert owner.fill_feedback_count == 1 and owner.entry_capacity == 0.
    assert owner.adapter.state.position == 0. and owner.adapter.log[0][0] == "fill"
    assert len(owner.adapter.log) == 1


def test_fill_relative_followup_still_fails_before_count_or_decision():
    owner = binding()
    owner.adapter.followups = (object(),)
    fill = SimpleNamespace(metadata=dict(admission_intent_kind="enter_long"), side=OrderSide.BUY,
        qty=1., price=101., fee=.1)
    with pytest.raises(UnsupportedFinancialBinding, match="fill-relative protection"):
        owner.on_bar_close(context(owner.index[0], position=1., fills=(fill,)))
    assert owner.fill_feedback_count == 0 and len(owner.adapter.log) == 1


def test_entry_and_exit_commands_keep_observation_close_sizing_and_global_ids():
    owner = binding()

    def intent(kind):
        return SimpleNamespace(kind=SimpleNamespace(value=kind), earliest_phase=SimpleNamespace(value="next_open"))

    owner.adapter.intents = (intent("enter_long"),)
    entered = owner.on_bar_close(context(owner.index[3]))
    assert entered[0].order_id == "admission-3-0" and entered[0].qty == 20.
    assert entered[0].timestamp == owner.index[3] and not entered[0].reduce_only
    owner.adapter.state.position = 2.
    owner.adapter.intents = (intent("exit_all"),)
    exited = owner.on_bar_close(context(owner.index[4], position=2.))
    assert exited[0].order_id == "admission-4-0" and exited[0].qty == entered[0].qty
    assert exited[0].side == OrderSide.SELL and exited[0].reduce_only
