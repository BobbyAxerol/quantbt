"""Inner availability, native candidate failures and unsupported boundaries."""

from dataclasses import replace
import importlib.util

import numpy as np
import pandas as pd
import pytest

from examples.wfo_reactive_samplers import (
    CandidateBatchStrategy, Factory, RECIPES, RANGES, configuration, execute, market,
)
from quantbt import CandidateWakePlansV1
from quantbt.core.wfo_contracts import strategy_fingerprint
from quantbt.optimization import NormalizedSearchSpace
from quantbt.walkforward import WalkForwardEngine, _build_inner_folds, _derive_fold_seed


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t02_inner_study_uses_inner_cutoff_and_fold_seed(recipe):
    config = replace(configuration(recipe, schedule="per_fold_causal", trials=4),
        optimization_mode="mode_1_decay", candidate_selection_metric="robust_decay",
        inner_split_frequency="weekly", inner_window_mode="rolling", inner_train_window="14D",
        inner_min_folds=2, min_train_bars=10, min_test_bars=3)
    engine = WalkForwardEngine(strategy=lambda: None, config=config, scorer=lambda: None)
    folds = engine.build_folds(market().index)
    result = execute(config=config)
    for fold, study in zip(folds, result.metadata["sampler_studies"], strict=True):
        inner = _build_inner_folds(fold, config)
        assert study["is_cutoff"] == max(f.train_end for f in inner) < fold.test_start
        assert study["seed"] == _derive_fold_seed(config.random_seed, fold.fold_id)
        assert study["study_id"] == fold.fold_id and study["attempts"] == 4


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t02_future_market_cannot_change_first_causal_search(recipe):
    config = configuration(recipe, schedule="per_fold_causal", trials=12)
    a = execute(config=config)
    future = market()
    future.loc[future.index >= pd.Timestamp("2024-03-01", tz="UTC"), ["open", "high", "low", "close"]] *= 1.5
    b = execute(config=config, data=future)
    assert a.params_by_fold[0] == b.params_by_fold[0]
    assert a.metadata["sampler_studies"][0]["rows"] == b.metadata["sampler_studies"][0]["rows"]
    assert a.metadata["sampler_studies"][0]["ask_tell_digest"] == b.metadata["sampler_studies"][0]["ask_tell_digest"]


@pytest.mark.parametrize("recipe", RECIPES)
def test_c03_t04_actual_native_local_error_prunes_only_failed_candidate(recipe, monkeypatch):
    original = CandidateBatchStrategy.on_wake_batch
    def fail_candidate(self, context, out):
        plans = dict(original(self, context, out).plans)
        for i in tuple(plans):
            if self.params[i]["qty"] > 1.:
                plans.pop(i)
        return CandidateWakePlansV1(plans)
    monkeypatch.setattr(CandidateBatchStrategy, "on_wake_batch", fail_candidate)
    seeds = tuple(dict(params=dict(qty=qty, hold=4, direction=1.),
        available_at="2023-01-01T00:00:00Z", space_identity=NormalizedSearchSpace(RANGES).identity,
        strategy_identity=strategy_fingerprint(Factory())) for qty in (2., .5))
    result = execute(config=replace(configuration(recipe), sampler_warm_start=seeds),
                     scheduler="throughput_batch_v1")
    rows = result.metadata["sampler_studies"][0]["rows"]
    assert rows[0]["state"] == "PRUNED" and rows[0]["reason"] == "NATIVE_CANDIDATE_ERROR"
    assert rows[0]["objective"] is None and rows[1]["state"] == "COMPLETE"
    assert result.params["qty"] <= 1.
    assert all(r["objective"] is None for r in rows if r["reason"] == "NATIVE_CANDIDATE_ERROR")


@pytest.mark.parametrize("scheduler", ["certified_sequential_v1", "throughput_batch_v1"])
@pytest.mark.parametrize("recipe", ["tpe_legacy", "tpe_multivariate_group"])
def test_c03_t04_formal_tpe_constraints_keep_genuine_objectives(recipe, scheduler):
    config = replace(configuration(recipe), result_constraints=lambda r: (4 - r.params["hold"],))
    result = execute(config=config, scheduler=scheduler)
    study = result.metadata["sampler_studies"][0]
    assert study["constraint_mode"] == "sampler" and result.params["hold"] >= 4
    assert any(r["reason"] == "RESULT_CONSTRAINT" for r in study["rows"])
    assert all(r["state"] == "COMPLETE" and np.isfinite(r["objective"][0])
               for r in study["rows"] if r["reason"] == "RESULT_CONSTRAINT")


def test_c03_t05_missing_cma_dependency_fails_before_strategy(monkeypatch):
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *args: None if name == "cmaes" else original(name, *args))
    monkeypatch.setattr(Factory, "prepare_reactive_wfo", lambda **_: pytest.fail("missing dependency reached alpha"))
    with pytest.raises(ImportError, match="cmaes==0.12.0"):
        execute("cmaes", scheduler="throughput_batch_v1")


@pytest.mark.parametrize("case", ["per_fold_batch", "process_batch", "batch_meta", "carry", "mode2"])
def test_c03_t07_existing_unsupported_boundaries_stay_closed(case, monkeypatch):
    config, scheduler, worker = configuration(), "throughput_batch_v1", "inprocess"
    if case == "per_fold_batch":
        config = configuration(schedule="per_fold_causal")
    elif case == "process_batch":
        worker = "process"
    elif case == "batch_meta":
        config = replace(configuration(schedule="per_fold_causal"), meta_selection=dict(mode="active"))
    elif case == "carry":
        config = replace(config, fold_account_policy="carry_position", fold_boundary_position_policy="carry")
    else:
        config = replace(config, optimization_mode="mode_2_sbb", candidate_selection_metric="robust_decay", scoring_backend="proxy")
    monkeypatch.setattr(Factory, "prepare_reactive_wfo", lambda **_: pytest.fail("unsupported route reached alpha"))
    with pytest.raises((ValueError, NotImplementedError)):
        execute(config=config, scheduler=scheduler, worker=worker)
