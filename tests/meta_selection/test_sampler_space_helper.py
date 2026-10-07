"""SH-T01..T05: explicit semantics, no helper dependency, real WFO parity."""

from copy import deepcopy
from dataclasses import replace
from importlib import import_module
import json
import random

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization import (NormalizedSearchSpace, SamplerConfig, build_sampler,
                                  prepare_sampler_space, suggest_params)
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.history import MetaHistory
from tools.qms01_baseline import endpoint, market


def test_sh_t01_regular_integer_declaration_preserves_exact_support():
    original = {"window": [12, 4, 8], "threshold": (0.001, 0.02)}
    before = deepcopy(original)
    plan = prepare_sampler_space(original, numeric_parameters=("window",))
    spec = NormalizedSearchSpace(plan.param_ranges).by_name["window"]
    assert set(range(spec.low, spec.high + 1, spec.step)) == set(original["window"])
    assert plan.assessment.static_numeric == ("window", "threshold")
    assert plan.assessment.numeric_declarations == ("window",)
    assert original == before
    assert plan.decode({"window": np.int64(8), "threshold": 0.01}) == {"window": 8, "threshold": 0.01}
    assert type(plan.decode({"window": np.int64(8), "threshold": 0.01})["window"]) is int
    with pytest.raises(ValueError, match="violates schema"):
        plan.decode({"window": 8.0, "threshold": 0.01})
    with pytest.raises(ValueError, match="violates schema"):
        plan.decode({"window": 6, "threshold": 0.01})


@pytest.mark.parametrize("values", [[True, False], ["cross", "direction"], [1, 3, 9],
                                   [1, 1, 2], [0.1, 0.2, 0.3]])
def test_sh_t01_no_fake_ordinal_or_support_expansion(values):
    with pytest.raises(ValueError):
        prepare_sampler_space({"choice": values, "x": (-1.0, 1.0)}, numeric_parameters=["choice"])


@pytest.mark.parametrize("numeric", ["x", ["missing"], ["x", "x"], [1]])
def test_sh_t01_invalid_numeric_declarations(numeric):
    with pytest.raises(ValueError):
        prepare_sampler_space({"x": (1, 10)}, numeric_parameters=numeric)


def test_sh_t01_fixed_and_custom_numeric_log_step_semantics():
    plan = prepare_sampler_space(
        {"window": [4, 8, 12], "rate": [0.01, 0.1]},
        parameter_overrides={"rate": {"kind": "float", "low": 0.01, "high": 0.1, "log": True}},
        numeric_parameters=["window"], fixed_params={"degree": 2, "use_atr": True},
    )
    assert plan.decode({"window": 8, "rate": 0.02}) == dict(window=8, rate=0.02, degree=2, use_atr=True)
    assert plan.assessment.fixed == ("degree", "use_atr")
    assert plan.assessment.schema_overrides == ("rate",)
    assert NormalizedSearchSpace(plan.param_ranges).by_name["rate"].log is True
    with pytest.raises(ValueError, match="unknown"):
        prepare_sampler_space({"x": (1, 10)}, parameter_overrides={"typo": (2, 5)})


def test_sh_t01_conditions_declared_not_inferred_and_inactive_values_omitted():
    plan = prepare_sampler_space(
        {"use_atr": [True, False], "length": (4, 20), "threshold": (0.01, 0.1)},
        active_if={"length": {"use_atr": True}},
        sampler_config={"name": "tpe_multivariate_group"},
    )
    assert plan.decode({"use_atr": False, "length": 19, "threshold": 0.02}) == dict(use_atr=False, threshold=0.02)
    assert plan.assessment.conditional_numeric == ("length",)
    assert plan.assessment.categorical == ("use_atr",)
    assert plan.assessment.caller_sampler_override is True
    with pytest.raises(ValueError, match="missing active"):
        plan.decode({"use_atr": True, "threshold": 0.02})
    with pytest.raises(ValueError, match="prior parent"):
        prepare_sampler_space({"length": (4, 20), "use_atr": [True, False]},
                              active_if={"length": {"use_atr": True}})


