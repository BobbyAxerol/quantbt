"""C04-T01/T02/T05: genuine reconstruction beyond startup, not seed-only reload."""

from dataclasses import replace
import json

import optuna
import pytest

from quantbt.optimization import SamplerConfig
from quantbt.optimization.continuation import ContinuationConfig, ContinuationError, ExactStudySession
from quantbt.optimization.wfo_study import WfoSamplerStudy

RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")
RANGES = {"z": {"kind": "float", "low": -2.0, "high": 2.0},
          "a": {"kind": "integer", "low": 1, "high": 9},
          "fixed": {"kind": "fixed", "value": 2}}
BINDING = {key: key + ":reviewed-v1" for key in (
    "market", "calendar", "accounting", "objective", "schedule",
    "meta_snapshot", "meta_basis", "meta_task")}


def config(recipe="tpe_legacy", **kwargs):
    return ContinuationConfig(sampler_config=SamplerConfig(name=recipe), ranges=RANGES,
                              seed=731, budget=64, cutoff="2024-01-01T00:00:00Z",
                              strategy_identity="fixture-alpha-v1", **kwargs)


def advance(session, count, *, outcomes=False):
    for _ in range(count):
        proposal = session.ask()
        n = proposal.number
        if proposal.duplicate and session.config.duplicate_policy == "prune":
            session.tell(n, state="PRUNED")
            continue
        value = 4.0 - (proposal.effective["z"] - 0.5)**2 - proposal.effective["a"] / 10
        if outcomes:
            session.report(n, value, 0)
            if session.should_prune(n):
                session.tell(n, state="PRUNED", reason="PRUNER")
            elif n % 11 == 7:
                session.tell(n, state="FAIL", reason="DECLARED_EVALUATOR_FAILURE")
            else:
                session.tell(n, value, constraints=(1.0 if n % 5 == 0 else -1.0,))
        else:
            session.tell(n, value)


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("split", [0, 1, 17, 39])
def test_c04_t01_exact_sampler_trajectory_and_winner(recipe, split):
    cfg = config(recipe)
    full = ExactStudySession(cfg, binding=BINDING)
    advance(full, 56)
    partial = ExactStudySession(cfg, binding=BINDING)
    advance(partial, split)
    text, sha = partial.dumps()
    resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    advance(resumed, 56 - split)
    assert full.witness() == resumed.witness()
    assert full.best_trial.params == resumed.best_trial.params
    assert full.best_trial.number == resumed.best_trial.number
    assert full.best_trial.value == resumed.best_trial.value
    assert full.dumps() == resumed.dumps()


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t05_matches_existing_shared_sampler_public_proposals(recipe):
    cfg = config(recipe)
    owned = ExactStudySession(cfg, binding=BINDING)
    bridge = WfoSamplerStudy(cfg.sampler_config, cfg.ranges, seed=cfg.seed, budget=cfg.budget,
                             cutoff=cfg.cutoff, strategy_identity=cfg.strategy_identity, stage=cfg.stage)
    study = optuna.create_study(sampler=bridge.sampler(), direction="maximize", pruner=optuna.pruners.NopPruner())
    for _ in range(32):
        proposal = owned.ask()
        trial = study.ask()
        requested, effective = bridge.suggest(trial)
        assert (proposal.requested, proposal.effective) == (requested, effective)
        if proposal.duplicate:
            owned.tell(proposal.number, state="PRUNED")
            bridge.constraints(trial, ())
            trial.set_user_attr("qms_rejection_reason", "DUPLICATE_EFFECTIVE_PARAMS")
            study.tell(trial, state=optuna.trial.TrialState.PRUNED)
        else:
            value = float(effective["z"] + effective["a"])
            owned.tell(proposal.number, value)
            bridge.constraints(trial, ())
            study.tell(trial, value)
    assert owned._bridge.observed.events == bridge.observed.events
    assert owned._bridge.metadata(owned._study)["ask_tell_digest"] == bridge.metadata(study)["ask_tell_digest"]


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t02_constraints_states_median_pruner_replay(recipe):
    cfg = config(recipe, result_constraints=True,
                 pruner={"name": "median", "kwargs": {"n_startup_trials": 3}})
    if recipe in {"cmaes", "sobol"}:
        cfg = replace(cfg, sampler_config=SamplerConfig(name=recipe, constraint_mode="post_filter"))
    full = ExactStudySession(cfg, binding=BINDING)
    advance(full, 56, outcomes=True)
    partial = ExactStudySession(cfg, binding=BINDING)
    advance(partial, 21, outcomes=True)
    text, sha = partial.dumps()
    resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    advance(resumed, 35, outcomes=True)
    assert resumed.witness() == full.witness()
    assert {trial.state.name for trial in full.trials} == {"COMPLETE", "PRUNED", "FAIL"}


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t02_batch_order_not_replaced_with_sequential_order(recipe):
    cfg = config(recipe)
    def batches(session, count):
        for _ in range(count):
            proposals = [session.ask() for _ in range(4)]
            with pytest.raises(ContinuationError, match="RUNNING"):
                session.dumps()
            for p in reversed(proposals):
                if p.duplicate:
                    session.tell(p.number, state="PRUNED")
                else:
                    session.tell(p.number, float(p.effective["z"] - p.effective["a"]))
    full = ExactStudySession(cfg, binding=BINDING)
    batches(full, 12)
    partial = ExactStudySession(cfg, binding=BINDING)
    batches(partial, 5)
    text, sha = partial.dumps()
    resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    batches(resumed, 7)
    assert full.witness() == resumed.witness()


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t02_warm_start_waiting_queue_and_early_stop(recipe):
    cfg = config(recipe, early_stopping={"patience": 5, "min_delta": 0.1, "min_trials": 7})
    warm = dict(params={"z": 0.4, "a": 2, "fixed": 2}, available_at="2023-01-01T00:00:00Z",
                space_identity=cfg.bridge().space.identity, strategy_identity=cfg.strategy_identity)
    cfg = replace(cfg, warm_start=(warm,))
    full = ExactStudySession(cfg, binding=BINDING)
    waiting, sha = full.dumps()
    resumed = ExactStudySession.loads(waiting, config=cfg, binding=BINDING, expected_digest=sha)
    for i in range(7):
        for session in (full, resumed):
            p = session.ask()
            session.tell(p.number, state="PRUNED") if p.duplicate else session.tell(p.number, 1.0)
        if i == 2:
            text, sha = resumed.dumps()
            resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    assert full.witness() == resumed.witness()
    assert full.stopped and resumed.stopped
    with pytest.raises(ContinuationError, match="stopped"):
        resumed.ask()


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t01_mixed_space_reconstruction(recipe):
    ranges = {**RANGES, "switch": {"kind": "categorical", "choices": ["on", "off"]}}
    if recipe.startswith("tpe"):
        ranges["extra"] = {"kind": "float", "low": 0.001, "high": 1.0, "log": True,
                           "active_if": {"switch": ["on"]}}
    cfg = replace(config(recipe), ranges=ranges,
                  sampler_config=SamplerConfig(name=recipe, mixed_space_policy="explicit_independent"))
    full, partial = (ExactStudySession(cfg, binding=BINDING) for _ in range(2))
    advance(full, 40)
    advance(partial, 19)
    text, sha = partial.dumps()
    resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    advance(resumed, 21)
    assert resumed.witness() == full.witness()
    assert list(json.loads(text)["payload"]["config"]["ranges"][0]) == ["z", cfg.bridge().ranges["z"]]


