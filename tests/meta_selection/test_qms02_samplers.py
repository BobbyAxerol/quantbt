"""Q2-T01..Q2-T08: proposal/space/stage contracts, not sampler superiority."""

from dataclasses import replace
import importlib.metadata
import json

import numpy as np
import optuna
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization import (
    NormalizedSearchSpace,
    ObjectiveResult,
    OptimizationConfig,
    OptunaOptimizer,
    SamplerConfig,
    build_sampler,
    suggest_params,
)
from quantbt.optimization.wfo_study import WfoSamplerStudy
from quantbt.walkforward import _derive_fold_seed, _param_matrix, WalkForwardTrialRecord
from quantbt.core.wfo_contracts import strategy_fingerprint
from tools import qms01_baseline as baseline


optuna.logging.set_verbosity(optuna.logging.WARNING)
NUMERIC = {"x": (-2.0, 2.0), "y": (-2.0, 2.0)}
RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")


def technical_strategy(data, params, train_index, test_index, fold):
    span = max(2, int(round(8 + float(params.get("x", 0)) + float(params.get("y", 0)))))
    close = data["close"]
    output = np.sign(close - close.rolling(span, min_periods=1).mean()).astype(float)
    return output.reindex(test_index).fillna(0)


def run_public(
    recipe=None,
    *,
    mode="mode_4_is_only_robust",
    schedule="per_fold_causal",
    ranges=None,
    native="off",
    trials=8,
    **policies,
):
    endpoint = baseline.endpoint(mode, schedule, native=native, retention="none")
    cfg = replace(
        endpoint.config.walkforward_config,
        sampler_config=recipe,
        optuna_trials=trials,
        **policies,
    )
    endpoint = QuantBTEndpoint(
        replace(
            endpoint.config,
            walkforward_config=cfg,
            strategy_class=technical_strategy
            if ranges is not None
            else endpoint.config.strategy_class,
        )
    )
    result = endpoint.backtest(
        data=baseline.market(), param_ranges=ranges or {"window": (3, 31, 2)}
    )
    return endpoint, result


@pytest.mark.parametrize("mode,schedule", baseline.ROUTES)
def test_q2_t01_omitted_config_exact_released_search_and_account(mode, schedule):
    recorded = json.loads(baseline.MANIFEST.read_text())
    expected = next(
        lane
        for lane in recorded["lanes"]
        if (lane["mode"], lane["schedule"]) == (mode, schedule)
    )
    actual, result, engine = baseline.trace_run(mode=mode, schedule=schedule)
    for field in (
        "pools",
        "score_tasks",
        "equity",
        "positions",
        "stitched_signal",
        "report",
        "account_contract",
    ):
        assert actual[field] == expected[field], field
    for field in (
        "params",
        "params_by_fold",
        "best_trial",
        "trial_table",
        "candidate_table",
        "validation_claim",
        "causality_claim",
    ):
        assert actual["summary"][field] == expected["summary"][field], field
    assert "sampler_studies" not in result.metadata["walk_forward"]
    assert engine._sampler_bridges is None


def test_q2_t01_explicit_legacy_matches_default_numeric_outcomes():
    _old, old = run_public()
    _new, new = run_public({"name": "tpe_legacy"})
    pd.testing.assert_series_equal(old.equity, new.equity, check_exact=True)
    pd.testing.assert_frame_equal(old.positions, new.positions, check_exact=True)
    assert (
        old.metadata["walk_forward"]["params_by_fold"]
        == new.metadata["walk_forward"]["params_by_fold"]
    )
    assert list(
        new.metadata["walk_forward"]["sampler_studies"][0]["rows"][0][
            "effective_params"
        ]
    ) == ["window"]


