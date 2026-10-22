"""Synthetic original-binding retry tests; no private alpha import or finance.

The opt-in helper is deliberately private and absent from public checkouts.
The toy generates a generic entry/bracket only to exercise inherited transport.
"""

from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError
from enum import Enum
import importlib.util
from pathlib import Path
import sys
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest


HELPER = (
    Path(__file__).resolve().parents[1]
    / "upgrade/local/mode5_upgrade_v1/m5-11-6/hma-perf-v1/lean_binding.py"
)
if not HELPER.is_file():
    pytest.skip("private compact-snapshot helper absent", allow_module_level=True)


@pytest.fixture(scope="module")
def lean():
    spec = importlib.util.spec_from_file_location("_hma_perf_snapshot_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class AdapterState:
    position: float = 0.0
    entry_price: float | None = None
    entry_index: int | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    pending_entry_side: int = 0
    pending_exit: bool = False
    realized_fills: int = 0


class Kind(str, Enum):
    ENTER_LONG = "enter_long"
    EXIT_ALL = "exit_all"
    SET_PROTECTION = "set_protection"


@dataclass
class ToyDecision:
    index: int
    position_entering_bar: float
    target_after_close: float
    intents: tuple = ()

    def as_record(self):
        return dict(index=self.index, position_entering_bar=self.position_entering_bar,
                    target_after_close=self.target_after_close)


class ToyHma:
    alpha_id = "A-HMA"

    def __init__(self, index, *, later=False):
        self.params = {"toy_trigger": 1, "toy_scope": "later" if later else "first"}
        self.market = SimpleNamespace(open=(100.0,) * len(index), high=(110.0,) * len(index),
            low=(90.0,) * len(index), close=(100.0,) * len(index),
            volume=(1.0,) * len(index), index=index, _cursor=-1)
        self.state, self.decisions, self._prepared = AdapterState(), [], True
        self.rsi_variant, self.gap_policy = "canonical", "reject"
        self.features = object()
        self.ignored_knobs = {"provenance": "toy"}
        self.sl_input, self.sl_input_migrated_from = "toy-stop", None

    def on_bar_close(self, t):
        self.market._cursor = t
        entering = self.state.position
        intents = ()
        if t == self.params["toy_trigger"] and not entering and not self.state.pending_entry_side:
            self.state.pending_entry_side = 1
            self._staged = dict(side=1, stop_level=90.0, tp_level=110.0, decision_index=t)
            intents = (SimpleNamespace(kind=Kind.ENTER_LONG,
                earliest_phase=SimpleNamespace(value="next_open"), reason="toy-entry"),)
        decision = ToyDecision(t, entering, 1.0 if intents else entering, intents)
        self.decisions.append(decision)
        return decision

    def on_fill(self, fill):
        self.state.position += fill.quantity
        self.state.realized_fills += 1
        if fill.intent_kind == Kind.ENTER_LONG:
            self.state.entry_price, self.state.entry_index = fill.price, fill.index
            self.state.pending_entry_side = 0
            self.state.stop_price, self.state.take_profit_price = 90.0, 110.0
            return (SimpleNamespace(kind=Kind.SET_PROTECTION,
                earliest_phase=SimpleNamespace(value="resting_intrabar"),
                stop_price=90.0, take_profit_price=110.0, ladder=(), reason="toy-protection"),)
        if self.state.position == 0:
            self.state.entry_price = self.state.entry_index = None
            self.state.stop_price = self.state.take_profit_price = None
            self.state.pending_exit = False
        return ()


def create(lean, *, compact=True, variable=False):
    index = pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC")
    template = ToyHma(index)
    later = ToyHma(index, later=True) if variable else template
    financial = SimpleNamespace(alpha="A-HMA", template=template, start=1, stop=8,
        history=pd.DataFrame({"close": 100.0}, index=index),
        constraints=dict(qty_step=0.01, min_qty=0.01, min_notional=0.0))
    config = dict(symbol="X", notional=2000.0)
    contracts = SimpleNamespace(Fill=lambda **kwargs: SimpleNamespace(**kwargs), IntentKind=Kind)
    schedule = (lean.original.ScheduleEntry(0, 1, template), lean.original.ScheduleEntry(1, 2, later))
    cls = lean.LeanHmaScheduledIncrementalBinding if compact else lean.original.ScheduledIncrementalBinding
    return cls(financial, config, contracts, schedule, state_policy=lean.original.PREFIX_RECOMPUTE_V1)


def feedback(binding, *, entry=True, reject=False):
    from quantbt import Fill, OrderSide
    from tools.mode5_research.incremental_feedback import FeedbackEvent

    order_id = "entry-1" if entry else "entry-1-stop"
    if reject:
        return FeedbackEvent(2, order_id, "reject", record={"reason": "toy-reject"})
    fill = Fill(timestamp=binding.original.history.index[2], symbol="X", order_id=order_id,
        side=OrderSide.BUY if entry else OrderSide.SELL, qty=20.0, price=100.0, fee=0.01,
        metadata=binding.known["entry-1"].metadata)
    return FeedbackEvent(2, order_id, "fill", fill=fill)


def state_view(binding):
    return dict(state=vars(binding.adapter.state).copy(),
        staged=deepcopy(getattr(binding.adapter, "_staged", None)),
        rows=binding.rows[:], commands=binding.commands(), decisions=binding.decisions[:],
        adapter_decisions=binding.adapter.decisions[:], known=binding.known.copy(),
        parent=binding.parent, feedback_count=binding.feedback_count,
        ladders=deepcopy(binding.ladders), rejections=deepcopy(binding.rejections),
        terminal_intents=deepcopy(binding.terminal_intents),
        cursor=binding.adapter.market._cursor, active_schedule_index=binding.active_schedule_index)


def test_only_snapshot_restore_are_overridden(lean):
    cls, original = lean.LeanHmaScheduledIncrementalBinding, lean.original.ScheduledIncrementalBinding
    assert issubclass(cls, original)
    for name in ("__init__", "advance", "translate", "commands", "add", "cleanup", "_at_close"):
        assert getattr(cls, name) is getattr(original, name)
    assert lean.LeanScheduledBinding is cls


@pytest.mark.parametrize("variable", [False, True])
@pytest.mark.parametrize("outcome", ["entry", "same-bar-stop", "reject"])
def test_retry_matches_original_snapshot_and_inherited_oco_decisions(lean, variable, outcome):
    compact, reference = create(lean, variable=variable), create(lean, compact=False, variable=variable)
    for binding in (compact, reference):
        binding.advance(1, ())
    checkpoints = (compact.snapshot(), reference.snapshot())
    before = state_view(compact)
    owner, params, features = compact.adapter, compact.adapter.params, compact.adapter.features
    for repeat in range(3):
        for binding, checkpoint in zip((compact, reference), checkpoints):
            binding.restore(checkpoint)
            events = (feedback(binding, reject=outcome == "reject"),)
            if outcome == "same-bar-stop":
                events += (feedback(binding, entry=False),)
            binding.advance(2, events)
        assert state_view(compact) == state_view(reference)
        if variable:
            assert compact.adapter is not owner
    compact.restore(checkpoints[0])
    assert compact.adapter is owner and owner.params is params and owner.features is features
    assert state_view(compact) == before


def test_all_eight_state_fields_and_numpy_scalar_types_restore_without_coercion(lean):
    binding = create(lean)
    values = (np.float64(2.0), np.float64(100.0), np.int64(2), 90.0,
              np.float64(110.0), np.int64(1), np.bool_(True), np.int64(7))
    for name, value in zip(lean._STATE, values):
        setattr(binding.adapter.state, name, value)
    snapshot = binding.snapshot()
    binding.adapter.state = AdapterState()
    binding.restore(snapshot)
    for name, value in zip(lean._STATE, values):
        actual = getattr(binding.adapter.state, name)
        assert type(actual) is type(value) and actual == value


def test_staged_absence_restore_and_repeated_retry_do_not_share_mutable_copies(lean):
    binding = create(lean)
    absent = binding.snapshot()
    binding.advance(1, ())
    binding.restore(absent)
    assert not hasattr(binding.adapter, "_staged")
    binding.advance(1, ())
    snapshot = binding.snapshot()
    binding.adapter._staged["stop_level"] = 1.0
    binding.restore(snapshot)
    first = binding.adapter._staged
    first["stop_level"] = 5.0
    binding.restore(snapshot)
    assert binding.adapter._staged is not first
    assert binding.adapter._staged["stop_level"] == 90.0
    assert dict(snapshot.staged)["stop_level"] == 90.0


def test_prepared_refs_constructor_flags_cursor_and_schedule_identity_restore(lean):
    binding = create(lean)
    binding.advance(1, ())
    owner = binding.adapter
    snapshot = binding.snapshot()
    prepared = tuple(getattr(owner, name) for name in lean._PREPARED)
    for name in lean._PREPARED:
        setattr(owner, name, object())
    owner.rsi_variant, owner.gap_policy, owner._prepared = "legacy", "normalize", False
    owner.market._cursor = 7
    binding.active_schedule_index = 1
    binding.restore(snapshot)
    assert tuple(getattr(owner, name) for name in lean._PREPARED) == prepared
    assert all(getattr(owner, name) is value for name, value in zip(lean._PREPARED, prepared))
    assert owner.rsi_variant == "canonical" and owner.gap_policy == "reject" and owner._prepared
    assert owner.market._cursor == 1 and binding.active_schedule_index == 0
    assert binding.schedule is snapshot.static_owners[3]


def test_record_lengths_known_parent_feedback_and_command_cache_restore(lean):
    binding = create(lean)
    binding.advance(1, ())
    before = state_view(binding)
    snapshot = binding.snapshot()
    binding.advance(2, (feedback(binding),))
    binding.ladders.append({"toy": 1})
    binding.rejections.append({"toy": 2})
    binding.terminal_intents.append({"toy": 3})
    binding.parent, binding.feedback_count = "different", 100
    binding.commands()
    binding.restore(snapshot)
    assert binding._commands is None
    assert state_view(binding) == before


@pytest.mark.parametrize("target", ["binding", "adapter", "state", "market"])
@pytest.mark.parametrize("when", ["snapshot", "restore"])
def test_unexpected_mutable_attribute_fails_closed(lean, target, when):
    binding = create(lean)
    snapshot = binding.snapshot()
    targets = dict(binding=binding, adapter=binding.adapter,
                   state=binding.adapter.state, market=binding.adapter.market)
    setattr(targets[target], "unreviewed_mutable_state", [])
    with pytest.raises(ValueError, match="layout"):
        binding.snapshot() if when == "snapshot" else binding.restore(snapshot)


@pytest.mark.parametrize("value", [None, {"only_one_key": 1},
    dict(side=1, stop_level=[], tp_level=110.0, decision_index=1)])
def test_unqualified_staged_shape_fails_closed(lean, value):
    binding = create(lean)
    binding.adapter._staged = value
    with pytest.raises(ValueError, match="staged-level"):
        binding.snapshot()


def test_unknown_state_fields_or_mutable_scalar_cannot_hide_in_snapshot(lean):
    binding = create(lean)
    binding.adapter.state.position = np.array([1.0])
    with pytest.raises(ValueError, match="eight-scalar"):
        binding.snapshot()


def test_cross_owner_restore_and_replaced_record_owners_are_rejected(lean):
    left, right = create(lean), create(lean)
    snapshot = left.snapshot()
    with pytest.raises(ValueError, match="different binding"):
        right.restore(snapshot)
    left.rows = list(left.rows)
    with pytest.raises(ValueError, match="identity"):
        left.restore(snapshot)


def test_shrunken_prefix_and_replaced_schedule_fail_before_partial_restore(lean):
    binding = create(lean)
    binding.advance(1, ())
    snapshot = binding.snapshot()
    binding.decisions.clear()
    with pytest.raises(ValueError, match="retained prefix"):
        binding.restore(snapshot)
    second = create(lean)
    snapshot = second.snapshot()
    second.schedule = tuple(list(second.schedule))
    with pytest.raises(ValueError, match="identity"):
        second.restore(snapshot)


def test_snapshot_is_frozen_and_independent_candidates_do_not_share_state(lean):
    left, right = create(lean), create(lean)
    left.advance(1, ())
    snapshot = left.snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.state.position = 100.0
    left.adapter.state.pending_entry_side = -1
    assert right.adapter.state.pending_entry_side == 0
    left.restore(snapshot)
    left.adapter.state.pending_entry_side = 0
    left.restore(snapshot)
    assert left.adapter.state.pending_entry_side == 1
    assert right.adapter.state.pending_entry_side == 0


def test_non_hma_owner_is_rejected_without_changing_reference_code(lean):
    binding = create(lean)
    binding.original.alpha = "A-HASH"
    with pytest.raises(ValueError, match="binding instance layout"):
        binding.snapshot()


def add_preparation(adapter):
    array = np.frombuffer(np.arange(8.0).tobytes(), dtype=np.float64)
    adapter.features = SimpleNamespace(_arrays=MappingProxyType({"toy_indicator": array}))
    adapter._hma_preparation_owner = 731
    adapter._hma_preparation_params = adapter.params.copy()
    adapter._hma_preparation_key = ("toy-version", "source", 8, (1, 2, 3))
    adapter._hma_preparation_arrays = (("toy_indicator", id(array)),)
    return array


def test_declared_preparation_metadata_restores_identity_without_copying_arrays(lean):
    binding = create(lean)
    array = add_preparation(binding.adapter)
    binding.advance(1, ())
    snapshot = binding.snapshot()
    original_features = binding.adapter.features
    params_witness = binding.adapter._hma_preparation_params
    binding.advance(2, (feedback(binding),))
    binding.restore(snapshot)
    assert binding.adapter.features is original_features
    assert binding.adapter.features._arrays["toy_indicator"] is array
    assert binding.adapter._hma_preparation_params is params_witness
    assert binding.adapter._hma_preparation_key == ("toy-version", "source", 8, (1, 2, 3))
    with pytest.raises(ValueError):
        array.setflags(write=True)


@pytest.mark.parametrize("corrupt", ["missing", "mutable-key", "params", "owner", "arrays", "writable", "writable-base"])
def test_preparation_witnesses_fail_closed_on_unknown_or_mutable_contract(lean, corrupt):
    binding = create(lean)
    adapter = binding.adapter
    add_preparation(adapter)
    if corrupt == "missing":
        del adapter._hma_preparation_key
    elif corrupt == "mutable-key":
        adapter._hma_preparation_key = ("version", [])
    elif corrupt == "params":
        adapter._hma_preparation_params = {"different": 1}
    elif corrupt == "owner":
        adapter._hma_preparation_owner = []
    elif corrupt == "arrays":
        adapter._hma_preparation_arrays = (("toy_indicator", 123),)
    else:
        array = np.arange(8.0)
        if corrupt == "writable-base":
            array = array.view()
            array.flags.writeable = False
        adapter.features._arrays = MappingProxyType({"toy_indicator": array})
        adapter._hma_preparation_arrays = (("toy_indicator", id(adapter.features._arrays["toy_indicator"])),)
    with pytest.raises(ValueError, match="preparation"):
        binding.snapshot()


def test_teammate_frozen_wrapper_deepcopy_keeps_verified_array_aliases(lean):
    path = HELPER.parent / "preparation.py"
    if not path.is_file():
        pytest.skip("separate private preparation helper absent")
    spec = importlib.util.spec_from_file_location("_hma_perf_preparation_snapshot_test", path)
    preparation = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = preparation
    spec.loader.exec_module(preparation)
    binding = create(lean)
    array = add_preparation(binding.adapter)
    binding.adapter.features = preparation.FrozenHmaFeatures(
        {"toy_indicator": array}, {"values": {"toy": 1}}
    )
    binding.adapter = deepcopy(binding.adapter)
    snapshot = binding.snapshot()
    assert binding.adapter.features._arrays["toy_indicator"] is array
    binding.advance(1, ())
    binding.restore(snapshot)
    assert binding.adapter.features._arrays["toy_indicator"] is array
    assert binding.adapter._hma_preparation_arrays == (("toy_indicator", id(array)),)