def test_sh_t03_incompatible_raise_or_explicit_compatible_recommendation():
    ranges = {"window": (4, 20), "kind": ["cross", "direction"]}
    with pytest.raises(ValueError, match="SAMPLER_HELPER_INCOMPATIBLE"):
        prepare_sampler_space(ranges)
    plan = prepare_sampler_space(ranges, on_incompatible="recommend")
    assert plan.param_ranges == ranges
    assert plan.assessment.resolution == "RECOMMENDED_ALTERNATIVE"
    assert plan.sampler_config.name == "tpe_legacy"
    assert "categorical" in plan.assessment.requested_issue
    with pytest.raises(ValueError):
        prepare_sampler_space(ranges, on_incompatible="recommend", sampler_config={"name": "cmaes"})


@pytest.mark.parametrize("recipe", ["cmaes", "sobol", "tpe_legacy", "tpe_multivariate_group"])
def test_sh_t03_geometry_uses_actual_shared_factory(recipe):
    ranges = {"window": (4, 20), "threshold": (0.01, 0.1)}
    plan = prepare_sampler_space(ranges, preferred_sampler=recipe)
    actual = build_sampler(plan.sampler_config, seed=731, search_space=plan.param_ranges, objective_count=1)
    assert isinstance(actual, optuna.samplers.BaseSampler)
    assert plan.assessment.resolution == "COMPATIBLE"


def test_sh_t03_mixed_cma_not_encoded_or_advertised_joint():
    ranges = {"x": (-1.0, 1.0), "y": (-1.0, 1.0), "kind": ["cross", "direction"], "flag": [True, False]}
    plan = prepare_sampler_space(ranges, sampler_config={"name": "cmaes", "mixed_space_policy": "explicit_independent"})
    assert plan.param_ranges == ranges
    assert plan.assessment.categorical == ("kind", "flag")
    assert any("independently" in s for s in plan.assessment.notes)
    assert plan.decode(dict(x=0, y=0, kind="cross", flag=False))["flag"] is False
    with pytest.raises(ValueError, match="warnings"):
        prepare_sampler_space(ranges, sampler_config={"name": "cmaes", "mixed_space_policy": "explicit_independent",
                                                       "kwargs": {"warn_independent_sampling": False}})


def test_sh_t03_conditional_sobol_override_is_existing_policy():
    plan = prepare_sampler_space(
        {"flag": [True, False], "x": {"kind": "integer", "low": 4, "high": 20, "active_if": {"flag": True}}},
        sampler_config={"name": "sobol", "sobol_policy": "conditional_numeric_latent_v1"},
    )
    assert plan.sampler_config.sobol_policy == "conditional_numeric_latent_v1"
    assert plan.decode({"flag": False, "x": 10}) == {"flag": False}


def test_sh_t02_defensive_copies_and_no_global_rng_or_sampler_work(monkeypatch):
    import quantbt.optimization.samplers as factory
    monkeypatch.setattr(factory, "build_sampler", lambda *a, **k: pytest.fail("helper constructs sampler"))
    py = random.getstate()
    np_state = deepcopy(np.random.get_state())
    config = {"name": "tpe_multivariate_group", "kwargs": {"n_startup_trials": 20}}
    ranges = {"x": (0.0, 1.0), "kind": ["a", "b"]}
    original = deepcopy((ranges, config))
    plan = prepare_sampler_space(ranges, sampler_config=config)
    exported = plan.param_ranges
    exported["kind"].append("corrupt")
    returned = plan.sampler_config
    returned.kwargs["n_startup_trials"] = 999
    base = {"meta_selection": {"mode": "active", "lambda_reg": 10.0}, "is_subperiods": 3}
    merged = plan.optimization_config(base)
    merged["meta_selection"]["mode"] = "off"
    assert base["meta_selection"]["mode"] == "active"
    assert plan.param_ranges == original[0] and config == original[1]
    assert plan.sampler_config.kwargs["n_startup_trials"] == 20
    assert random.getstate() == py
    after = np.random.get_state()
    assert np_state[0] == after[0] and np_state[2:] == after[2:]
    np.testing.assert_array_equal(np_state[1], after[1])
    json.dumps(plan.assessment.metadata(), allow_nan=False)