def test_q2_t02_group_constructor_and_joint_proposals():
    cfg = SamplerConfig(name="tpe_multivariate_group", kwargs={"n_startup_trials": 2})
    sampler = build_sampler(cfg, seed=91, search_space=NUMERIC, objective_count=1)
    assert isinstance(sampler, optuna.samplers.TPESampler)
    _bt, result = run_public(cfg, ranges=NUMERIC, trials=12)
    telemetry = result.metadata["walk_forward"]["sampler_studies"][0]
    assert telemetry["kwargs"] == {
        "n_startup_trials": 2,
        "multivariate": True,
        "group": True,
        "seed": 731,
    }
    assert telemetry["relative_proposal_trials"] > 0
    assert telemetry["group_decomposition"] == "not_exposed"
    with pytest.raises(ValueError, match="multivariate"):
        build_sampler(
            SamplerConfig(kwargs={"group": True}),
            seed=1,
            search_space=NUMERIC,
            objective_count=1,
        )


def test_q2_t03_cma_default_rejection_and_explicit_independent(monkeypatch):
    space = {**NUMERIC, "choice": ["red", "green"]}
    with pytest.raises(ValueError, match="categorical"):
        run_public({"name": "cmaes"}, ranges=space)
    _bt, result = run_public(
        {"name": "cmaes", "mixed_space_policy": "explicit_independent"},
        ranges=space,
        trials=12,
    )
    meta = result.metadata["walk_forward"]["sampler_studies"][0]
    assert meta["sampler_class"] == "CmaEsSampler" and meta["cmaes_version"] == "0.12.0"
    assert meta["joint_numeric_candidates"] == ["x", "y"]
    assert meta["independent_sample_calls"]["choice"] == meta["attempts"]
    assert meta["relative_proposal_trials"] > 0
    from quantbt.optimization import samplers

    real = samplers.importlib.util.find_spec
    monkeypatch.setattr(
        samplers.importlib.util,
        "find_spec",
        lambda name: None if name == "cmaes" else real(name),
    )
    with pytest.raises(ImportError, match="cmaes"):
        run_public({"name": "cmaes"}, ranges=NUMERIC)
    with pytest.raises(ValueError, match="one objective"):
        build_sampler(
            SamplerConfig(name="cmaes"), seed=1, search_space=NUMERIC, objective_count=2
        )


SPACE = {
    "filter": {"kind": "boolean"},
    "length": {
        "kind": "integer",
        "low": 2,
        "high": 10,
        "step": 2,
        "active_if": {"filter": True},
    },
    "rate": {"kind": "float", "low": 0.001, "high": 0.1, "log": True},
    "label": {"kind": "categorical", "choices": ["green", "red"]},
    "degree": 2,
}


def test_q2_t04_mapping_conditional_activity_and_effective_identity():
    space = NormalizedSearchSpace(SPACE)
    first = {"filter": False, "length": 2, "rate": 0.01, "label": "green", "degree": 2}
    second = {**first, "length": 10}
    assert space.effective(first) == space.effective(second)
    assert space.candidate_key(
        first, strategy_identity="alpha1"
    ) == space.candidate_key(second, strategy_identity="alpha1")
    assert space.candidate_key(
        first, strategy_identity="alpha1"
    ) != space.candidate_key(first, strategy_identity="alpha2")
    cfg = SamplerConfig(name="tpe_multivariate_group", kwargs={"n_startup_trials": 2})
    study = optuna.create_study(
        sampler=build_sampler(cfg, seed=4, search_space=SPACE, objective_count=1)
    )
    captured = []

    def objective(trial):
        params = suggest_params(trial, SPACE)
        captured.append(params)
        if params["filter"]:
            assert params["length"] in (2, 4, 6, 8, 10)
        else:
            assert "length" not in params
        assert 0.001 <= params["rate"] <= 0.1 and params["degree"] == 2
        assert trial.distributions["rate"].log
        return float(params["rate"])

    study.optimize(objective, n_trials=16)
    assert {p["filter"] for p in captured} == {True, False}
    assert NormalizedSearchSpace({"x": [1, 2, 3]}).by_name["x"].kind == "categorical"
    assert NormalizedSearchSpace({"x": range(3)}).by_name["x"].kind == "categorical"
    assert NormalizedSearchSpace({"x": (1, 3, 1)}).by_name["x"].kind == "integer"


