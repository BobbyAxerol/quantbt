from dataclasses import replace
import copy
import pickle

import numpy as np
import pytest

from quantbt.mode5.dossier.records import Record
from quantbt.mode5.runtime import Mode5NoSelectionError
from public_fixtures import public_setup


@pytest.mark.parametrize("selector", ["full_dro_cvar", "full_sam_basin", "full_pareto_chebyshev"])
def test_actual_public_selection_and_replay(tmp_path, selector):
    endpoint, frame, ranges, calibration = public_setup(tmp_path, selector=selector)
    result = endpoint.backtest(data=frame, param_ranges=ranges)
    meta = result.metadata["walk_forward"]["mode5_diagnostics_first"]
    assert meta["status"] == "SELECTED_REPLAY_VERIFIED"
    assert meta["decision"]["requested_selector"] == selector
    assert meta["sampler"]["attempts"] == 8
    assert meta["sampler"]["kwargs"]["seed"] == 731
    assert meta["meta_learning_activated"] is False
    assert result.metadata["walk_forward"]["validation_claim"] == "none_full_sample_calibration"
    assert meta["selected_params_digest"] == meta["decision"]["chosen_params_digest"]
    assert meta["selected_audit"][0]["finance"]["equity"]
    raw = result.metadata["walk_forward"]["best_trial"]["mean_is_sharpe"]
    value = result.metadata["walk_forward"]["best_trial"]["objective"]
    assert raw != value
    assert calibration.plan.record.data["deployment_authorized"] is False


def test_adaptive_requires_explicit_researcher_choice(tmp_path):
    e, frame, ranges, _ = public_setup(tmp_path, requested_selector="full_alpha_adaptive_invariant")
    meta = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
    assert meta["decision"]["resolved_selector"] == "full_dro_cvar"
    assert meta["decision"]["advisory"]["automatic_routing"] is False


@pytest.mark.parametrize("mutation", ["data", "range", "fee", "seed", "budget", "sampler"])
def test_stale_binding_rejected_before_strategy(tmp_path, mutation):
    e, frame, ranges, _ = public_setup(tmp_path)
    if mutation == "data":
        frame = frame.copy()
        frame.iloc[-1, frame.columns.get_loc("close")] += 1
    elif mutation == "range":
        ranges = {"period": (6, 30, 1)}
    elif mutation == "fee":
        e.config = replace(e.config, fee=.001)
    else:
        cfg = e.config.walkforward_config
        if mutation == "seed":
            cfg = replace(cfg, random_seed=732)
        elif mutation == "budget":
            cfg = replace(cfg, optuna_trials=9)
        else:
            from quantbt.optimization import SamplerConfig
            cfg = replace(cfg, sampler_config=SamplerConfig("sobol", constraint_mode="post_filter"))
        e.config = replace(e.config, walkforward_config=cfg)
    with pytest.raises(ValueError, match="differs|stale"):
        e.backtest(data=frame, param_ranges=ranges)


def test_no_selection_never_forces_best_numerical_candidate(tmp_path):
    e, frame, ranges, _ = public_setup(tmp_path, min_daily=1000)
    with pytest.raises(Mode5NoSelectionError) as caught:
        e.backtest(data=frame, param_ranges=ranges)
    meta = caught.value.mode5_metadata
    assert meta["decision"]["chosen_candidate"] is None
    assert all("INSUFFICIENT_SUPPORT" in r["reasons"] for r in meta["decision"]["component_rows"])


@pytest.mark.parametrize("sampler", ["tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"])
def test_actual_inherited_sampler_and_no_meta(tmp_path, sampler):
    e, frame, ranges, _ = public_setup(tmp_path, sampler_name=sampler)
    meta = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
    assert meta["sampler"]["recipe"] == sampler
    assert not meta["meta_learning_activated"]


@pytest.mark.parametrize("batch_size", [1, 3])
def test_ask_tell_schedule_deterministic_and_distinct(tmp_path, batch_size):
    out = []
    for i in range(2):
        root = tmp_path / str(i)
        root.mkdir()
        e, frame, ranges, _ = public_setup(root, batch_size=batch_size)
        m = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
        out.append([(r["effective_params"], r["state"], r.get("objective")) for r in m["trial_ledger"]])
        assert m["candidate_sequence_equivalent_to_sequential"] is (batch_size == 1)
    assert out[0] == out[1]


def test_metadata_record_copies_are_immutable(tmp_path):
    _, _, _, c = public_setup(tmp_path)
    for b in (copy.deepcopy(c.binding), pickle.loads(pickle.dumps(c.binding))):
        data = b.data
        data["metrics"]["dd_weight"] = 100
        assert b == c.binding


def test_authorized_multi_environment_reset_diagnostics(tmp_path):
    e, frame, ranges, _ = public_setup(tmp_path, two_windows=True)
    m = e.backtest(data=frame, param_ranges=ranges).metadata["walk_forward"]["mode5_diagnostics_first"]
    assert len(m["selected_audit"]) == 2
    assert all(r["daily_count"] == 16 for r in m["selected_audit"])
