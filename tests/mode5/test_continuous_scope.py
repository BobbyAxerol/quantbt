"""Calendar-policy fixtures only; not original-alpha execution qualification."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import pickle

import numpy as np
import pandas as pd
import pytest

from quantbt.mode5.continuous import DAY_NS, ContinuousAccountContract
from quantbt.mode5.continuous_scope import ContinuousAccountScope, SCOPE_VERSION
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.geometry.schema import EffectiveGeometry


HOUR = DAY_NS // 24


def ns(value):
    return int(pd.Timestamp(value, tz="UTC").value)


def contract_fixture(*, preload="2020-12-30", start="2021-01-01", stop="2021-01-03",
                     step=HOUR, purpose="selection", witness_stop=None):
    start_ns, stop_ns = ns(start), ns(stop)
    end = stop_ns if witness_stop is None else ns(witness_stop)
    metrics = Record.of(dict(bar_interval_ns=step, currency="USD", annual_periods=365.,
        dd_weight=1., tail_weight=1., tail_confidence=.95, min_daily_returns=1,
        min_closed_records=0, max_drawdown=1., min_utility=-10.))
    execution = Record.of(dict(route="calendar_fixture", backend="python",
        clock=dict(id="fixture_bar_close", equity_clock="bar_close"),
        initial_state=dict(equity=100., position_policy="flat"),
        terminal_policy=dict(id="mark_only"), economics=dict(one_way_fee_rate=.0005)))
    contract = ContinuousAccountContract(start_ns, stop_ns,
        EffectiveGeometry.from_ranges({"period": (2, 20, 1)}), metrics,
        digest("sealed_metric_binding_fixture"),
        Record.of(dict(alpha=digest("calendar_fixture"), financial_provider=digest("no_execution"))),
        execution, AccessPolicy("fixture-rights", ("synthetic",), ("market-1",), end, purpose),
        AccessWitness("market-1", "synthetic", ns(preload), end, end))
    index = pd.date_range(pd.Timestamp(ns(preload), tz="UTC"),
        pd.Timestamp(stop_ns, tz="UTC"), freq=pd.Timedelta(step, unit="ns"), inclusive="left")
    return contract, index


def test_registered_calendar_shape_keeps_2020_preload_and_scores_2021_to_2023():
    c, index = contract_fixture(preload="2020-01-01", stop="2024-01-01")
    scope = ContinuousAccountScope.from_contract(c, index)
    assert scope.full_index.equals(index)
    assert scope.preload_index.equals(index[:366 * 24])
    assert scope.scored_index.equals(index[366 * 24:])
    assert set(scope.scored_index.year) == {2021, 2022, 2023}
    assert len(scope.scored_index) == 1095 * 24
    assert scope.scored_slice == slice(8784, 35064)
    assert scope.prefix_slice(c.stop_ns - HOUR) == slice(0, len(index))
    scope.require_full_index(index)
    scope.require_scored_index(scope.scored_index)
    metadata = scope.metadata()
    assert metadata["schema"] == SCOPE_VERSION
    assert metadata["contract_identity"] == c.identity
    assert metadata["preload_bars"] == 8784
    assert metadata["scored_bars"] == 26280
    assert metadata["initial_state"] == c.execution.data["initial_state"]
    assert metadata["annual_account_resets"] == 0
    assert metadata["preload_account_execution"] is False
    assert metadata["execution_qualification"] is False


@pytest.mark.parametrize("step", [DAY_NS, HOUR, HOUR // 2, 1])
def test_exact_minimal_day_and_half_open_end_bounds(step):
    # A one-nanosecond interval uses a prebuilt byte descriptor to test alignment
    # rejection without allocating a day's worth of observations.
    c, index = contract_fixture(step=DAY_NS if step == 1 else step)
    if step == 1:
        c = replace(c, metrics=Record.of({**c.metrics.data, "bar_interval_ns": 1}))
        with pytest.raises(PermissionError, match="full prefix must end"):
            ContinuousAccountScope.from_contract(c, index)
        return
    scope = ContinuousAccountScope.from_contract(c, index)
    assert int(scope.scored_index[0].value) == c.start_ns
    assert int(scope.scored_index[-1].value) == c.stop_ns - step
    assert scope.scored_slice.stop - scope.scored_slice.start == (c.stop_ns-c.start_ns)//step


def test_no_preload_only_when_sealed_witness_explicitly_starts_at_score_start():
    c, index = contract_fixture(preload="2021-01-01")
    scope = ContinuousAccountScope.from_contract(c, index)
    assert scope.preload_index.empty
    assert scope.scored_slice == slice(0, len(index))
    assert scope.full_index.equals(scope.scored_index)


@pytest.mark.parametrize("cut", [0, 1, 24, 48, 49, -1])
def test_missing_preload_or_scored_observation_is_not_repaired(cut):
    c, index = contract_fixture()
    with pytest.raises((ValueError, PermissionError)):
        ContinuousAccountScope.from_contract(c, index.delete(cut))


@pytest.mark.parametrize("cut", [1, 24, 48])
def test_duplicate_calendar_is_rejected(cut):
    c, index = contract_fixture()
    with pytest.raises(ValueError, match="ordered"):
        ContinuousAccountScope.from_contract(c, index.insert(cut, index[cut]))


@pytest.mark.parametrize("cut", [1, 24, 48])
def test_unsorted_calendar_is_rejected_without_sorting(cut):
    c, index = contract_fixture()
    order = np.arange(len(index))
    order[cut], order[cut+1] = order[cut+1], order[cut]
    with pytest.raises(ValueError, match="ordered"):
        ContinuousAccountScope.from_contract(c, index[order])


@pytest.mark.parametrize("index", [pd.DatetimeIndex([], tz="UTC"), pd.DatetimeIndex([pd.NaT])])
def test_empty_and_nat_are_rejected(index):
    c, _ = contract_fixture()
    with pytest.raises(ValueError):
        ContinuousAccountScope.from_contract(c, index)


@pytest.mark.parametrize("kind", ["list", "series", "range"])
def test_untyped_calendars_are_rejected(kind):
    c, index = contract_fixture()
    values = {"list": list(index), "series": pd.Series(index), "range": pd.RangeIndex(len(index))}
    with pytest.raises(ValueError, match="DatetimeIndex"):
        ContinuousAccountScope.from_contract(c, values[kind])


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_resolution_and_naive_utc_have_one_exact_identity(unit):
    c, index = contract_fixture()
    expected = ContinuousAccountScope.from_contract(c, index)
    for candidate in (index.as_unit(unit), index.tz_localize(None).as_unit(unit)):
        actual = ContinuousAccountScope.from_contract(c, candidate)
        assert actual.identity == expected.identity
        assert actual.full_index.equals(index)
        actual.require_full_index(candidate)
        actual.require_scored_index(candidate[48:])


@pytest.mark.parametrize("timezone", ["Europe/London", "Asia/Singapore", "US/Eastern"])
def test_other_timezones_must_be_normalized_by_ingestion(timezone):
    c, index = contract_fixture()
    with pytest.raises(ValueError, match="UTC"):
        ContinuousAccountScope.from_contract(c, index.tz_convert(timezone))


@pytest.mark.parametrize("change", ["early", "late", "drop_preload", "shift", "append_future"])
def test_full_prefix_bounds_cannot_expand_or_omit_registered_history(change):
    c, index = contract_fixture(witness_stop="2021-01-04")
    candidates = dict(early=index.insert(0, index[0]-pd.Timedelta(hours=1)),
        late=index[1:], drop_preload=index[48:], shift=index+pd.Timedelta(hours=1),
        append_future=index.append(pd.DatetimeIndex([pd.Timestamp(c.stop_ns, tz="UTC")])))
    with pytest.raises(PermissionError):
        ContinuousAccountScope.from_contract(c, candidates[change])


def test_off_grid_witness_preload_cannot_be_snapped_to_score_start():
    c, _ = contract_fixture()
    witness = replace(c.witness, start_ns=c.witness.start_ns+HOUR//2)
    c = replace(c, witness=witness)
    index = pd.date_range(pd.Timestamp(witness.start_ns, tz="UTC"),
        pd.Timestamp(c.stop_ns-HOUR, tz="UTC"), freq="h")
    index = index.append(pd.DatetimeIndex([pd.Timestamp(c.stop_ns-HOUR, tz="UTC")]))
    with pytest.raises(ValueError, match="exact complete"):
        ContinuousAccountScope.from_contract(c, index)


@pytest.mark.parametrize("change", ["full", "preload", "missing", "future", "shift"])
def test_post_account_guard_rejects_preload_and_illegal_account_windows(change):
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    scored = scope.scored_index
    candidates = dict(full=index, preload=scope.preload_index, missing=scored.delete(1),
        future=scored.append(pd.DatetimeIndex([pd.Timestamp(c.stop_ns, tz="UTC")])),
        shift=scored+pd.Timedelta(hours=1))
    with pytest.raises(ValueError):
        scope.require_scored_index(candidates[change])


@pytest.mark.parametrize("change", ["score_only", "missing", "future"])
def test_pre_market_guard_rejects_changed_prefix(change):
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    candidates = dict(score_only=scope.scored_index, missing=index.delete(1),
        future=index.append(pd.DatetimeIndex([pd.Timestamp(c.stop_ns, tz="UTC")])))
    with pytest.raises(PermissionError):
        scope.require_full_index(candidates[change])


@pytest.mark.parametrize("offset", [-1, 96, 97])
def test_prefix_cutoff_cannot_read_before_or_after_allowed_window(offset):
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    with pytest.raises(PermissionError):
        scope.prefix_slice(c.witness.start_ns+offset*HOUR)


def test_prefix_positions_use_full_clock_and_exact_inclusive_bar():
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    assert scope.prefix_slice(c.witness.start_ns) == slice(0, 1)
    assert scope.prefix_slice(c.start_ns) == slice(0, 49)
    assert index[scope.prefix_slice(c.start_ns)].equals(scope.full_index[:49])
    with pytest.raises(ValueError, match="exact observed"):
        scope.prefix_slice(c.start_ns+1)
    for invalid in (True, float(c.start_ns), np.int64(c.start_ns), pd.Timestamp(c.start_ns, tz="UTC")):
        with pytest.raises(TypeError):
            scope.prefix_slice(invalid)


@pytest.mark.parametrize("change", ["future_end", "immature", "role", "manifest"])
def test_sealed_rights_fail_before_any_scope_can_be_derived(change):
    c, _ = contract_fixture()
    changes = dict(future_end=dict(end_ns=c.stop_ns+HOUR, ready_ns=c.stop_ns+HOUR),
        immature=dict(ready_ns=c.stop_ns+HOUR), role=dict(role="holdout"),
        manifest=dict(manifest_id="unregistered-market"))
    with pytest.raises(PermissionError):
        replace(c, witness=replace(c.witness, **changes[change]))


def test_rights_rechecked_on_derive_and_both_boundary_guards(monkeypatch):
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)

    def denied(policy, witness):
        raise PermissionError("current access gate denied")

    monkeypatch.setattr(AccessPolicy, "require", denied)
    for action in (lambda: ContinuousAccountScope.from_contract(c, index),
                   lambda: scope.require_full_index(index),
                   lambda: scope.require_scored_index(index[48:]),
                   lambda: scope.prefix_slice(c.start_ns)):
        with pytest.raises(PermissionError, match="current access"):
            action()


@pytest.mark.parametrize("position_policy", ["carry", "replay_prior_state", None])
def test_initial_flat_is_explicit_and_does_not_infer_carried_state(position_policy):
    c, index = contract_fixture()
    initial = dict(equity=100.)
    if position_policy is not None:
        initial["position_policy"] = position_policy
    c = replace(c, execution=Record.of({**c.execution.data, "initial_state": initial}))
    with pytest.raises(NotImplementedError, match="flat account entry"):
        ContinuousAccountScope.from_contract(c, index)


def test_existing_single_fold_and_prepared_window_use_scored_positions_on_full_clock():
    from quantbt.core.wfo_preparation import PreparedWfoWindowRegistryV1

    c, index = contract_fixture(preload="2020-01-01", stop="2024-01-01")
    scope = ContinuousAccountScope.from_contract(c, index)
    folds = scope.folds()
    assert len(folds) == 1
    fold = folds[0]
    assert fold.train_index is fold.test_index
    assert fold.train_index.equals(scope.scored_index)
    assert fold.train_start.value == c.start_ns
    assert fold.test_end.value == fold.cutoff_timestamp.value == c.stop_ns-HOUR
    assert fold.account_policy == "carry_position"
    assert fold.warmup_index.empty  # No new warmup callback semantics.
    registry = PreparedWfoWindowRegistryV1(scope.full_index)
    window = registry.register(fold.test_index)
    assert (window.start, window.stop) == (scope.scored_slice.start, scope.scored_slice.stop)
    assert registry.window_for(fold.test_index) is window


@pytest.mark.parametrize("operation", [deepcopy, lambda x: pickle.loads(pickle.dumps(x, protocol=4)),
                                       lambda x: pickle.loads(pickle.dumps(x, protocol=5))])
def test_scope_does_not_retain_mutable_caller_or_returned_calendar(operation):
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    copied = operation(scope)
    identity = scope.identity
    index.values[0] = index.values[1]
    for exposed in (copied.full_index, copied.scored_index, copied.preload_index):
        exposed.values[0] = exposed.values[1]
    metadata = copied.metadata()
    metadata["initial_state"]["equity"] = 999.
    assert copied.identity == scope.identity == identity
    assert copied.full_index[0].value == c.witness.start_ns
    assert copied.scored_index[0].value == c.start_ns
    assert copied.metadata()["initial_state"]["equity"] == 100.
    with pytest.raises(FrozenInstanceError):
        copied.version = "unknown"


def test_identity_includes_rights_and_execution_not_just_equal_calendar():
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    altered = replace(c, access=replace(c.access, cutoff_ns=c.stop_ns+HOUR))
    assert ContinuousAccountScope.from_contract(altered, index).identity != scope.identity
    execution = Record.of({**c.execution.data, "economics": dict(one_way_fee_rate=.001)})
    assert ContinuousAccountScope.from_contract(replace(c, execution=execution), index).identity != scope.identity


def test_typed_contract_and_version_cannot_be_bypassed():
    c, index = contract_fixture()
    scope = ContinuousAccountScope.from_contract(c, index)
    for contract in (None, c.to_metadata(), object()):
        with pytest.raises(TypeError, match="ContinuousAccountContract"):
            ContinuousAccountScope.from_contract(contract, index)
    with pytest.raises(ValueError, match="version"):
        replace(scope, version="quantbt.mode5.continuous_account_scope.v0")
    for raw in (bytearray(scope._full_calendar), b"", b"bad"):
        with pytest.raises(TypeError, match="immutable"):
            replace(scope, _full_calendar=raw)


def test_held_diagnostic_rights_are_not_upgraded_to_selection():
    c, index = contract_fixture(purpose="diagnostic")
    scope = ContinuousAccountScope.from_contract(c, index)
    assert scope.contract.access.purpose == "diagnostic"
    assert scope.metadata()["access_identity"] == c.access.identity
    assert scope.metadata()["validation_claim"] == "none_full_sample_calibration"