def test_q2_t04_warm_numeric_representation_has_one_effective_identity():
    space = NormalizedSearchSpace({"x": (-2.0, 2.0), "fixed": 2})
    first = {"x": 1, "fixed": 2.0}
    second = {"x": 1.0, "fixed": 2}
    assert space.candidate_key(first, strategy_identity="alpha") == space.candidate_key(
        second, strategy_identity="alpha"
    )
    effective = space.effective(first)
    assert type(effective["x"]) is float and type(effective["fixed"]) is int


def test_q2_t04_nullable_category_keeps_active_and_inactive_geometry_distinct():
    ranges = {
        "flag": {"kind": "boolean"},
        "category": {
            "kind": "categorical",
            "choices": [None, "a"],
            "active_if": {"flag": True},
        },
    }
    records = [
        WalkForwardTrialRecord(i, params, 1, 1, 0, 0, 0, [])
        for i, params in enumerate(
            [
                {"flag": True, "category": None},
                {"flag": False},
            ]
        )
    ]
    matrix, names = _param_matrix(records, ranges)
    assert matrix[0, names.index("category__active")] == 1
    assert matrix[1, names.index("category__active")] == 0
    assert matrix[0, names.index("category==None")] == pytest.approx(1 / np.sqrt(2))
    assert matrix[1, names.index("category==None")] == 0


def test_q2_t04_numeric_centroid_stays_on_the_declared_step_lattice():
    from quantbt.walkforward import _denormalize_param_value

    spec = {"kind": "integer", "low": 2, "high": 9, "step": 2}
    value = _denormalize_param_value(1.0, spec)
    assert value == 8
    assert NormalizedSearchSpace({"x": spec}).effective({"x": value}) == {"x": 8}


@pytest.mark.parametrize(
    "spec",
    [
        {"kind": "float", "low": 0, "high": 1, "log": True},
        {"kind": "float", "low": 0.1, "high": 1, "log": True, "step": 0.1},
        {"kind": "integer", "low": 1, "high": 10, "log": True, "step": 2},
        {"kind": "integer", "low": 1.0, "high": 10},
        {"kind": "float", "low": 1, "high": np.inf},
        {"kind": "float", "low": 1, "high": 2, "active_if": {"missing": True}},
        {"kind": "categorical", "choices": []},
        {"kind": "categorical", "choices": [np.nan, "a"]},
        {"kind": "categorical", "choices": [True, 1]},
        {"kind": "float", "low": 1, "high": 2, "unknown": True},
    ],
)
def test_q2_t04_invalid_schema_fails(spec):
    with pytest.raises(ValueError):
        NormalizedSearchSpace({"x": spec})


def test_q2_t04_unordered_geometry_and_log_scale():
    def record(i, params):
        return WalkForwardTrialRecord(i, params, 1, 1, 0, 0, 0, [])

    records = [
        record(0, {"kind": "a", "x": 1}),
        record(1, {"kind": "b", "x": 10}),
        record(2, {"kind": "c", "x": 100}),
    ]
    ranges = {
        "kind": {"kind": "categorical", "choices": ["a", "b", "c"]},
        "x": {"kind": "float", "low": 1.0, "high": 100.0, "log": True},
    }
    matrix, _ = _param_matrix(records, ranges)
    changed, _ = _param_matrix(
        records, {**ranges, "kind": {"kind": "categorical", "choices": ["c", "a", "b"]}}
    )
    np.testing.assert_allclose(
        np.linalg.norm(matrix[:, None] - matrix[None, :], axis=2),
        np.linalg.norm(changed[:, None] - changed[None, :], axis=2),
    )
    assert matrix[1, 1] == pytest.approx(0.5)


def numeric_study(recipe, n, seed=9, split=None, warm=()):
    bridge = WfoSamplerStudy(
        SamplerConfig(name=recipe),
        NUMERIC,
        seed=seed,
        budget=n,
        cutoff="2021-01-01",
        strategy_identity="synthetic-ridge-v1",
        stage="is_search",
    )
    study = optuna.create_study(sampler=bridge.sampler(), direction="maximize")
    bridge.enqueue(study, warm)

    def objective(trial):
        _requested, p = bridge.suggest(trial)
        return -((p["x"] + p["y"]) ** 2 + 0.1 * (p["x"] - 0.5) ** 2)

    for budget in split or (n,):
        study.optimize(objective, n_trials=budget)
    return bridge, study