def test_c04_t02_duplicate_cache_and_terminal_failure_reconstruction():
    cfg = replace(config(), ranges={"z": {"kind": "fixed", "value": 1}})
    session = ExactStudySession(cfg, binding=BINDING)
    first = session.ask()
    session.tell(first.number, state="FAIL", reason="CANCELLED_EXPLICITLY")
    text, sha = session.dumps()
    resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    duplicate = resumed.ask()
    assert duplicate.duplicate
    with pytest.raises(ContinuationError, match="duplicate"):
        resumed.tell(duplicate.number, 0.0)
    resumed.tell(duplicate.number, state="PRUNED")
    assert resumed.trials[-1].user_attrs["qms_rejection_reason"] == "DUPLICATE_EFFECTIVE_PARAMS"


def test_c04_t01_cma_margin_and_log_step_space():
    cfg = replace(config("cmaes"), sampler_config=SamplerConfig(name="cmaes", kwargs={"with_margin": True}),
                  ranges={"z": {"kind": "float", "low": 0.001, "high": 2.0, "log": True},
                          "a": {"kind": "integer", "low": 1, "high": 9, "step": 2}})
    full, partial = (ExactStudySession(cfg, binding=BINDING) for _ in range(2))
    advance(full, 40)
    advance(partial, 23)
    text, sha = partial.dumps()
    resumed = ExactStudySession.loads(text, config=cfg, binding=BINDING, expected_digest=sha)
    advance(resumed, 17)
    assert resumed.witness() == full.witness()


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t05_seed_only_reconstruction_is_not_accepted_as_resume(recipe):
    cfg = config(recipe)
    session = ExactStudySession(cfg, binding=BINDING)
    advance(session, 23)
    next_proposal = session.ask()
    seed_only = ExactStudySession(cfg, binding=BINDING).ask()
    assert next_proposal.effective != seed_only.effective


def test_c04_t03_failed_suggestion_poisoned_not_checkpointable(monkeypatch):
    session = ExactStudySession(config(), binding=BINDING)
    monkeypatch.setattr(session._bridge, "suggest", lambda _: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError, match="injected"):
        session.ask()
    with pytest.raises(ContinuationError, match="uncommitted"):
        session.dumps()
