"""Synthetic numeric qualification only; no history, account or market inputs."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import warnings

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from quantbt.optimization.meta_selection.common import MetaRecordError, digest
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from tools.meta_model_research import families as f


@pytest.fixture(autouse=True)
def single_numeric_thread():
    with threadpool_limits(limits=1):
        yield


def synthetic():
    rng = np.random.default_rng(731)
    counts = (3, 7, 11, 19) * 6
    X = rng.normal(size=(sum(counts), 3)) * 8
    beta = np.array([0.7, -0.4, 0.2])
    y = X @ beta + rng.normal(scale=0.15, size=len(X))
    w = np.concatenate([np.full(n, 1 / n) for n in counts])
    return X, y, w, beta


def available(code):
    if code.startswith("X"):
        try:
            f._xgboost()
        except f.FamilyUnavailableError as exc:
            pytest.skip(str(exc))
    return f.FamilySpec(code)


def fitted(code):
    X, y, w, _ = synthetic()
    return f.fit_family(available(code), X, y, w)


def rehash(payload):
    payload["model_id"] = digest({k: v for k, v in payload.items() if k != "model_id"})
    return payload


@pytest.mark.parametrize("code", f.CODES)
def test_closed_frozen_specs_and_stable_distinct_sha_recipes(code):
    spec = f.FamilySpec(code)
    assert spec.code == code and len(spec.recipe_id) == 64
    assert len({f.FamilySpec(c).recipe_id for c in f.CODES}) == 5
    assert spec.recipe_id == digest(f._recipe(code))
    with pytest.raises(FrozenInstanceError):
        spec.code = "B1"


@pytest.mark.parametrize(
    "code", ["P0", "B2", "h135", " H135", "X4", "", None, 1, True, []]
)
def test_unregistered_family_is_not_an_alias_or_new_search_arm(code):
    with pytest.raises(MetaRecordError, match="FAMILY"):
        f.FamilySpec(code)


def test_b1_independent_scalar_generalized_conjugate_oracle():
    X = np.array([[1.0], [2.0], [4.0]])
    y, w = np.array([2.0, -1.0, 3.0]), np.array([1.0, 0.5, 0.5])
    model = f.fit_family(f.FamilySpec("B1"), X, y, w)
    # Two origins: (1+2+8+2)*beta = 2-1+6. Prior precision is 1
    # in the MEAN-origin likelihood, equivalently lambda_sum=K=2.
    assert model.state["coefficients"] == pytest.approx((7 / 13,))
    assert model.metadata["weight_sum"] == 2
    assert model.metadata["diagnostics"]["lambda_sum"] == 2
    assert model.metadata["fit_count"] == 1
    recipe = f._recipe("B1")
    assert recipe["prior"] == "N(0,I)" and recipe["sigma2"] == 1
    assert recipe["likelihood_power"] == "w/K"
    assert recipe["posterior_certainty"] == "not_calibrated"


@pytest.mark.parametrize("code", ["B1", "H135", "H200"])
def test_linear_recovery_with_noise_and_independent_measured_loss(code):
    X, y, w, truth = synthetic()
    copies = [a.copy() for a in (X, y, w)]
    model = f.fit_family(f.FamilySpec(code), X, y, w)
    np.testing.assert_allclose(model.state["coefficients"], truth, atol=0.04, rtol=0)
    predicted = model.predict(X)
    assert predicted.shape == (len(X),) and np.isfinite(predicted).all()
    expected = sum(
        float(wi) * float(yi - pi) ** 2 for wi, yi, pi in zip(w, y, predicted)
    ) / sum(w)
    assert model.metadata["train_served_mse"] == pytest.approx(expected, abs=1e-12)
    assert model.metadata["train_raw_mse"] == model.metadata["train_served_mse"]
    assert model.metadata["weight_sum"] == pytest.approx(24)
    for actual, before in zip((X, y, w), copies):
        np.testing.assert_array_equal(actual, before)


@pytest.mark.parametrize("code,epsilon", [("H135", 1.35), ("H200", 2.0)])
def test_huber_exact_sklearn_recipe_and_concomitant_objective(code, epsilon):
    from sklearn.linear_model import HuberRegressor

    X, y, w, _ = synthetic()
    model = f.fit_family(f.FamilySpec(code), X, y, w)
    K, alpha = model.metadata["weight_sum"], model.metadata["diagnostics"]["alpha"]
    assert alpha == K * (10 / 12)
    oracle = HuberRegressor(
        fit_intercept=False,
        epsilon=epsilon,
        alpha=alpha,
        max_iter=500,
        tol=1e-8,
        warm_start=False,
    ).fit(X, y, sample_weight=w)
    np.testing.assert_array_equal(model.state["coefficients"], oracle.coef_)
    assert model.metadata["diagnostics"]["scale"] == oracle.scale_
    # Independent scalar pieces of sklearn's actual objective, including K*s.
    s = oracle.scale_
    terms = []
    for row, target, weight in zip(X, y, w):
        residual = abs(float(target - sum(v * b for v, b in zip(row, oracle.coef_))))
        terms.append(
            weight
            * (
                residual**2 / s
                if residual <= epsilon * s
                else 2 * epsilon * residual - epsilon**2 * s
            )
        )
    expected = K * s + sum(terms) + alpha * sum(float(b) ** 2 for b in oracle.coef_)
    assert model.metadata["diagnostics"]["objective"] == pytest.approx(
        expected, rel=1e-12
    )


@pytest.mark.parametrize("code", ["H135", "H200"])
def test_huber_outlier_contract_on_synthetic_signal(code):
    rng = np.random.default_rng(731)
    X = np.linspace(-8, 8, 200)[:, None]
    clean = X[:, 0] * 0.5 + rng.normal(0, 0.05, len(X))
    contaminated = clean.copy()
    contaminated[-1] += 500
    w = np.full(len(X), 1 / 10)
    robust = f.fit_family(f.FamilySpec(code), X, contaminated, w)
    squared = f.fit_family(f.FamilySpec("B1"), X, contaminated, w)
    robust_error = np.mean((robust.predict(X) - clean) ** 2)
    assert robust_error < np.mean((squared.predict(X) - clean) ** 2) / 10
    assert robust.metadata["diagnostics"]["scale"] > 0


@pytest.mark.parametrize("code", ["B1", "H135", "H200"])
def test_origin_mass_not_row_count_and_replication_invariance(code):
    X, y, w, _ = synthetic()
    spec = f.FamilySpec(code)
    model = f.fit_family(spec, X, y, w)
    # Split every row into two equally weighted copies: total origin mass fixed.
    split = f.fit_family(
        spec, np.repeat(X, 2, axis=0), np.repeat(y, 2), np.repeat(w / 2, 2)
    )
    # Duplicate complete origins: K and the sum penalty double together.
    doubled = f.fit_family(spec, np.tile(X, (2, 1)), np.tile(y, 2), np.tile(w, 2))
    np.testing.assert_allclose(model.predict(X), split.predict(X), atol=2e-7, rtol=1e-7)
    np.testing.assert_allclose(
        model.predict(X), doubled.predict(X), atol=2e-7, rtol=1e-7
    )
    assert split.metadata["weight_sum"] == pytest.approx(model.metadata["weight_sum"])
    assert doubled.metadata["weight_sum"] == pytest.approx(
        2 * model.metadata["weight_sum"]
    )
    # Equal row weights are a different estimand for unequal origin sizes.
    unbalanced = f.fit_family(spec, X, y, np.ones(len(w)))
    assert not np.allclose(
        model.state["coefficients"], unbalanced.state["coefficients"], atol=1e-5
    )


@pytest.mark.parametrize("code", f.CODES)
def test_exact_zero_anchor_on_all_zero_rows_shape_and_permutation(code):
    X, y, w, _ = synthetic()
    spec = available(code)
    model = f.fit_family(spec, X, y, w)
    probe = np.vstack((np.zeros((2, X.shape[1])), X[:17], np.zeros((3, X.shape[1]))))
    original = model.predict(probe)
    assert np.array_equal(original[np.all(probe == 0, axis=1)], np.zeros(5))
    assert model.predict(np.empty((0, X.shape[1]))).shape == (0,)
    assert model.predict(probe[:1]).shape == (1,)
    order = np.random.default_rng(9).permutation(len(probe))
    np.testing.assert_allclose(
        model.predict(probe[order]), original[order], atol=1e-12, rtol=1e-12
    )
    train_order = np.random.default_rng(8).permutation(len(X))
    permuted = f.fit_family(spec, X[train_order], y[train_order], w[train_order])
    np.testing.assert_allclose(
        model.predict(probe), permuted.predict(probe), atol=3e-6, rtol=1e-6
    )


@pytest.mark.parametrize("code", f.CODES)
def test_json_roundtrip_deterministic_restore_without_refitting(code, monkeypatch):
    model = fitted(code)
    payload = json.loads(json.dumps(model.to_payload(), allow_nan=False))

    def forbidden(*args, **kwargs):
        raise AssertionError("restoring/predicting must not fit")

    monkeypatch.setattr(NumericRuntime, "fit", forbidden)
    if code.startswith("H"):
        from sklearn.linear_model import HuberRegressor

        monkeypatch.setattr(HuberRegressor, "fit", forbidden)
    if code.startswith("X"):
        monkeypatch.setattr(f._xgboost(), "train", forbidden)
    first, second = (
        f.NumericModel.from_payload(payload),
        f.NumericModel.from_payload(payload),
    )
    assert first.model_id == second.model_id == model.model_id
    assert first == second == model  # State equality never compares NumPy arrays.
    assert first.spec == model.spec and first.dimension == 3
    assert first.to_payload() == second.to_payload() == payload
    X, _, _, _ = synthetic()
    np.testing.assert_array_equal(first.predict(X), model.predict(X))
    np.testing.assert_array_equal(second.predict(X), model.predict(X))


def test_immutable_model_state_metadata_outputs_and_detached_json():
    model = fitted("B1")
    with pytest.raises(FrozenInstanceError):
        model.dimension = 4
    with pytest.raises(TypeError):
        model.state["coefficients"][0] = 4
    with pytest.raises(TypeError):
        model.metadata["diagnostics"]["lambda_sum"] = 0
    with pytest.raises(TypeError):
        model.backend_versions["numpy"] = "other"
    result = model.predict(np.ones((2, 3)))
    with pytest.raises(ValueError):
        result.setflags(write=True)
    with pytest.raises(ValueError):
        result[0] = 2
    detached = model.to_payload()
    detached["state"]["coefficients"][0] = 99
    detached["metadata"]["diagnostics"]["lambda_sum"] = 99
    assert model.to_payload() != detached
    assert f.NumericModel.from_payload(model.to_payload()).model_id == model.model_id


@pytest.mark.parametrize(
    "path,value",
    [
        (("version",), "old"),
        (("recipe_id",), "0" * 64),
        (("backend_versions", "numpy"), "0.0.0"),
        (("backend_versions", "unexpected"), "1"),
        (("spec", "code"), "B2"),
        (("dimension",), 4),
        (("dimension",), True),
        (("dimension",), 0),
        (("dimension",), f.MAX_DIMENSION + 1),
        (("state", "coefficients"), [1, 2]),
        (("state", "coefficients"), [True, 2, 3]),
        (("state", "coefficients"), [float("nan"), 2, 3]),
        (("metadata", "weight_sum"), 0),
        (("metadata", "fit_count"), True),
        (("metadata", "status"), "CONVERGENCE_FAILED"),
        (("metadata", "train_served_mse"), float("inf")),
        (("metadata", "diagnostics", "lambda_sum"), 999),
        (("metadata", "diagnostics", "relative_residual"), "0"),
        (("metadata", "diagnostics", "relative_residual"), False),
        (("metadata", "diagnostics", "runtime_policy"), []),
        (("metadata", "diagnostics", "selected_backend"), "rust"),
    ],
)
def test_strict_rehashed_payload_validation_not_just_content_hash(path, value):
    payload = fitted("B1").to_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if not (isinstance(value, float) and not np.isfinite(value)) and not (
        isinstance(value, list)
        and any(isinstance(v, float) and not np.isfinite(v) for v in value)
    ):
        rehash(payload)
    with pytest.raises(MetaRecordError):
        f.NumericModel.from_payload(payload)


@pytest.mark.parametrize(
    "mutation",
    ["extra", "missing", "state_extra", "metadata_extra", "spec_extra", "id"],
)
def test_strict_payload_fields_and_stale_identity(mutation):
    payload = fitted("B1").to_payload()
    if mutation == "extra":
        payload["unexpected"] = 1
    elif mutation == "missing":
        del payload["dimension"]
    elif mutation == "state_extra":
        payload["state"]["intercept"] = 1
    elif mutation == "metadata_extra":
        payload["metadata"]["unknown"] = 1
    elif mutation == "spec_extra":
        payload["spec"]["alpha"] = 1
    else:
        payload["state"]["coefficients"][0] += 1
    with pytest.raises(MetaRecordError):
        f.NumericModel.from_payload(payload)


@pytest.mark.parametrize(
    "payload", [[], None, "{}", {"bad": np.float64(1)}, {"bad": (1, 2)}]
)
def test_restore_accepts_only_json_object_state(payload):
    with pytest.raises(MetaRecordError):
        f.NumericModel.from_payload(payload)


def test_payload_size_and_nesting_caps(monkeypatch):
    payload = fitted("B1").to_payload()
    monkeypatch.setattr(f, "MAX_MODEL_BYTES", 128)
    with pytest.raises(MetaRecordError, match="SIZE"):
        f.NumericModel.from_payload(payload)
    nested = []
    for _ in range(18):
        nested = [nested]
    with pytest.raises(MetaRecordError, match="SIZE"):
        f.NumericModel.from_payload({"nested": nested})
    with pytest.raises(MetaRecordError, match="SIZE"):
        f.NumericModel.from_payload({"large_integer": 2**4096})


@pytest.mark.parametrize(
    "X,y,w",
    [
        ([[1, 2]], [1], [0]),
        ([[1, 2]], [1], [-1]),
        ([[1, 2]], [1], [np.nan]),
        ([[1, 2]], [np.inf], [1]),
        ([[1, np.inf]], [1], [1]),
        ([[True, False]], [1], [1]),
        ([[1, 2]], [True], [1]),
        ([[1, 2]], [1], [True]),
        ([[1, 2]], [[1]], [1]),
        ([[1], [2]], [1, 2], [1e308, 1e308]),
        ([[1, 2]], [1, 2], [1]),
        ([1, 2], [1, 2], [1, 1]),
        (np.empty((0, 2)), [], []),
        (np.empty((1, 0)), [1], [1]),
        ([["1", "2"]], [1], [1]),
        ([[1 + 2j]], [1], [1]),
    ],
)
def test_reject_invalid_fit_inputs_without_backend_work(X, y, w, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid data must not fit")

    monkeypatch.setattr(NumericRuntime, "fit", forbidden)
    with pytest.raises(MetaRecordError):
        f.fit_family(f.FamilySpec("B1"), X, y, w)


def test_resource_caps_and_prediction_dimension_shape_finiteness():
    model = fitted("B1")
    for X in (np.ones(3), np.ones((2, 4)), [[np.inf, 1, 2]], [[True, False, True]]):
        with pytest.raises(MetaRecordError):
            model.predict(X)
    for X in (
        np.zeros((1, f.MAX_DIMENSION + 1)),
        np.zeros((f.MAX_ROWS + 1, 1)),
        np.broadcast_to(1.0, (f.MAX_ROWS, f.MAX_DIMENSION)),
    ):
        with pytest.raises(MetaRecordError, match="DIMENSION|RESOURCE"):
            f.fit_family(f.FamilySpec("B1"), X, np.ones(len(X)), np.ones(len(X)))
    payload = model.to_payload()
    payload["state"]["coefficients"] = [1e308] * 3
    huge = f.NumericModel.from_payload(rehash(payload))
    with pytest.raises(MetaRecordError, match="PREDICTION"):
        huge.predict(np.full((1, 3), 1e308))


def test_default_runtime_is_reference_and_injected_fit_is_used(monkeypatch):
    original = NumericRuntime.fit
    calls = []

    def observed(self, X, y, w, lam, **kwargs):
        calls.append((self, lam))
        return original(self, X, y, w, lam, **kwargs)

    monkeypatch.setattr(NumericRuntime, "fit", observed)
    X, y, w, _ = synthetic()
    spec = f.FamilySpec("B1")
    f.fit_family(spec, X, y, w)
    assert len(calls) == 1 and calls[0][0].policy == "reference"
    owner = NumericRuntime(native_policy="reference", work_cache=False)
    model = f.fit_family(spec, X, y, w, runtime=owner)
    assert len(calls) == 2 and calls[1][0] is owner
    assert calls[1][1] == model.metadata["weight_sum"]
    assert model.metadata["fit_count"] == 1
    f.fit_family(f.FamilySpec("H135"), X, y, w, runtime=owner)
    assert len(calls) == 2  # Huber accepts the common context, not its Ridge solver.
    with pytest.raises(MetaRecordError, match="RUNTIME"):
        f.fit_family(spec, X, y, w, runtime=object())
    with pytest.raises(MetaRecordError, match="SPEC"):
        f.fit_family("B1", X, y, w)


def native_runtime(policy="require"):
    root = Path(__file__).resolve().parents[2]
    prefix = root / ".maturin/mode5-m5111/goal-native-gate01/native/_quantbt_native"
    paths = list(prefix.glob("_quantbt_native*.so"))
    if len(paths) != 1:
        pytest.skip(
            "existing qualified native binary absent; no build/install authorized"
        )
    spec = importlib.util.spec_from_file_location(
        "_mlr03_numeric_test._quantbt_native", paths[0]
    )
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    return NumericRuntime(native_policy=policy, native_module=native, work_cache=False)


def test_existing_native_delegate_parity_work_count_and_portable_restore():
    owner = native_runtime()
    X, y, w, _ = synthetic()
    model = f.fit_family(f.FamilySpec("B1"), X, y, w, runtime=owner)
    assert model.metadata["fit_count"] == 2  # delegated solve + whole-fit reference
    assert model.metadata["external_runtime_qualification_fits"] == 2
    assert model.metadata["diagnostics"]["selected_backend"] == "rust"
    assert owner.calls == 1
    np.testing.assert_allclose(
        model.predict(X), fitted("B1").predict(X), atol=1e-11, rtol=1e-11
    )
    restored = f.NumericModel.from_payload(model.to_payload())
    assert restored.model_id == model.model_id
    np.testing.assert_array_equal(restored.predict(X), model.predict(X))


def test_native_whole_fit_mismatch_is_failure_not_pass(monkeypatch):
    owner = native_runtime()
    original = owner.fit

    def wrong(*args, **kwargs):
        gram, b, beta = original(*args, **kwargs)
        return 2 * gram, 2 * b, beta

    monkeypatch.setattr(owner, "fit", wrong)
    X, y, w, _ = synthetic()
    with pytest.raises(MetaRecordError, match="PARITY_FAILED"):
        f.fit_family(f.FamilySpec("B1"), X, y, w, runtime=owner)


def test_native_dispatch_probe_work_is_not_hidden_or_recharged():
    owner = native_runtime("auto")
    rng = np.random.default_rng(731)
    X = rng.normal(size=(512, 24))
    y, w = rng.normal(size=len(X)), np.full(len(X), 1 / 16)
    first = f.fit_family(f.FamilySpec("B1"), X, y, w, runtime=owner)
    assert first.metadata["fit_count"] == 8
    assert first.metadata["diagnostics"]["dispatch_probe_fits"] == 6
    assert first.metadata["external_runtime_qualification_fits"] == 2
    second = f.fit_family(f.FamilySpec("B1"), X, y, w, runtime=owner)
    assert second.metadata["fit_count"] == 2
    assert second.metadata["diagnostics"]["dispatch_probe_fits"] == 0
    np.testing.assert_array_equal(first.predict(X), second.predict(X))


@pytest.mark.parametrize(
    "field,value",
    [
        ("scale", False),
        ("n_iter", True),
        ("warnings", ["ConvergenceWarning:failed"]),
        ("epsilon", 1.0),
        ("alpha", 1.0),
    ],
)
def test_huber_restore_cannot_relabel_failed_or_different_recipe(field, value):
    payload = fitted("H135").to_payload()
    payload["metadata"]["diagnostics"][field] = value
    with pytest.raises(MetaRecordError, match="HUBER_METADATA"):
        f.NumericModel.from_payload(rehash(payload))


@pytest.mark.parametrize("failure", ["warning", "exception", "iteration_cap"])
def test_huber_retains_convergence_failure_never_returns_pass(failure, monkeypatch):
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import HuberRegressor

    original = HuberRegressor.fit

    def failed(self, *args, **kwargs):
        if failure == "exception":
            raise ValueError("synthetic l-BFGS failure")
        result = original(self, *args, **kwargs)
        if failure == "warning":
            warnings.warn("synthetic solver did not converge", ConvergenceWarning)
        else:
            self.n_iter_ = 500
        return result

    monkeypatch.setattr(HuberRegressor, "fit", failed)
    X, y, w, _ = synthetic()
    with pytest.raises(f.FamilyFitError, match="FIT_FAILED") as exc:
        f.fit_family(f.FamilySpec("H135"), X, y, w)
    assert exc.value.metadata["status"] == "FIT_FAILED"
    assert exc.value.metadata["fit_count"] == 1
    assert exc.value.metadata["recipe_id"] == f.FamilySpec("H135").recipe_id
    assert "synthetic" in str(exc.value) or "CONVERGENCE_FAILED" in str(exc.value)


def test_absent_xgb_is_explicit_and_does_not_affect_linear_fit(monkeypatch):
    original = f.packages.version

    def missing(name):
        if name == "xgboost-cpu":
            raise f.packages.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(f.packages, "version", missing)
    X, y, w, _ = synthetic()
    for code in ("X2", "X3"):
        with pytest.raises(
            f.FamilyUnavailableError, match="CPU_UNAVAILABLE.*no auto-install"
        ):
            f.fit_family(f.FamilySpec(code), X, y, w)
    assert f.fit_family(f.FamilySpec("B1"), X, y, w).metadata["status"] == "FIT"


@pytest.mark.parametrize(
    "package,version,code",
    [("scikit-learn", "1.7.0", "H135"), ("xgboost-cpu", "3.1.2", "X2")],
)
def test_unapproved_backend_versions_are_rejected(package, version, code, monkeypatch):
    original = f.packages.version
    monkeypatch.setattr(
        f.packages,
        "version",
        lambda name: version if name == package else original(name),
    )
    X, y, w, _ = synthetic()
    with pytest.raises(MetaRecordError, match="BACKEND_VERSION"):
        f.fit_family(f.FamilySpec(code), X, y, w)


def test_xgb_gpu_or_conflicting_distribution_not_admitted(monkeypatch):
    def versions(name):
        if name == "xgboost-cpu":
            return "3.1.1"
        raise f.packages.PackageNotFoundError(name)

    monkeypatch.setattr(f.packages, "version", versions)
    monkeypatch.setattr(
        f.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            __version__="3.1.1", build_info=lambda: dict(USE_CUDA=True, USE_NCCL=False)
        ),
    )
    with pytest.raises(MetaRecordError, match="CPU-only"):
        f._xgboost()
    monkeypatch.setattr(f.packages, "version", lambda name: "3.1.1")
    with pytest.raises(MetaRecordError, match="conflicting"):
        f._xgboost()


@pytest.mark.parametrize("code", ["X2", "X3"])
def test_optional_real_xgb_whole_function_centering_raw_surrogate_and_ubj(code):
    spec = available(code)
    module = f._xgboost()
    rng = np.random.default_rng(731)
    X = rng.uniform(-3, 3, size=(256, 2))
    y = 2 + (X[:, 0] > 0) + X[:, 1] ** 2
    w = np.full(len(X), 1 / 8)
    model = f.fit_family(spec, X, y, w)
    booster = module.Booster(params={"nthread": 1, "device": "cpu"})
    booster.load_model(bytearray.fromhex(model.state["ubj_hex"]))
    booster.set_param({"nthread": 1, "device": "cpu"})
    f0 = float(booster.predict(module.DMatrix(np.zeros((1, 2)), nthread=1))[0])
    assert abs(f0) > 0.1  # base_score=0 does not constrain learned f(0).
    raw = booster.predict(module.DMatrix(X, nthread=1)).astype(float)
    served = model.predict(X)
    np.testing.assert_array_equal(served, raw - f0)
    assert not np.allclose(served, raw)
    assert model.predict(np.zeros((4, 2))).tolist() == [0.0] * 4
    assert model.metadata["train_served_mse"] == pytest.approx(
        np.average((y - served) ** 2, weights=w)
    )
    assert model.metadata["train_raw_mse"] == pytest.approx(
        np.average((y - raw) ** 2, weights=w)
    )
    assert model.metadata["train_served_mse"] != pytest.approx(
        model.metadata["train_raw_mse"]
    )
    recipe = f._recipe(code)
    assert recipe["centered_loss_optimized"] is False and recipe["rounds"] == 64
    assert recipe["params"] == dict(
        booster="gbtree",
        objective="reg:squarederror",
        tree_method="hist",
        device="cpu",
        max_depth=2 if code == "X2" else 3,
        eta=0.05,
        min_child_weight=1.0,
        reg_lambda=1.0,
        reg_alpha=0.0,
        max_bin=64,
        subsample=1.0,
        colsample_bytree=1.0,
        colsample_bylevel=1.0,
        colsample_bynode=1.0,
        nthread=1,
        seed=731,
        base_score=0.0,
        validate_parameters=True,
    )
    restored = f.NumericModel.from_payload(json.loads(json.dumps(model.to_payload())))
    np.testing.assert_array_equal(restored.predict(X), served)
    for key, value in (
        ("anchor_raw", f0 + 1),
        ("ubj_hex", "00"),
        ("ubj_hex", "A0"),
        ("ubj_hex", "00" * (f.MAX_UBJ_BYTES + 1)),
    ):
        payload = deepcopy(model.to_payload())
        payload["state"][key] = value
        with pytest.raises(MetaRecordError):
            f.NumericModel.from_payload(rehash(payload))