@pytest.mark.parametrize("recipe", RECIPES)
def test_q2_t05_owned_sampler_resume_preserves_exact_trajectory(recipe):
    first, full = numeric_study(recipe, 16)
    resumed, parts = numeric_study(recipe, 16, split=(5, 11))
    assert [(t.params, t.values, t.state) for t in full.trials] == [
        (t.params, t.values, t.state) for t in parts.trials
    ]
    assert (
        first.metadata(full)["ask_tell_digest"]
        == resumed.metadata(parts)["ask_tell_digest"]
    )
    if recipe == "sobol":
        meta = resumed.metadata(parts)
        assert meta["attempts"] == 16 and meta["qmc_sequence_position"] == 15
        assert meta["qmc_dimension_order"] == ["x", "y"]
        assert meta["independent_sample_calls"] == {"x": 1, "y": 1}
        assert meta["kwargs"]["scramble"] is True and meta["kwargs"]["seed"] == 9


def test_q2_t05_sobol_fixed_order_and_independent_categories():
    _bt, result = run_public(
        {"name": "sobol"}, ranges={**NUMERIC, "category": ["z", "a"]}, trials=9
    )
    meta = result.metadata["walk_forward"]["sampler_studies"][0]
    assert meta["qmc_sequence_position"] == 8
    assert meta["independent_sample_calls"]["category"] == 9
    with pytest.raises(ValueError, match="conditional"):
        run_public({"name": "sobol"}, ranges=SPACE)


def test_q2_t06_early_constraints_are_pruned_and_skip_financial_work():
    _bt, reference = run_public({"name": "tpe_legacy"}, ranges=NUMERIC, trials=12)

    def constraint(params):
        return (params["x"],)

    bt, result = run_public(
        {"name": "tpe_legacy"},
        ranges=NUMERIC,
        trials=12,
        parameter_constraints=constraint,
    )
    meta = result.metadata["walk_forward"]["sampler_studies"][0]
    rejected = [r for r in meta["rows"] if r["reason"] == "PARAMETER_CONSTRAINT"]
    assert rejected and all(
        r["state"] == "PRUNED" and r["objective"] is None for r in rejected
    )
    assert (
        result.metadata["walk_forward"]["performance_profile"]["score_calls"]
        < reference.metadata["walk_forward"]["performance_profile"]["score_calls"]
    )
    assert bt.config.walkforward_config.parameter_constraints is constraint


@pytest.mark.parametrize("recipe", ["cmaes", "sobol"])
def test_q2_t06_post_filter_policy_required_and_real_values_retained(recipe):
    def constraint(record):
        return (record.params["x"],)

    with pytest.raises(ValueError, match="constraints|post_filter"):
        run_public({"name": recipe}, ranges=NUMERIC, result_constraints=constraint)
    _bt, result = run_public(
        {"name": recipe, "constraint_mode": "post_filter"},
        ranges=NUMERIC,
        result_constraints=constraint,
        trials=12,
    )
    meta = result.metadata["walk_forward"]["sampler_studies"][0]
    rejected = [r for r in meta["rows"] if r["reason"] == "RESULT_CONSTRAINT"]
    assert rejected and all(
        r["state"] == "COMPLETE" and r["objective"] is not None for r in rejected
    )
    assert all(
        params["x"] <= 0
        for params in result.metadata["walk_forward"]["params_by_fold"].values()
    )


def test_q2_t06_formal_tpe_constraints_and_all_rejected():
    _bt, result = run_public(
        {"name": "tpe", "kwargs": {"n_startup_trials": 2}},
        ranges=NUMERIC,
        result_constraints=lambda record: (record.params["x"],),
        trials=16,
    )
    assert all(
        p["x"] <= 0 for p in result.metadata["walk_forward"]["params_by_fold"].values()
    )
    with pytest.raises(ValueError, match="no valid in-sample trials"):
        run_public(
            {"name": "tpe"}, ranges=NUMERIC, parameter_constraints=lambda p: (1,)
        )