@pytest.mark.parametrize("recipe", ["cmaes", "tpe_legacy"])
def test_sh_t04_same_normalized_manual_and_helper_proposals_and_objective(recipe):
    ranges = {"x": [1, 3, 5, 7], "y": (-2.0, 2.0)}
    plan = prepare_sampler_space(ranges, preferred_sampler=recipe, numeric_parameters=["x"])
    manual = {"x": {"kind": "integer", "low": 1, "high": 7, "step": 2}, "y": (-2.0, 2.0)}
    sequences = []
    for space, config in [(manual, SamplerConfig(name=recipe)), (plan.param_ranges, plan.sampler_config)]:
        study = optuna.create_study(direction="maximize", sampler=build_sampler(config, seed=731, search_space=space, objective_count=1))
        rows = []
        def objective(trial):
            p = suggest_params(trial, space)
            value = -(p["x"] - 3) ** 2 - (p["y"] - 0.2) ** 2
            rows.append((p, value))
            return value
        study.optimize(objective, n_trials=32)
        sequences.append(rows)
    assert sequences[0] == sequences[1]


@pytest.mark.parametrize("meta_mode", ["off", "shadow", "active"])
def test_sh_t05_public_meta_helper_is_optional_and_does_not_change_actual_results(meta_mode, monkeypatch):
    # Both paths must observe the same already-loaded math libraries, including
    # the OpenMP runtime lazily loaded by plateau clustering during the first run.
    import_module("sklearn.cluster")
    import_module("numba").get_num_threads()
    # Freeze only instrumentation/availability clocks for exact provenance;
    # execute the real financial scorer, history, learner and selection.
    import quantbt.optimization.meta_selection.runtime as runtime
    monkeypatch.setattr(runtime, "perf_counter", lambda: 0.0)
    original_task = runtime.PublicMetaRuntime.task_from_pool
    monkeypatch.setattr(runtime.PublicMetaRuntime, "task_from_pool",
                        lambda self, *args: replace(original_task(self, *args),
                                                  wall_generated_at=pd.Timestamp("2026-01-01", tz="UTC")))
    config = SamplerConfig(name="tpe_legacy")
    plan = prepare_sampler_space({"window": (3, 31, 2)}, sampler_config=config)
    results = []
    for helper in [False, True]:
        old = endpoint(retention="none")
        wf = replace(old.config.walkforward_config,
                     sampler_config=plan.sampler_config if helper else config,
                     meta_selection={"mode": meta_mode, "min_matured_origins": 1,
                                     "label_observer": True, "native_batch_policy": "reference"},
                     metadata={**old.config.walkforward_config.metadata, "use_scalar_trial_scoring": False})
        bt = QuantBTEndpoint(replace(old.config, walkforward_config=wf))
        context = MetaHistoryContext(
            MetaHistory(), "helper-test", "SYNTHETIC-linear", "1D", "helper-run",
            clock=lambda fold, stage, elapsed: fold.train_index[-1] + pd.Timedelta(
                seconds={"search": 10, "fit": 20, "seal": 30}[stage]),
        )
        kwargs = {} if meta_mode == "off" else {"meta_history": context}
        result = bt.backtest(data=market(), param_ranges=plan.param_ranges if helper else {"window": (3, 31, 2)}, **kwargs)
        results.append(result)
    left, right = results
    for field in ("equity", "positions", "returns"):
        np.testing.assert_array_equal(getattr(left, field), getattr(right, field))
    a, b = (r.metadata["walk_forward"] for r in results)
    pd.testing.assert_frame_equal(a["trial_table"], b["trial_table"], check_exact=True)
    assert a["params_by_fold"] == b["params_by_fold"]
    if meta_mode == "off":
        assert "meta_selection" not in a
    else:
        for old_record, new_record in zip(a["meta_selection"]["records"], b["meta_selection"]["records"], strict=True):
            for key in old_record:
                assert old_record[key] == new_record[key], key
