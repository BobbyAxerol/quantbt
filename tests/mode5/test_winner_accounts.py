"""Pure retained-path controls; no strategy, optimizer, fitting or finance runs."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.diagnostics.evidence import ExecutionEvidence, FrozenBuffer, MissingInputs
from quantbt.diagnostics.winner import accounts
from quantbt.diagnostics.winner.accounts import WinnerStateView, profile_selected_account
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.evaluation import array_identity

DAY = 86_400_000_000_000
HALF_DAY = DAY // 2
STREAMS = ("equity", "positions", "fees", "funding", "margin")


@pytest.fixture
def retained():
    # Two close marks/day across two partial calendar years, with carried equity.
    index = pd.date_range("2020-12-29", periods=12, freq="12h", tz="UTC")
    result = SimpleNamespace(
        initial_capital=100., final_equity=115.,
        equity=pd.Series([99., 102., 103., 105., 104., 101., 104., 110., 110., 110., 111., 115.], index=index),
        positions=pd.DataFrame(dict(a=[0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0],
                                    b=[0, 0, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0]), index=index),
        fees=pd.Series([1., 0., 0., 2., 0., 0., 0., 0., 0., 0., 0., 3.], index=index),
        funding=pd.Series([0., .1, -.2, .3, 0., 0., 0., -.4, 0., 0., 0., 0.], index=index),
        margin=pd.DataFrame(dict(a=np.arange(12.), b=np.arange(12.) * 2), index=index),
        metadata=dict(backend="synthetic_retained", execution_contract="original_close_clock"),
        # Deliberately inconsistent with any fill/campaign inference.
        trades=[SimpleNamespace(closed_at=index[1])], fills=[object()] * 9,
    )
    observation = dict(environment_id="whole_path", account_policy="CONTINUOUS_PATH_ATTRIBUTION",
        start_ns=int(index[0].value), stop_ns=int(index[-1].value) + HALF_DAY,
        finance={name: array_identity(getattr(result, name).to_numpy()) for name in STREAMS},
        initial_capital=100., final_equity=115., metric_contract="original-metric-contract",
        closed_records=7, closed_record_unit="engine_closed_records_not_closed_actions_or_inferred_campaigns")
    witness = AccessWitness("account", "synthetic", observation["start_ns"], observation["stop_ns"], observation["stop_ns"])
    labels = replace(witness, manifest_id="labels", ready_ns=witness.end_ns + DAY)
    access = AccessPolicy("cold-winner", ("synthetic",), ("account", "labels"), labels.ready_ns, "diagnostic")
    return result, observation, dict(access=access, witness=witness, source_ref="original-selected-result"), labels


def state(witness, labels=(0, 0, -1, 1, 1, 1), **changes):
    values = dict(name="trend", labels=FrozenBuffer.from_array("daily-state", np.asarray(labels)),
        witness=witness, source_ref="original-state-vintage", label_names=((0, "down"), (1, "up")))
    values.update(changes)
    return WinnerStateView(**values)


def identities(result):
    return {name: array_identity(getattr(result, name).to_numpy()) for name in STREAMS}


def test_original_activity_uses_actual_marks_and_keeps_missing_evidence(retained):
    result, original, kwargs, _ = retained
    before = identities(result)
    observation = deepcopy(original)
    payload = profile_selected_account(result, original, **kwargs)
    activity = payload["activity"]
    assert activity["initial_equity"] == 100. and activity["terminal_equity"] == 115.
    assert activity["net_pnl"] == 15.
    assert activity["observed_days"] == 6 and activity["observed_bars"] == 12
    assert activity["exposed_bars"] == 5 and activity["exposed_days"] == 3
    assert activity["long_close_mark_bars"] == 4 and activity["short_close_mark_bars"] == 2
    assert activity["exposure_fraction"] == pytest.approx(5 / 12)
    assert activity["exposure_unit"] == "occupied_close_marks"
    assert activity["fees"] == 6. and activity["funding"] == pytest.approx(-.2)
    assert activity["engine_closed_records"] == 7  # Original count, not len(result.trades).
    assert activity["engine_closed_record_unit"] == original["closed_record_unit"]
    assert activity["fills"]["value"] is None and activity["campaigns"]["value"] is None
    assert activity["opportunities"]["value"] is None
    assert activity["environments_status"] == "NOT_SUPPLIED"
    assert payload["states"]["status"] == "NOT_SUPPLIED" and payload["states"]["reason"]
    assert payload["states"]["families"] == []
    assert payload["view"] == "full_development" and payload["decision_use"] == "NOT_BACKDATABLE"
    assert payload["calendar"] == dict(start_ns=original["start_ns"], stop_ns=original["stop_ns"],
        step_ns=HALF_DAY, bars=12, timezone="UTC")
    assert identities(result) == before and original == observation


def test_partial_years_and_overlapping_state_families_are_not_pooled(retained):
    result, original, kwargs, label_witness = retained
    views = (state(label_witness), state(label_witness, labels=(0, 1, 0, 1, 0, 1),
        name="volatility", source_ref="different-label-source", purpose="decision_vintage"))
    payload = profile_selected_account(result, original, state_views=views, **kwargs)
    assert payload["states"]["status"] == "OBSERVED"
    assert payload["states"]["independent_sample_count"] is None
    assert "never sum" in payload["states"]["aggregation"]
    assert len(payload["states"]["families"]) == 2
    for family, view in zip(payload["states"]["families"], views):
        assert family["source_ref"] == view.source_ref
        assert family["witness"] == asdict(view.witness) and family["purpose"] == view.purpose
        assert family["independent_sample_count"] is None
        assert sum(r["days"] for r in family["groups"]) == 6
        assert sum(r["money_pnl"] for r in family["groups"]) == 15.
        assert sum(r["fees"] for r in family["groups"]) == 6.
        assert family["attribution"]["summed_group_pnl"] == 15.
        assert all(r["annualized_return"] is None and r["annualized_sharpe"] is None for r in family["groups"])
    unknown = next(r for r in payload["states"]["families"][0]["groups"] if r["state"] == -1)
    assert unknown["name"] == "UNKNOWN" and unknown["days"] == 1 and unknown["money_pnl"] == -4.
    assert unknown["conditional_sharpe"]["status"] == "MISSING"
    up = next(r for r in payload["states"]["families"][0]["groups"] if r["state"] == 1)
    assert up["name"] == "up" and up["conditional_sharpe"]["status"] == "OBSERVED"
    # Costs on a flat close still count; no inferred fill/campaign support.
    assert up["fees"] == 3. and up["exposed_bars"] == 2


def test_dataframe_singletons_keep_original_hash_shapes(retained):
    result, original, kwargs, _ = retained
    for name in ("equity", "fees", "funding"):
        setattr(result, name, getattr(result, name).to_frame(name))
        original["finance"][name] = array_identity(getattr(result, name).to_numpy())
    payload = profile_selected_account(result, original, **kwargs)
    assert payload["finance"] == original["finance"]
    assert payload["activity"]["net_pnl"] == 15. and payload["activity"]["fees"] == 6.


@pytest.mark.parametrize("rich_result", (False, True))
def test_actual_completed_result_contracts_use_original_selected_final_marks(retained, rich_result):
    from quantbt.core.results import BacktestResultV2
    from quantbt.core.types import BacktestResult

    source, original, kwargs, _ = retained
    fields = dict(equity=source.equity.copy(), returns=pd.Series(0., index=source.equity.index),
        positions=source.positions.copy(), closes=pd.DataFrame(1., index=source.equity.index, columns=["a", "b"]),
        symbols=["a", "b"], initial_capital=source.initial_capital, leverage=1., metadata=deepcopy(source.metadata))
    if rich_result:
        fields.update(fees=source.fees.copy(), funding=source.funding.copy(), margin=source.margin.copy())
        result = BacktestResultV2(**fields)
    else:
        result = BacktestResult(**fields)
        original["finance"] = {name: original["finance"][name] for name in ("equity", "positions")}
    profile = profile_selected_account(result, original, **kwargs)
    assert profile["finance"] == original["finance"]
    assert profile["activity"]["terminal_equity"] == 115.
    assert profile["activity"]["engine_closed_records"] == 7
    assert profile["activity"]["fees"] == (6. if rich_result else None)
    result.equity.iloc[1] += 1.
    with pytest.raises(ValueError, match="finance hash mismatch: equity"):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("name", STREAMS)
def test_changed_values_in_any_retained_stream_fail(retained, name):
    result, original, kwargs, _ = retained
    item = getattr(result, name)
    item.iloc[1] += 1.
    with pytest.raises(ValueError, match="finance hash mismatch: " + name):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("name", STREAMS)
def test_missing_original_streams_fail_without_replay(retained, name):
    result, original, kwargs, _ = retained
    setattr(result, name, None)
    with pytest.raises(MissingInputs):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("name", ("fees", "funding", "margin"))
def test_unbound_new_streams_are_not_silently_trusted(retained, name):
    result, original, kwargs, _ = retained
    del original["finance"][name]
    with pytest.raises(ValueError, match="lacks original retained hash"):
        profile_selected_account(result, original, **kwargs)


def test_originally_absent_costs_remain_missing_not_zero(retained):
    result, original, kwargs, _ = retained
    for name in ("fees", "funding", "margin"):
        setattr(result, name, None)
        del original["finance"][name]
    activity = profile_selected_account(result, original, **kwargs)["activity"]
    assert activity["fees"] is None and activity["funding"] is None
    assert activity["fee_status"] == activity["funding_status"] == "NOT_SUPPLIED"


@pytest.mark.parametrize("clock", ("shift", "gap", "duplicate", "reverse", "timezone", "naive", "empty"))
def test_changed_equity_calendar_is_not_repaired(retained, clock):
    result, original, kwargs, _ = retained
    index = result.equity.index
    if clock == "shift":
        changed = index + pd.Timedelta(hours=1)
    elif clock == "gap":
        points = index.asi8.copy()
        points[3] += 1
        changed = pd.to_datetime(points, utc=True)
    elif clock == "duplicate":
        changed = index[:3].append(index[2:11])
    elif clock == "reverse":
        changed = index[::-1]
    elif clock == "timezone":
        changed = index.tz_convert("America/New_York")
    elif clock == "naive":
        changed = index.tz_localize(None)
    else:
        result.equity = result.equity.iloc[:0]
        changed = result.equity.index
    result.equity.index = changed
    with pytest.raises(ValueError, match="calendar"):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("name", ("positions", "fees", "funding", "margin"))
def test_changed_stream_calendar_fails_even_with_identical_values(retained, name):
    result, original, kwargs, _ = retained
    getattr(result, name).index = result.equity.index + pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="calendar/timezone"):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("field", ("initial_capital", "final_equity"))
def test_mismatched_capital_is_rejected(retained, field):
    result, original, kwargs, _ = retained
    setattr(result, field, getattr(result, field) + 1.)
    with pytest.raises(ValueError, match="capital|final equity"):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("field", ("execution_backend", "execution_contract"))
def test_retained_execution_clock_and_backend_are_checked_when_present(retained, field):
    result, original, kwargs, _ = retained
    original[field] = "another-clock-or-backend"
    with pytest.raises(ValueError, match="backend/clock"):
        profile_selected_account(result, original, **kwargs)


@pytest.mark.parametrize("change", (
    dict(environment_id="2020"), dict(account_policy="independent_reset_flat_v1"),
    dict(start_ns=None), dict(stop_ns=None), dict(finance={}), dict(closed_records=None),
    dict(closed_record_unit="campaigns"), dict(metric_contract=""),
))
def test_requests_missing_and_unsupported_observations_fail(retained, change):
    result, original, kwargs, _ = retained
    original.update(change)
    with pytest.raises(ValueError):
        profile_selected_account(result, original, **kwargs)


def test_stale_observation_scope_and_failed_current_rights_fail(retained):
    result, original, kwargs, _ = retained
    shifted = dict(original, start_ns=original["start_ns"] + DAY)
    with pytest.raises(ValueError, match="calendar"):
        profile_selected_account(result, shifted, **kwargs)
    for witness in (replace(kwargs["witness"], start_ns=original["start_ns"] + DAY),
                    replace(kwargs["witness"], end_ns=original["stop_ns"] - DAY),
                    replace(kwargs["witness"], manifest_id="unapproved"),
                    replace(kwargs["witness"], ready_ns=kwargs["access"].cutoff_ns + 1)):
        with pytest.raises(PermissionError):
            profile_selected_account(result, original, **dict(kwargs, witness=witness))
    with pytest.raises(PermissionError, match="diagnostic access"):
        profile_selected_account(result, original, **dict(kwargs, access=replace(kwargs["access"], purpose="selection")))


@pytest.mark.parametrize("alteration", ("future", "manifest", "role", "start", "end"))
def test_labels_have_their_own_current_full_scope_rights(retained, alteration):
    result, original, kwargs, label_witness = retained
    if alteration == "future":
        label_witness = replace(label_witness, ready_ns=kwargs["access"].cutoff_ns + 1)
    elif alteration == "manifest":
        label_witness = replace(label_witness, manifest_id="unauthorized-labels")
    elif alteration == "role":
        label_witness = replace(label_witness, role="holdout")
    elif alteration == "start":
        label_witness = replace(label_witness, start_ns=original["start_ns"] + DAY)
    else:
        label_witness = replace(label_witness, end_ns=original["stop_ns"] - DAY)
    with pytest.raises(PermissionError):
        profile_selected_account(result, original, state_views=(state(label_witness),), **kwargs)


def test_labels_cover_scored_scope_not_unobserved_preload(retained):
    result, original, kwargs, label_witness = retained
    kwargs["witness"] = replace(kwargs["witness"], start_ns=original["start_ns"] - DAY)
    payload = profile_selected_account(result, original, state_views=(state(label_witness),), **kwargs)
    assert payload["states"]["families"][0]["attribution"]["observed_days"] == 6
    assert payload["states"]["families"][0]["attribution"]["observed_span_days"] == 6.
    assert payload["witness"] == asdict(kwargs["witness"])
    assert payload["account_witness"]["start_ns"] == original["start_ns"]


@pytest.mark.parametrize("labels", ((0, 1), (0,) * 12))
def test_labels_must_match_observed_days_not_bars(retained, labels):
    result, original, kwargs, label_witness = retained
    with pytest.raises(ValueError, match="one per original observed UTC day"):
        profile_selected_account(result, original, state_views=(state(label_witness, labels=labels),), **kwargs)


@pytest.mark.parametrize("changes", (
    dict(labels=np.zeros(6)), dict(labels=FrozenBuffer.from_array("wrong", np.zeros(6))),
    dict(labels=FrozenBuffer.from_array("wrong", np.full(6, -2))),
    dict(labels=FrozenBuffer.from_array("wrong", np.zeros((6, 1), dtype=int))),
    dict(label_names=[(0, "mutable")]), dict(label_names=((0, "a"), (0, "b"))),
    dict(label_names=((0, ""),)), dict(label_names=((True, "bool"),)),
    dict(purpose="retrospective_fit"), dict(source_ref=""), dict(witness=None),
))
def test_stateview_rejects_untyped_mutable_and_invalid_labels(retained, changes):
    _, _, _, label_witness = retained
    with pytest.raises((TypeError, ValueError)):
        replace(state(label_witness), **changes)


def test_stateview_is_frozen_and_labels_are_bytes_owned(retained):
    _, _, _, label_witness = retained
    values = np.zeros(6, dtype=np.int64)
    view = state(label_witness, labels=values)
    values[:] = 5
    np.testing.assert_array_equal(view.labels.array(), np.zeros(6, dtype=int))
    with pytest.raises(FrozenInstanceError):
        view.name = "changed"
    with pytest.raises(ValueError):
        view.labels.array().setflags(write=True)


def test_duplicate_and_mutable_family_requests_are_rejected(retained):
    result, original, kwargs, label_witness = retained
    view = state(label_witness)
    for views in ((view, view), [view], ({"name": "not-a-view"},)):
        with pytest.raises(ValueError, match="WinnerStateView tuple"):
            profile_selected_account(result, original, state_views=views, **kwargs)


def test_no_variance_and_sparse_states_are_missing_not_favorable_sentinels(retained):
    result, original, kwargs, label_witness = retained
    result.equity[:] = 100.
    result.final_equity = original["final_equity"] = 100.
    original["finance"]["equity"] = array_identity(result.equity.to_numpy())
    view = state(label_witness, labels=(0, 0, 0, 1, 1, -1))
    payload = profile_selected_account(result, original, state_views=(view,), **kwargs)
    groups = {row["state"]: row for row in payload["states"]["families"][0]["groups"]}
    assert groups[0]["conditional_sharpe"]["estimator_status"] == "UNDEFINED"
    assert "zero return variance" in groups[0]["conditional_sharpe"]["reason"]
    assert groups[1]["conditional_sharpe"]["estimator_status"] == "INSUFFICIENT"
    for row in groups.values():
        assert row["conditional_sharpe"]["value"] is None
        assert row["conditional_sharpe"]["status"] == "MISSING" and row["conditional_sharpe"]["reason"]
        assert row["money_pnl"] == 0.
    assert payload["activity"]["concentration_status"] == "UNDEFINED_ZERO_ABSOLUTE_PNL"


def test_bankrupt_path_keeps_money_and_missing_conditional_statistics(retained):
    result, original, kwargs, label_witness = retained
    result.equity.iloc[3:] = 0.
    result.final_equity = original["final_equity"] = 0.
    original["finance"]["equity"] = array_identity(result.equity.to_numpy())
    payload = profile_selected_account(result, original, state_views=(state(label_witness, labels=(0,) * 6),), **kwargs)
    group, = payload["states"]["families"][0]["groups"]
    assert payload["activity"]["net_pnl"] == -100.
    assert group["conditional_sharpe"]["status"] == "MISSING"
    assert group["conditional_compound"] is None


def test_only_existing_authoritative_native_metadata_can_supply_fills(retained):
    result, original, kwargs, _ = retained
    result.metadata.update(backend="native_event", lifecycle_counters=dict(fill_count=13))
    activity = profile_selected_account(result, original, **kwargs)["activity"]
    assert activity["fills"]["status"] == "RECORDED" and activity["fills"]["value"] == 13
    assert activity["fills"]["metadata_field"] == "lifecycle_counters.fill_count"
    assert activity["campaigns"]["value"] is None
    result.metadata["backend"] = "synthetic_retained"
    assert profile_selected_account(result, original, **kwargs)["activity"]["fills"]["value"] is None


@pytest.mark.parametrize("count", (-1, True, 2.5))
def test_invalid_authoritative_fill_counts_fail(retained, count):
    result, original, kwargs, _ = retained
    result.metadata.update(backend="native_event", lifecycle_counters=dict(fill_count=count))
    with pytest.raises(ValueError, match="authoritative"):
        profile_selected_account(result, original, **kwargs)


def test_evidence_snapshots_are_immutable_and_report_has_no_raw_arrays(retained, monkeypatch):
    result, original, kwargs, label_witness = retained
    owner = accounts.account_profile
    seen = []

    def inspect(account, policy):
        assert isinstance(account.evidence, ExecutionEvidence)
        for array in account.evidence.arrays().values():
            assert not array.flags.writeable
            with pytest.raises(ValueError):
                array.setflags(write=True)
        seen.append(account.evidence.content_id)
        return owner(account, policy)

    monkeypatch.setattr(accounts, "account_profile", inspect)
    payload = profile_selected_account(result, original, state_views=(state(label_witness),), **kwargs)
    assert len(seen) == 2 and len(set(seen)) == 1

    def no_arrays(value):
        assert not isinstance(value, (np.ndarray, pd.Series, pd.DataFrame, bytes, FrozenBuffer, ExecutionEvidence))
        if isinstance(value, dict):
            for item in value.values():
                no_arrays(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                no_arrays(item)

    no_arrays(payload)
    assert Record.of(payload).data == json.loads(json.dumps(payload))


@pytest.mark.parametrize("name", STREAMS)
def test_live_finance_is_rehashed_after_profile_computation(retained, monkeypatch, name):
    result, original, kwargs, _ = retained
    owner = accounts.account_profile

    def mutate(account, policy):
        profile = owner(account, policy)
        getattr(result, name).iloc[1] += 1.
        return profile

    monkeypatch.setattr(accounts, "account_profile", mutate)
    with pytest.raises(ValueError, match="finance hash mismatch: " + name):
        profile_selected_account(result, original, **kwargs)


def test_original_observation_is_not_allowed_to_mutate_during_computation(retained, monkeypatch):
    result, original, kwargs, _ = retained
    owner = accounts.account_profile

    def mutate(account, policy):
        profile = owner(account, policy)
        original["closed_records"] += 1
        return profile

    monkeypatch.setattr(accounts, "account_profile", mutate)
    with pytest.raises(ValueError, match="changed during"):
        profile_selected_account(result, original, **kwargs)


def test_no_financial_policy_or_strategy_entry_is_used(retained, monkeypatch):
    from quantbt.mode5.evaluation import Mode5MetricPolicy

    def forbidden(*args, **kwargs):
        raise AssertionError("cold helper must not execute finance or a strategy")

    monkeypatch.setattr(Mode5MetricPolicy, "observe", forbidden)
    monkeypatch.setattr(Mode5MetricPolicy, "score", forbidden)
    result, original, kwargs, label_witness = retained
    result.strategy = result.run = result.backtest = forbidden
    assert profile_selected_account(result, original, state_views=(state(label_witness),), **kwargs)["activity"]["net_pnl"] == 15.