@pytest.mark.parametrize("recipe", ["cmaes", "sobol"])
def test_q2_t06_parameter_constraints_require_explicit_post_filter(recipe):
    with pytest.raises(ValueError, match="constraints|post_filter"):
        run_public(
            {"name": recipe}, ranges=NUMERIC, parameter_constraints=lambda p: (p["x"],)
        )
    _bt, result = run_public(
        {"name": recipe, "constraint_mode": "post_filter"},
        ranges=NUMERIC,
        parameter_constraints=lambda p: (p["x"],),
        trials=12,
    )
    studies = result.metadata["walk_forward"]["sampler_studies"]
    rejected = [
        r
        for study in studies
        for r in study["rows"]
        if r["reason"] == "PARAMETER_CONSTRAINT"
    ]
    assert rejected and all(
        r["state"] == "PRUNED" and r["objective"] is None for r in rejected
    )


def test_q2_t07_warm_start_availability_rescore_and_budget():
    ranges = {"window": (3, 31, 2)}
    seed = {
        "params": {"window": 11},
        "available_at": "2020-01-01T00:00:00Z",
        "space_identity": NormalizedSearchSpace(ranges).identity,
        "strategy_identity": strategy_fingerprint(baseline.example_strategy()),
    }
    _bt, result = run_public(
        {"name": "tpe_legacy"}, sampler_warm_start=(seed,), trials=6
    )
    for meta in result.metadata["walk_forward"]["sampler_studies"]:
        assert meta["attempts"] == 6 and meta["warm_start_attempts"] == 1
        assert meta["rows"][0]["effective_params"] == seed["params"]
        assert (
            meta["rows"][0]["source"] == "warm_start"
            and meta["rows"][0]["state"] == "COMPLETE"
        )
    first, second = result.metadata["walk_forward"]["sampler_studies"]
    assert first["rows"][0]["objective"] != second["rows"][0]["objective"]
    for changed in (
        {**seed, "objective": 999},
        {**seed, "space_identity": "bad"},
        {**seed, "strategy_identity": "other-alpha"},
        {**seed, "available_at": "2022-01-01T00:00:00Z"},
        {**seed, "params": {"window": 4}},
    ):
        with pytest.raises(ValueError):
            run_public({"name": "tpe_legacy"}, sampler_warm_start=(changed,))
    with pytest.raises(ValueError, match="budget"):
        run_public({"name": "tpe_legacy"}, sampler_warm_start=(seed,) * 9)


def test_q2_t07_same_arm_independent_warm_pool_and_inactive_provenance():
    warm = (
        {
            "params": {"x": 0.5, "y": -0.5},
            "available_at": "2020-01-01",
            "space_identity": NormalizedSearchSpace(NUMERIC).identity,
            "strategy_identity": "synthetic-ridge-v1",
        },
    )
    first, native = numeric_study("sobol", 10, warm=warm)
    other, shadow = numeric_study("sobol", 10, warm=warm)
    assert [t.params for t in native.trials] == [t.params for t in shadow.trials]
    assert (
        first.metadata(native)["ask_tell_digest"]
        == other.metadata(shadow)["ask_tell_digest"]
    )
    assert first.metadata(native)["attempts"] == 10
    space = {
        "flag": {"kind": "boolean"},
        "x": {"kind": "integer", "low": 1, "high": 4, "active_if": {"flag": True}},
    }
    bridge = WfoSamplerStudy(
        {"name": "tpe_legacy"},
        space,
        seed=1,
        budget=2,
        cutoff="2021-01-01",
        strategy_identity="fixture",
        stage="is_search",
    )
    study = optuna.create_study(sampler=bridge.sampler())
    bridge.enqueue(
        study,
        (
            {
                "params": {"flag": False, "x": 4},
                "available_at": "2020-01-01",
                "space_identity": bridge.space.identity,
                "strategy_identity": "fixture",
            },
        ),
    )
    study.optimize(lambda t: float(len(bridge.suggest(t)[1])), n_trials=2)
    assert bridge.metadata(study)["rows"][0]["requested_params"] == {
        "flag": False,
        "x": 4,
    }
    assert bridge.metadata(study)["rows"][0]["effective_params"] == {"flag": False}


