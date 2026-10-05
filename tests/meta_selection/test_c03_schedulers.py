"""Real W3/R3B financial runs and exact, declared sampler schedules."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import optuna
import pytest

from examples.wfo_reactive_samplers import Factory, RECIPES, RANGES, configuration, execute
from quantbt.backends.reactive_wfo_sampling import BATCH_CONTRACT
from quantbt.core.wfo_contracts import strategy_fingerprint
from quantbt.optimization import NormalizedSearchSpace, SamplerConfig
from quantbt.optimization.samplers import build_sampler
from quantbt.optimization.space import stable_params_key
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory


def assert_accounts(a, b):
    assert a.params == b.params and a.params_by_fold == b.params_by_fold
    for left, right in zip(a.fold_results, b.fold_results, strict=True):
        for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
            np.testing.assert_array_equal(getattr(left.result, field), getattr(right.result, field))


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_c03_t01_actual_four_recipes_and_same_schedule_seed(recipe, scheduler):
    a = execute(recipe, scheduler=scheduler)
    b = execute(recipe, scheduler=scheduler)
    assert_accounts(a, b)
    np.testing.assert_array_equal(a.trial_table.objective, b.trial_table.objective)
    sa, sb = a.metadata["sampler_studies"][0], b.metadata["sampler_studies"][0]
    for field in ("recipe", "kwargs", "seed", "states", "rows", "ask_tell_digest",
                  "qmc_dimension_order", "qmc_sequence_position"):
        assert sa[field] == sb[field]
    assert sa["attempts"] == sa["requested_trials"] == 16
    assert sa["states"] == {"COMPLETE": 16}
    assert sa["relative_proposal_trials"] > 0 if recipe != "tpe_legacy" else True
    assert sa["sampler_class"] == {"cmaes": "CmaEsSampler", "sobol": "QMCSampler"}.get(recipe, "TPESampler")
    assert a.metadata["sampler_scheduler"]["strategy_identity"] == strategy_fingerprint(Factory())
    if recipe == "sobol":
        assert sa["qmc_sequence_position"] == (12 if scheduler == "throughput_batch_v1" else 15)
        assert sa["qmc_dimension_order"] == ["qty", "hold"]
    if scheduler == "throughput_batch_v1":
        assert a.metadata["sampling_contract"] == BATCH_CONTRACT
        assert sa["batches"] == [list(range(i, i + 4)) for i in range(0, 16, 4)]
        assert sa["sequential_equivalent"] is False


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t01_direct_factory_sequential_proposals_exact(recipe):
    result = execute(recipe)
    observed = result.metadata["sampler_studies"][0]
    study = optuna.create_study(direction="maximize", sampler=build_sampler(SamplerConfig(name=recipe),
        seed=731, search_space=RANGES, objective_count=1))
    space = NormalizedSearchSpace(RANGES)
    for row in observed["rows"]:
        trial = study.ask()
        assert space.suggest(trial) == row["effective_params"]
        study.tell(trial, row["objective"][0])


def test_c03_t01_omitted_legacy_path_does_not_change():
    ranges = {"qty": (.5, 2.), "hold": (2, 8), "direction": 1.}
    legacy = execute(config=replace(configuration(), sampler_config=None), ranges=ranges)
    explicit = execute(ranges=ranges)
    assert "sampler_studies" not in legacy.metadata
    assert_accounts(legacy, explicit)
    np.testing.assert_array_equal(legacy.trial_table.objective, explicit.trial_table.objective)


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t02_real_meta_off_shadow_active_preserves_search_and_account(recipe):
    config = configuration(recipe, schedule="per_fold_causal", trials=12)
    off = execute(config=config)
    results = []
    for mode in ("shadow", "active"):
        cfg = replace(config, meta_selection=dict(mode=mode, native_batch_policy="require",
            min_matured_origins=1, label_observer=True))
        result = execute(config=cfg, meta_history=MetaHistoryContext(MetaHistory(), "C03", "BTC", "1D", "engineering"))
        assert result.metadata["meta_selection"]["observer_failures"] == 0
        assert result.metadata["meta_selection"]["observer_attempts"] > 0
        for baseline, observed in zip(off.metadata["sampler_studies"], result.metadata["sampler_studies"], strict=True):
            assert baseline["rows"] == observed["rows"]
            assert baseline["ask_tell_digest"] == observed["ask_tell_digest"]
        for record in result.metadata["meta_selection"]["records"]:
            assert record["selected_params"] == result.params_by_fold[record["fold_id"]]
            assert record["current_outer_oos_used_for_selection"] is False
        results.append(result)
    assert_accounts(off, results[0])


def process_matrix():
    import multiprocessing

    for recipe in RECIPES:
        a, b = execute(recipe), execute(recipe, worker="process")
        assert_accounts(a, b)
        assert a.metadata["sampler_studies"][0]["rows"] == b.metadata["sampler_studies"][0]["rows"]
    assert not multiprocessing.active_children()


def test_c03_t02_actual_safe_process_matrix():
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
        NUMBA_NUM_THREADS="1", PYTHONPATH=str(Path.cwd() / "src") + ":" + str(Path.cwd()))
    result = subprocess.run([sys.executable, "-c",
        "from tests.meta_selection.test_c03_schedulers import process_matrix; process_matrix()"],
        env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t03_batch_one_matches_sequential_on_same_geometry(recipe):
    a, b = execute(recipe), execute(recipe, scheduler="throughput_batch_v1", batch_size=1)
    assert_accounts(a, b)
    assert a.metadata["sampler_studies"][0]["rows"] == b.metadata["sampler_studies"][0]["rows"]
    assert a.metadata["sampler_studies"][0]["ask_tell_digest"] == b.metadata["sampler_studies"][0]["ask_tell_digest"]


def test_c03_t03_full_batch_order_and_partial_budget(monkeypatch):
    from quantbt.optimization.wfo_study import ObservedSampler

    events = []
    before, after = ObservedSampler.before_trial, ObservedSampler.after_trial
    def ask(self, study, trial):
        events.append(("ask", trial.number))
        return before(self, study, trial)
    def tell(self, study, trial, state, values):
        events.append(("tell", trial.number))
        return after(self, study, trial, state, values)
    monkeypatch.setattr(ObservedSampler, "before_trial", ask)
    monkeypatch.setattr(ObservedSampler, "after_trial", tell)
    result = execute("sobol", scheduler="throughput_batch_v1", config=configuration("sobol", trials=10))
    expected = []
    for ids in (range(4), range(4, 8), range(8, 10)):
        expected += [("ask", i) for i in ids] + [("tell", i) for i in ids]
    assert events == expected
    assert result.metadata["sampler_studies"][0]["attempts"] == 10


@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_c03_t04_duplicates_consume_budget_without_fake_complete(scheduler):
    result = execute(config=configuration(trials=9), scheduler=scheduler,
        ranges={"qty": [.5, 1.], "hold": 4, "direction": 1.})
    study = result.metadata["sampler_studies"][0]
    assert study["attempts"] == 9 and study["duplicate_attempts"] == 7
    assert study["states"] == {"COMPLETE": 2, "PRUNED": 7}
    assert all(row["objective"] is None for row in study["rows"] if row["state"] == "PRUNED")


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_c03_t04_constraints_actual_is_and_early_rejection(recipe, scheduler):
    seeds = tuple(dict(params=params, available_at="2023-01-01T00:00:00Z",
        space_identity=NormalizedSearchSpace(RANGES).identity, strategy_identity=strategy_fingerprint(Factory()))
        for params in (dict(qty=1.9, hold=7, direction=1.), dict(qty=.9, hold=2, direction=1.),
                       dict(qty=1., hold=4, direction=1.)))
    config = replace(configuration(recipe), sampler_config=SamplerConfig(name=recipe, constraint_mode="post_filter"),
        parameter_constraints=lambda params: (params["qty"] - 1.7,),
        result_constraints=lambda record: (3 - record.params["hold"],), sampler_warm_start=seeds)
    result = execute(config=config, scheduler=scheduler)
    study = result.metadata["sampler_studies"][0]
    assert study["attempts"] == 16
    early = [r for r in study["rows"] if r["reason"] == "PARAMETER_CONSTRAINT"]
    assert early and all(r["state"] == "PRUNED" and r["objective"] is None for r in early)
    assert result.params["qty"] <= 1.7 and result.params["hold"] >= 3
    for row in study["rows"]:
        if row["reason"] == "RESULT_CONSTRAINT":
            assert row["state"] == "COMPLETE" and np.isfinite(row["objective"][0])


def test_c03_t04_all_parameter_infeasible_never_reaches_native(monkeypatch):
    from quantbt.backends.reactive_wfo_batch_selection import ReactiveWfoBatchSelectionMixinV1

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid parameter reached native score")
    monkeypatch.setattr(ReactiveWfoBatchSelectionMixinV1, "_score_r3b_stage", forbidden)
    with pytest.raises(ValueError, match="no valid|no candidates|no completed"):
        execute(scheduler="throughput_batch_v1", config=replace(configuration(), parameter_constraints=lambda _: (1.,)))


@pytest.mark.parametrize("kind", ["raise", "cancel"])
def test_c03_t04_batch_abort_finishes_running_trials(kind, monkeypatch):
    from quantbt.backends.reactive_wfo import ReactivePreparedWfoRuntimeV1
    from quantbt.core.runtime_governance import RuntimeCanceledError

    owners = []
    def abort(self, **kwargs):
        owners.append(self)
        if kind == "cancel":
            self.cancel()
            self._check_canceled()
        raise RuntimeError("C03 test callback abort")
    monkeypatch.setattr(ReactivePreparedWfoRuntimeV1, "_score_r3b_stage", abort)
    with pytest.raises((RuntimeError, RuntimeCanceledError)):
        execute(scheduler="throughput_batch_v1")
    study = owners[0]._candidate_batch_metadata["sampler_study"]
    assert study["states"] == {"FAIL": 4} and owners[0]._active_candidate_scheduler is None


def test_c03_t04_early_stop_finishes_already_asked_batch():
    result = execute(config=replace(configuration(trials=32), optuna_early_stopping=1),
                     scheduler="throughput_batch_v1")
    study = result.metadata["sampler_studies"][0]
    assert study["attempts"] % 4 == 0 and study["attempts"] < 32
    assert "RUNNING" not in study["states"]


@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
@pytest.mark.parametrize("recipe", ["tpe_multivariate_group", "cmaes"])
def test_c03_t05_conditional_effective_branch_geometry(recipe, scheduler):
    ranges = {**RANGES, "enabled": {"kind": "boolean"},
              "extra": {"kind": "integer", "low": 1, "high": 3, "active_if": {"enabled": True}}}
    cfg = replace(configuration(recipe), sampler_config=SamplerConfig(name=recipe,
                  mixed_space_policy="explicit_independent" if recipe == "cmaes" else "reject"))
    result = execute(config=cfg, ranges=ranges, scheduler=scheduler)
    study = result.metadata["sampler_studies"][0]
    for row in study["rows"]:
        assert ("extra" in row["effective_params"]) is row["effective_params"]["enabled"]
    assert study["independent_sample_calls"].get("enabled", 0) > 0
    if recipe == "cmaes":
        assert "enabled" not in study["joint_numeric_candidates"]


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_c03_t05_log_step_fixed_geometry(recipe, scheduler):
    ranges = {"qty": {"kind": "float", "low": .5, "high": 2., "log": True},
              "hold": {"kind": "integer", "low": 2, "high": 8, "step": 2}, "direction": 1.}
    cfg = replace(configuration(recipe), sampler_config=SamplerConfig(name=recipe,
                  kwargs={"with_margin": True} if recipe == "cmaes" else {}))
    result = execute(config=cfg, ranges=ranges, scheduler=scheduler)
    for row in result.metadata["sampler_studies"][0]["rows"]:
        assert row["effective_params"]["hold"] % 2 == 0
        assert row["effective_params"]["direction"] == 1.


@pytest.mark.parametrize("case", ["sobol_conditional", "cma_category", "centroid", "seed", "kwargs", "constraint_policy"])
@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_c03_t05_unsupported_policy_preflight_before_strategy(case, scheduler, monkeypatch):
    cfg, ranges = configuration(), dict(RANGES)
    if case == "sobol_conditional":
        cfg = configuration("sobol")
        ranges.update(enabled={"kind": "boolean"},
            extra={"kind": "integer", "low": 1, "high": 3, "active_if": {"enabled": True}})
    elif case == "cma_category":
        cfg = configuration("cmaes")
        ranges["direction"] = [-1., 1.]
    elif case == "centroid":
        cfg = replace(cfg, flat_selector="centroid")
        ranges["direction"] = [-1., 1.]
    elif case == "seed":
        cfg = replace(cfg, sampler_config=SamplerConfig(kwargs={"seed": 99}))
    elif case == "kwargs":
        cfg = replace(cfg, sampler_config=SamplerConfig(kwargs={"unrecognized": 1}))
    else:
        cfg = replace(configuration("sobol"), result_constraints=lambda _: (0.,))
    def forbidden(*args, **kwargs):
        raise AssertionError("bad policy reached user preparation")
    monkeypatch.setattr(Factory, "prepare_reactive_wfo", forbidden)
    with pytest.raises((ValueError, TypeError), match="sampler|SAMPLER|seed"):
        execute(config=cfg, ranges=ranges, scheduler=scheduler)


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
def test_c03_t06_params_only_warm_start_rescored_inside_budget(recipe, scheduler):
    seed = dict(params={"qty": 1., "hold": 4, "direction": 1.}, available_at="2023-01-01T00:00:00Z",
        space_identity=NormalizedSearchSpace(RANGES).identity, strategy_identity=strategy_fingerprint(Factory()))
    cfg = replace(configuration(recipe), sampler_warm_start=(seed,))
    result = execute(config=cfg, scheduler=scheduler)
    study = result.metadata["sampler_studies"][0]
    assert study["attempts"] == 16 and study["warm_start_attempts"] == 1
    assert study["rows"][0]["effective_params"] == seed["params"]
    assert study["rows"][0]["objective"] is not None


@pytest.mark.parametrize("mutation", ["future", "schema", "strategy", "old_score", "duplicate"])
def test_c03_t06_bad_warm_start_fails_before_strategy(mutation, monkeypatch):
    seed = dict(params={"qty": 1., "hold": 4, "direction": 1.}, available_at="2023-01-01T00:00:00Z",
        space_identity=NormalizedSearchSpace(RANGES).identity, strategy_identity=strategy_fingerprint(Factory()))
    seeds = [seed]
    if mutation == "future":
        seed["available_at"] = "2026-01-01T00:00:00Z"
    elif mutation == "schema":
        seed["space_identity"] = "wrong"
    elif mutation == "strategy":
        seed["strategy_identity"] = "wrong"
    elif mutation == "old_score":
        seed["score"] = 99.
    else:
        seeds.append(dict(seed))
    monkeypatch.setattr(Factory, "prepare_reactive_wfo", lambda **_: pytest.fail("bad seed reached preparation"))
    with pytest.raises(ValueError, match="warm_start"):
        execute(config=replace(configuration(), sampler_warm_start=tuple(seeds)), scheduler="throughput_batch_v1")


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t07_frozen_pool_fixed_matrix_original_native_scores(recipe):
    adaptive = execute(recipe, scheduler="throughput_batch_v1")
    matrix = [r["effective_params"] for r in adaptive.metadata["sampler_studies"][0]["rows"] if r["state"] == "COMPLETE"]
    fixed = execute(config=replace(configuration(recipe), sampler_config=None), scheduler="throughput_batch_v1",
        candidate_matrix=matrix, ranges={"qty": (.5, 2.), "hold": (2, 8), "direction": 1.})
    a = {stable_params_key(r.params): r.objective for r in adaptive.trial_table.itertuples() if not r.pruned}
    b = {stable_params_key(r.params): r.objective for r in fixed.trial_table.itertuples() if not r.pruned}
    assert a == b
    assert fixed.metadata["sampling_contract"] == "fixed_candidate_matrix_r3b_v1"
    assert "sampler_studies" not in fixed.metadata
    assert_accounts(adaptive, fixed)


def test_c03_t07_fixed_matrix_cannot_silently_ignore_sampler(monkeypatch):
    monkeypatch.setattr(Factory, "prepare_reactive_wfo", lambda **_: pytest.fail("invalid matrix reached preparation"))
    with pytest.raises(ValueError, match="fixed candidate_matrix has no sampler"):
        execute(scheduler="throughput_batch_v1", candidate_matrix=[dict(qty=1., hold=4, direction=1.)])