@pytest.mark.parametrize("mode,schedule", baseline.ROUTES)
@pytest.mark.parametrize("recipe", RECIPES)
def test_q2_t08_actual_sampler_only_stage_matrix(mode, schedule, recipe):
    config = {"name": recipe}
    if recipe == "cmaes":
        config["kwargs"] = {"popsize": 4}
    _bt, result = run_public(
        config, mode=mode, schedule=schedule, ranges=NUMERIC, trials=8
    )
    wf = result.metadata["walk_forward"]
    studies = wf["sampler_studies"]
    expected_count = 1 if schedule == "global" else 2
    assert len(studies) == expected_count
    for i, study in enumerate(studies):
        assert study["seed"] == (
            731 if schedule == "global" else _derive_fold_seed(731, i)
        )
        assert study["attempts"] == 8 and study["sampler_wall_seconds"] > 0
        assert study["stage"] == (
            "sbb_proxy_is_search" if mode == "mode_2_sbb" else "is_search"
        )
        assert study["sampler_class"] in {"TPESampler", "CmaEsSampler", "QMCSampler"}
    assert wf["optimization_mode"] == mode and wf["optimization_schedule"] == schedule
    frozen = json.loads(baseline.MANIFEST.read_text())
    lane = next(
        item
        for item in frozen["lanes"]
        if (item["mode"], item["schedule"]) == (mode, schedule)
    )
    assert wf["oos_used_for_selection"] == lane["summary"]["oos_used_for_selection"]


@pytest.mark.parametrize(
    "config,ranges",
    [
        ({"name": "random"}, NUMERIC),
        ({"name": "tpe", "kwargs": {"group": True}}, NUMERIC),
        ({"name": "tpe", "kwargs": {"seed": 999}}, NUMERIC),
        ({"name": "cmaes"}, {**NUMERIC, "label": ["a", "b"]}),
        ({"name": "sobol"}, SPACE),
    ],
)
def test_q2_t08_unsupported_preflight_before_strategy_or_financial_work(
    config, ranges, monkeypatch
):
    from quantbt.walkforward import WalkForwardEngine

    def unexpected(*args, **kwargs):
        pytest.fail("unsupported configuration reached expensive strategy/scoring")

    monkeypatch.setattr(WalkForwardEngine, "_call_strategy_for_indices", unexpected)
    monkeypatch.setattr(WalkForwardEngine, "_score_strategy_outputs_batch", unexpected)
    with pytest.raises(ValueError):
        run_public(config, ranges=ranges)


@pytest.mark.parametrize("recipe", RECIPES)
def test_q2_t08_installed_native_and_oracle_account_parity(recipe):
    _bt, oracle = run_public({"name": recipe}, ranges=NUMERIC)
    _bt, native = run_public({"name": recipe}, ranges=NUMERIC, native="require")
    pd.testing.assert_series_equal(native.equity, oracle.equity, rtol=1e-11, atol=1e-9)
    pd.testing.assert_frame_equal(
        native.positions, oracle.positions, rtol=1e-11, atol=1e-9
    )
    assert (
        native.metadata["walk_forward"]["params_by_fold"]
        == oracle.metadata["walk_forward"]["params_by_fold"]
    )
    assert native.metadata["walk_forward"]["native_prepared_wfo"]["fallback_rows"] == 0


def test_q2_t08_package_dependency_and_protected_financial_modules():
    import tomllib

    project = tomllib.loads((baseline.ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((baseline.ROOT / "uv.lock").read_text())
    assert (
        "cmaes==0.12.0" in project["project"]["optional-dependencies"]["optimization"]
    )
    assert importlib.metadata.version("cmaes") == "0.12.0"
    old = json.loads(baseline.MANIFEST.read_text())["source"]["protected_sources"]
    allowed = {
        "src/quantbt/endpoint.py",
        "src/quantbt/walkforward.py",
        # QMS-06 original-pass witness and fail-closed route glue, not kernels.
        "src/quantbt/backends/native_prepared_evaluation.py",
        "src/quantbt/backends/native_wfo_public.py",
        "src/quantbt/backends/reactive_wfo.py",
        "src/quantbt/backends/reactive_wfo_support.py",
        "src/quantbt/optimization/config.py",
        "src/quantbt/optimization/samplers.py",
        "src/quantbt/optimization/space.py",
        "src/quantbt/optimization/optimizer.py",
        "src/quantbt/optimization/__init__.py",
        "pyproject.toml",
        "uv.lock",
    }
    for name, expected in old.items():
        if name in allowed:
            continue
        current = (baseline.ROOT / name).read_bytes()
        from tools.qms_release_source_guard import without_release_identity
        current = without_release_identity(current, name)
        from tools.qms_c02_source_guard import without_c02_witness
        current = without_c02_witness(current, name)
        from tools.qms06_source_guard import without_qms06_witness

        current = without_qms06_witness(current, name)
        # Approved QMS-04 is only an opt-in numeric export/feature addition.
        # Normalize those exact additions; all financial Rust bytes stay locked.
        if name == "rust/native_event/src/lib.rs":
            current = current.replace(
                b'#[cfg(feature = "qms-numeric-candidate")]\nmod qms_numeric;\n', b""
            ).replace(
                b'    #[cfg(feature = "qms-numeric-candidate")]\n    qms_numeric::register(module)?;\n',
                b"",
            )
        elif name == "rust/native_event/Cargo.toml":
            current = current.replace(
                b"\n[features]\nqms-numeric-candidate = []\n", b""
            )
        assert baseline.digest(current) == expected, name
    old_versions = {
        (p["name"], p["version"])
        for p in tomllib.loads(baseline.git("show", "5f8a732:uv.lock").decode())[
            "package"
        ]
    }
    assert {
        (p["name"], {"quantbt-engine": "1.1.1", "quantbt-native": "0.4.2"}.get(p["name"], p["version"]))
        for p in lock["package"] if p["name"] != "cmaes"
    } == old_versions


def test_q2_t01_adaptive_trajectory_factory_and_public_observer_are_lossless():
    def sequence(sampler):
        study = optuna.create_study(sampler=sampler, direction="maximize")

        def objective(trial):
            params = suggest_params(trial, NUMERIC)
            return -((params["x"] + params["y"]) ** 2 + 0.1 * (params["x"] - 0.5) ** 2)

        study.optimize(objective, n_trials=40)
        return [(t.params, t.values, t.state) for t in study.trials]

    reference = sequence(optuna.samplers.TPESampler(seed=9))
    factory = sequence(
        build_sampler(SamplerConfig(), seed=9, search_space=NUMERIC, objective_count=1)
    )
    bridge, observed = numeric_study("tpe_legacy", 40)
    assert (
        reference == factory == [(t.params, t.values, t.state) for t in observed.trials]
    )
    assert bridge.metadata(observed)["startup_policy"] == 10


def test_q2_t03_cma_margin_integer_contract():
    ranges = {"x": (2, 10, 2), "y": (0.01, 1.0, 0.01)}
    _bt, result = run_public(
        {"name": "cmaes", "kwargs": {"with_margin": True, "popsize": 4}},
        ranges=ranges,
        trials=12,
    )
    for study in result.metadata["walk_forward"]["sampler_studies"]:
        assert study["kwargs"]["with_margin"] is True
        assert all(
            r["effective_params"]["x"] in (2, 4, 6, 8, 10) for r in study["rows"]
        )


@pytest.mark.parametrize("recipe", RECIPES)
def test_q2_t08_runnable_public_example(recipe):
    from examples.wfo_samplers import run

    _bt, result = run(recipe, warm_start=True)
    assert len(result.equity) > 0
    assert len(result.metadata["walk_forward"]["sampler_studies"]) == 2


def test_q2_t04_generic_factory_shares_structured_space_and_fixed_params():
    class Evaluator:
        def evaluate(self, params):
            return ObjectiveResult.scalar(float(params["x"]))

    result = OptunaOptimizer(
        evaluator=Evaluator(),
        config=OptimizationConfig(
            study_name="qms02", n_trials=5, show_progress_bar=False
        ),
        sampler_config=SamplerConfig(name="sobol", constraint_mode="post_filter"),
    ).optimize(
        param_ranges={
            "x": {"kind": "float", "low": 0.1, "high": 1, "log": True},
            "flag": [True, False],
        },
        fixed_params={"flag": True},
    )
    assert all(record.params["flag"] is True for record in result.trials)


def test_q2_t04_fixed_parent_stays_in_conditional_factory_schema():
    class Evaluator:
        def evaluate(self, params):
            return ObjectiveResult.scalar(float(params["rate"]))

    result = OptunaOptimizer(
        evaluator=Evaluator(),
        config=OptimizationConfig(
            study_name="fixed-parent", n_trials=5, show_progress_bar=False
        ),
        sampler_config=SamplerConfig(name="tpe_multivariate_group"),
    ).optimize(
        param_ranges=SPACE,
        fixed_params={"filter": False, "label": "green"},
        initial_trials=[{"filter": False, "rate": 0.01, "label": "green", "degree": 2}],
    )
    assert result.trials[0].params["rate"] == 0.01
    assert all("length" not in row.params for row in result.trials)
    assert result.search_diagnostics["param_kind_counts"]["float"] == 1


@pytest.mark.parametrize("recipe", ["tpe_multivariate_group", "cmaes"])
def test_q2_t04_public_conditional_space_is_admissible(recipe):
    space = {
        **NUMERIC,
        "filter": {"kind": "boolean"},
        "length": {
            "kind": "integer",
            "low": 2,
            "high": 8,
            "step": 2,
            "active_if": {"filter": True},
        },
    }
    config = {"name": recipe}
    if recipe == "cmaes":
        config["mixed_space_policy"] = "explicit_independent"
    _bt, result = run_public(config, ranges=space, trials=16)
    for study in result.metadata["walk_forward"]["sampler_studies"]:
        rows = study["rows"]
        assert all(
            ("length" in row["effective_params"]) == row["effective_params"]["filter"]
            for row in rows
        )
        assert study["conditional_branches"]["length"] == {"filter": (True,)}


def test_q2_t05_failed_trial_remains_failed_without_fake_objective():
    bridge = WfoSamplerStudy(
        {"name": "sobol"},
        NUMERIC,
        seed=9,
        budget=4,
        cutoff="2021-01-01",
        strategy_identity="fixture",
        stage="is_search",
    )
    study = optuna.create_study(sampler=bridge.sampler())

    def objective(trial):
        _, p = bridge.suggest(trial)
        if trial.number == 0:
            raise RuntimeError("declared failed evaluation fixture")
        return p["x"] + p["y"]

    study.optimize(objective, n_trials=4, catch=(RuntimeError,))
    meta = bridge.metadata(study)
    assert meta["states"]["FAIL"] == 1 and meta["rows"][0]["objective"] is None


def test_q2_t08_centroid_rejected_before_financial_work(monkeypatch):
    from quantbt.walkforward import WalkForwardEngine

    def unexpected(*args, **kwargs):
        pytest.fail("inadmissible centroid reached strategy/evaluator")

    monkeypatch.setattr(WalkForwardEngine, "_call_strategy_for_indices", unexpected)
    with pytest.raises(ValueError, match="centroid"):
        run_public({"name": "tpe_legacy"}, ranges=SPACE, flat_selector="centroid")


@pytest.mark.parametrize("status", ["failure", "error", "skipped"])
def test_q2_t08_gate_rejects_nonpassing_test_evidence(tmp_path, status):
    import xml.etree.ElementTree as ET
    from tools.qms02_evidence import tests

    root = ET.Element("testsuite")
    for i in range(1, 9):
        case = ET.SubElement(root, "testcase", name=f"test_q2_t{i:02d}_fixture")
        if i == 8:
            ET.SubElement(case, status)
    path = tmp_path / "invalid.xml"
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="without skips"):
        tests(path)
