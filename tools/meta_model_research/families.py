"""Bounded M4-ML-03 numeric recipes, not history/selection/financial owners.

X is the caller's permitted, already-transformed candidate-minus-anchor basis;
y is relative Y. The caller supplies positive weights totalling one per origin,
so K=sum(w), not the candidate count. Group membership cannot be checked from
these arrays. No preprocessing, weight normalization or posterior calibration
is learned here. The parent owns provenance, clocks, work budgets and selection.

B1 uses beta~N(0,I), sigma2=1 and likelihood powers w_i/K. Its generalized
conjugate mean solves (X'WX + K I) beta = X'Wy. This fixed-prior control is not
empirical Bayes; correlated origins/rows do not imply calibrated certainty.

sklearn 1.8.0 Huber minimizes K*s + sum_i w_i*s*h_e((y_i-X_i beta)/s)
+ alpha*||beta||^2, jointly over beta and s>=10*float64.eps. Here h_e(u)=u^2
inside |u|<=e and 2*e*|u|-e^2 outside, alpha=K*10/12, no intercept.
This is concomitant-scale Huber, not fixed-scale Huber or squared-loss Ridge.
Source: https://github.com/scikit-learn/scikit-learn/blob/1.8.0/sklearn/linear_model/_huber.py

XGB trains raw f with weighted square error and tree regularization, then serves
g(V)=f(V)-f(0) on EVERY row. Its raw training surrogate does not optimize the
centered served loss. Both measured training MSEs are retained, not validation
claims. UBJ model IO (hex in JSON), never pickle or a Python memory snapshot:
https://xgboost.readthedocs.io/en/release_3.1.0/tutorials/saving_model.html
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from importlib import metadata as packages
import json
import math
from typing import Mapping
import warnings

import numpy as np

from quantbt.optimization.meta_selection.common import (
    MetaRecordError,
    canonical,
    digest,
    freeze,
    frozen_array,
    wire,
)
from quantbt.optimization.meta_selection.numerics import (
    NumericLimits,
    NumericRuntime,
    reference_fit,
    solution_diagnostics,
)


VERSION = "m4-ml03-numeric-model-v1"
RECIPE_VERSION = "m4-ml03-family-recipe-v1"
MAX_DIMENSION = 256
MAX_ROWS = 100_000
MAX_WORKSPACE_BYTES = 64 * 1024**2
MAX_MODEL_BYTES = 2 * 1024**2
MAX_UBJ_BYTES = 512 * 1024
CODES = ("B1", "H135", "H200", "X2", "X3")


class FamilyUnavailableError(ImportError):
    """An optional backend is absent; this is not a successful fit."""


class FamilyFitError(MetaRecordError):
    """Failed backend work with a compact retained disposition for the parent."""

    def __init__(self, spec, message):
        super().__init__(f"MLR03_FIT_FAILED:{spec.code}:{message}")
        self.metadata = freeze(
            dict(
                status="FIT_FAILED",
                code=spec.code,
                recipe_id=spec.recipe_id,
                fit_count=1,
                reason=str(message),
            )
        )


def _recipe(code):
    common = dict(
        version=RECIPE_VERSION,
        code=code,
        fit_intercept=False,
        weights="caller_supplied_one_total_per_origin",
        K="sum(w)",
    )
    if code == "B1":
        return dict(
            common,
            prior="N(0,I)",
            sigma2=1.0,
            likelihood_power="w/K",
            lambda_sum="K",
            served="X@beta",
            posterior_certainty="not_calibrated",
        )
    if code in {"H135", "H200"}:
        return dict(
            common,
            backend="scikit-learn==1.8.0",
            epsilon=1.35 if code == "H135" else 2.0,
            alpha="K*10/12",
            max_iter=500,
            tol=1e-8,
            warm_start=False,
            scale_lower_bound=10 * np.finfo(np.float64).eps,
            objective="K*s+sum(w*s*h_e(residual/s))+alpha*||beta||^2",
            served="X@beta",
        )
    return dict(
        common,
        backend="xgboost-cpu==3.1.1",
        rounds=64,
        params=_xgb_params(code),
        trained="raw_f_weighted_square_error",
        served="g(V)=f(V)-f(0)_all_rows",
        centered_loss_optimized=False,
    )


def _xgb_params(code):
    return dict(
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


@dataclass(frozen=True, slots=True)
class FamilySpec:
    code: str

    def __post_init__(self):
        if type(self.code) is not str or self.code not in CODES:
            raise MetaRecordError("MLR03_FAMILY_INVALID: closed IDs B1,H135,H200,X2,X3")

    @property
    def recipe_id(self):
        return digest(_recipe(self.code))


def _xgboost():
    try:
        version = packages.version("xgboost-cpu")
    except packages.PackageNotFoundError as exc:
        raise FamilyUnavailableError(
            "MLR03_XGBOOST_CPU_UNAVAILABLE: optional xgboost-cpu==3.1.1 absent; no auto-install"
        ) from exc
    if version != "3.1.1":
        raise MetaRecordError(
            "MLR03_BACKEND_VERSION_INVALID: xgboost-cpu==3.1.1 required"
        )
    try:
        packages.version("xgboost")
    except packages.PackageNotFoundError:
        pass
    else:
        raise MetaRecordError(
            "MLR03_BACKEND_INVALID: conflicting non-CPU xgboost distribution"
        )
    module = importlib.import_module("xgboost")
    if (
        module.__version__ != version
        or module.build_info().get("USE_CUDA", True)
        or module.build_info().get("USE_NCCL", True)
    ):
        raise MetaRecordError("MLR03_BACKEND_INVALID: CPU-only build/version required")
    return module


def _versions(code):
    versions = {"numpy": np.__version__}
    if code.startswith("H"):
        try:
            version = packages.version("scikit-learn")
        except packages.PackageNotFoundError as exc:
            raise FamilyUnavailableError(
                "MLR03_SKLEARN_UNAVAILABLE: scikit-learn==1.8.0 required"
            ) from exc
        if version != "1.8.0":
            raise MetaRecordError(
                "MLR03_BACKEND_VERSION_INVALID: scikit-learn==1.8.0 required"
            )
        versions.update({"scikit-learn": version, "scipy": packages.version("scipy")})
    elif code.startswith("X"):
        _xgboost()
        versions["xgboost-cpu"] = "3.1.1"
    return versions


def _fields(value, names):
    if not isinstance(value, Mapping) or set(value) != set(names.split()):
        raise MetaRecordError("MLR03_PAYLOAD_FIELDS_INVALID")


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def _positive(value):
    return _number(value) and value > 0


def _json_size(value):
    # Reject non-JSON objects, excessive nesting and oversized containers before
    # canonicalization; in particular bool is not accepted as an integer field.
    remaining = 200_000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise MetaRecordError("MLR03_PAYLOAD_SIZE_INVALID")
        kind = type(item)
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise MetaRecordError("MLR03_PAYLOAD_JSON_INVALID")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif kind is list:
            for child in item:
                visit(child, depth + 1)
        elif kind is str:
            if len(item) > MAX_MODEL_BYTES:
                raise MetaRecordError("MLR03_PAYLOAD_SIZE_INVALID")
        elif kind is float:
            if not math.isfinite(item):
                raise MetaRecordError("MLR03_PAYLOAD_NONFINITE")
        elif kind is int and item.bit_length() > 1024:
            raise MetaRecordError("MLR03_PAYLOAD_SIZE_INVALID")
        elif kind not in {int, bool, type(None)}:
            raise MetaRecordError("MLR03_PAYLOAD_JSON_INVALID")

    visit(value, 0)
    if len(canonical(value).encode()) > MAX_MODEL_BYTES:
        raise MetaRecordError("MLR03_PAYLOAD_SIZE_INVALID")


def _matrix(X, dimension=None, *, fitting=False):
    try:
        a = np.asarray(X)
    except (TypeError, ValueError) as exc:
        raise MetaRecordError("MLR03_INPUT_SHAPE_INVALID") from exc
    if (
        a.ndim != 2
        or not 1 <= a.shape[1] <= MAX_DIMENSION
        or (fitting and not len(a))
        or len(a) > MAX_ROWS
        or (dimension is not None and a.shape[1] != dimension)
    ):
        raise MetaRecordError("MLR03_INPUT_DIMENSION_INVALID")
    required = 6 * a.size * 8 + 6 * a.shape[1] ** 2 * 8 + 4 * len(a) * 8
    if required > MAX_WORKSPACE_BYTES:
        raise MetaRecordError("MLR03_RESOURCE_LIMIT: no silent dimension reduction")
    if a.dtype.kind not in "fiu" or not np.isfinite(a).all():
        raise MetaRecordError("MLR03_INPUT_NONFINITE_OR_NONNUMERIC")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.array(a, dtype=np.float64, order="C", copy=True)
    if not np.isfinite(result).all():
        raise MetaRecordError("MLR03_INPUT_NONFINITE_OR_NONNUMERIC")
    return result


def _vector(value, n):
    try:
        a = np.asarray(value)
    except (ValueError, TypeError) as exc:
        raise MetaRecordError("MLR03_INPUT_VECTOR_INVALID") from exc
    if a.shape != (n,) or a.dtype.kind not in "fiu" or not np.isfinite(a).all():
        raise MetaRecordError("MLR03_INPUT_VECTOR_INVALID")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.array(a, dtype=np.float64, order="C", copy=True)
    if not np.isfinite(result).all():
        raise MetaRecordError("MLR03_INPUT_VECTOR_INVALID")
    return result


def _mse(y, prediction, w, K):
    with np.errstate(over="ignore", invalid="ignore"):
        value = float(np.dot(w / K, (y - prediction) ** 2))
    if not math.isfinite(value):
        raise MetaRecordError("MLR03_LOSS_NONFINITE")
    return value


def _check_prediction(value, n):
    a = np.asarray(value)
    if a.shape != (n,) or not np.isfinite(a).all():
        raise MetaRecordError("MLR03_PREDICTION_INVALID: finite (n,) required")
    return frozen_array(a)


def _load_booster(spec, dimension, state):
    _fields(state, "ubj_hex anchor_raw")
    encoded = state["ubj_hex"]
    if (
        type(encoded) is not str
        or not 0 < len(encoded) <= 2 * MAX_UBJ_BYTES
        or len(encoded) % 2
        or any(c not in "0123456789abcdef" for c in encoded)
        or type(state["anchor_raw"]) not in {float, int}
        or not math.isfinite(state["anchor_raw"])
    ):
        raise MetaRecordError("MLR03_UBJ_STATE_INVALID")
    module = _xgboost()
    try:
        booster = module.Booster(params={"nthread": 1, "device": "cpu"})
        booster.load_model(bytearray.fromhex(encoded))
        booster.set_param({"nthread": 1, "device": "cpu"})
        config = json.loads(booster.save_config())["learner"]
        if (
            booster.num_features() != dimension
            or booster.num_boosted_rounds() != 64
            or config["objective"]["name"] != "reg:squarederror"
            or config["gradient_booster"]["name"] != "gbtree"
            or json.loads(config["learner_model_param"]["base_score"]) != [0.0]
        ):
            raise MetaRecordError("MLR03_UBJ_RECIPE_OR_DIMENSION_INVALID")

        def depth(node):
            if "leaf" in node:
                if not math.isfinite(node["leaf"]):
                    raise MetaRecordError("MLR03_UBJ_NONFINITE")
                return 0
            return 1 + max(depth(child) for child in node["children"])

        trees = booster.get_dump(dump_format="json")
        if len(trees) != 64 or any(
            depth(json.loads(t)) > _xgb_params(spec.code)["max_depth"] for t in trees
        ):
            raise MetaRecordError("MLR03_UBJ_DEPTH_INVALID")
        anchor = booster.predict(module.DMatrix(np.zeros((1, dimension)), nthread=1))
        if anchor.shape != (1,) or float(anchor[0]) != state["anchor_raw"]:
            raise MetaRecordError("MLR03_UBJ_ANCHOR_INVALID")
    except (ValueError, KeyError, TypeError, module.core.XGBoostError) as exc:
        raise MetaRecordError(f"MLR03_UBJ_INVALID:{exc}") from exc
    return booster


def _validate_metadata(spec, meta):
    _fields(
        meta,
        "status n_rows weight_sum fit_count external_runtime_qualification_fits "
        "train_served_mse train_raw_mse diagnostics",
    )
    if (
        meta["status"] != "FIT"
        or type(meta["n_rows"]) is not int
        or not 1 <= meta["n_rows"] <= MAX_ROWS
        or not _positive(meta["weight_sum"])
        or type(meta["fit_count"]) is not int
        or not 1 <= meta["fit_count"] <= 8
        or type(meta["external_runtime_qualification_fits"]) is not int
        or meta["external_runtime_qualification_fits"] not in {0, 2}
        or any(
            type(meta[k]) not in {int, float}
            or not math.isfinite(meta[k])
            or meta[k] < 0
            for k in ("train_served_mse", "train_raw_mse")
        )
    ):
        raise MetaRecordError("MLR03_METADATA_INVALID")
    d, K = meta["diagnostics"], meta["weight_sum"]
    if spec.code == "B1":
        _fields(
            d,
            "lambda_sum condition relative_residual runtime_policy selected_backend native dispatch_probe_fits",
        )
        if (
            not _positive(d["lambda_sum"])
            or d["lambda_sum"] != K
            or not _positive(d["condition"])
            or not _number(d["relative_residual"])
            or not 0 <= d["relative_residual"] <= 1e-10
            or type(d["runtime_policy"]) is not str
            or d["runtime_policy"] not in {"reference", "auto", "require"}
            or type(d["selected_backend"]) is not str
            or d["selected_backend"] not in {"numpy", "rust"}
            or (d["selected_backend"] == "rust" and d["native"] is None)
            or type(d["dispatch_probe_fits"]) is not int
            or d["dispatch_probe_fits"] not in {0, 6}
            or meta["fit_count"]
            != 1 + int(d["native"] is not None) + d["dispatch_probe_fits"]
            or meta["external_runtime_qualification_fits"]
            != 2 * int(d["native"] is not None)
        ):
            raise MetaRecordError("MLR03_B1_METADATA_INVALID")
        if d["native"] is not None:
            _fields(d["native"], "version api descriptor")
            if not all(
                type(d["native"][k]) is str and d["native"][k]
                for k in ("version", "api")
            ) or canonical(d["native"]["descriptor"]) != canonical(
                dict(
                    abi="qms-numeric-v1",
                    dtype="float64",
                    fast_math=False,
                    owned_inputs=True,
                    blocks=["transform", "gram_solve", "rank"],
                )
            ):
                raise MetaRecordError("MLR03_NATIVE_VERSION_INVALID")
    elif spec.code.startswith("H"):
        _fields(d, "alpha epsilon scale n_iter objective warnings")
        if (
            not _positive(d["alpha"])
            or d["alpha"] != K * (10 / 12)
            or not _positive(d["epsilon"])
            or d["epsilon"] != _recipe(spec.code)["epsilon"]
            or not _positive(d["scale"])
            or d["scale"] < 10 * np.finfo(float).eps
            or type(d["n_iter"]) is not int
            or not 0 <= d["n_iter"] < 500
            or not _positive(d["objective"])
            or type(d["warnings"]) is not list
            or any(
                type(s) is not str or s.startswith("ConvergenceWarning:")
                for s in d["warnings"]
            )
        ):
            raise MetaRecordError("MLR03_HUBER_METADATA_INVALID")
    else:
        _fields(d, "rounds depth")
        if (
            type(d["rounds"]) is not int
            or type(d["depth"]) is not int
            or d != dict(rounds=64, depth=_xgb_params(spec.code)["max_depth"])
        ):
            raise MetaRecordError("MLR03_XGB_METADATA_INVALID")
    if spec.code != "B1" and (
        meta["fit_count"] != 1 or meta["external_runtime_qualification_fits"] != 0
    ):
        raise MetaRecordError("MLR03_FIT_COUNT_INVALID")
    if (
        not spec.code.startswith("X")
        and meta["train_raw_mse"] != meta["train_served_mse"]
    ):
        raise MetaRecordError("MLR03_LINEAR_LOSS_INVALID")


@dataclass(frozen=True, slots=True)
class NumericModel:
    spec: FamilySpec
    dimension: int
    backend_versions: Mapping
    state: Mapping
    metadata: Mapping
    model_id: str = field(init=False)

    def __post_init__(self):
        if (
            not isinstance(self.spec, FamilySpec)
            or type(self.dimension) is not int
            or not 1 <= self.dimension <= MAX_DIMENSION
        ):
            raise MetaRecordError("MLR03_MODEL_DIMENSION_INVALID")
        if self.backend_versions != _versions(self.spec.code):
            raise MetaRecordError("MLR03_BACKEND_VERSION_INVALID")
        state, meta = wire(self.state), wire(self.metadata)
        _json_size(dict(state=state, metadata=meta))
        _validate_metadata(self.spec, meta)
        if self.spec.code.startswith("X"):
            _load_booster(self.spec, self.dimension, state)
        else:
            _fields(state, "coefficients")
            coef = state["coefficients"]
            if (
                type(coef) is not list
                or len(coef) != self.dimension
                or any(
                    type(c) not in {float, int} or not math.isfinite(c) for c in coef
                )
            ):
                raise MetaRecordError("MLR03_COEFFICIENT_DIMENSION_INVALID")
        for key in ("state", "metadata", "backend_versions"):
            object.__setattr__(self, key, freeze(getattr(self, key)))
        object.__setattr__(self, "model_id", digest(self._body()))
        _json_size(self.to_payload())

    def _body(self):
        return dict(
            version=VERSION,
            spec=dict(code=self.spec.code),
            recipe_id=self.spec.recipe_id,
            dimension=self.dimension,
            backend_versions=wire(self.backend_versions),
            state=wire(self.state),
            metadata=wire(self.metadata),
        )

    def to_payload(self):
        """Return a detached JSON object; mutating it cannot mutate this model."""
        return dict(self._body(), model_id=self.model_id)

    @classmethod
    def from_payload(cls, payload):
        """Strict JSON-object restore; no fit, defaults, migration or dependency install."""
        _json_size(payload)
        _fields(
            payload,
            "version spec recipe_id dimension backend_versions state metadata model_id",
        )
        _fields(payload["spec"], "code")
        spec = FamilySpec(payload["spec"]["code"])
        if payload["version"] != VERSION or payload["recipe_id"] != spec.recipe_id:
            raise MetaRecordError("MLR03_RECIPE_OR_VERSION_INVALID")
        model = cls(
            spec,
            payload["dimension"],
            payload["backend_versions"],
            payload["state"],
            payload["metadata"],
        )
        if (
            type(payload["model_id"]) is not str
            or payload["model_id"] != model.model_id
        ):
            raise MetaRecordError("MLR03_MODEL_ID_INVALID")
        return model

    def predict(self, X):
        """Batch relative Y; exact zero on zero vectors, immutable finite (n,)."""
        a = _matrix(X, self.dimension)
        if not len(a):
            return frozen_array(np.empty(0))
        with np.errstate(over="ignore", invalid="ignore"):
            if self.spec.code.startswith("X"):
                booster = _load_booster(self.spec, self.dimension, self.state)
                raw = booster.predict(_xgboost().DMatrix(a, nthread=1))
                result = np.asarray(raw, dtype=np.float64) - self.state["anchor_raw"]
            else:
                result = a @ np.asarray(self.state["coefficients"])
        result = _check_prediction(result, len(a))
        if np.any(result[np.all(a == 0, axis=1)] != 0):
            raise MetaRecordError("MLR03_ANCHOR_INVALID")
        return result


def fit_family(spec, X, y, w, *, runtime=None) -> NumericModel:
    """Fit one closed recipe; failures propagate and never produce a PASS model.

    runtime is used by B1 and accepted but unused for other backends.
    metadata.fit_count counts actual solves,
    including B1 parity/probe solves; runtime construction qualification is
    separately reported, not charged again per model. No fit cache is owned here.
    """
    if not isinstance(spec, FamilySpec):
        raise MetaRecordError("MLR03_SPEC_REQUIRED")
    if runtime is not None and not isinstance(runtime, NumericRuntime):
        raise MetaRecordError("MLR03_RUNTIME_INVALID: NumericRuntime required")
    a = _matrix(X, fitting=True)
    y, w = _vector(y, len(a)), _vector(w, len(a))
    if (w <= 0).any():
        raise MetaRecordError("MLR03_WEIGHT_INVALID: positive origin weights required")
    try:
        K = math.fsum(float(v) for v in w)
    except OverflowError as exc:
        raise MetaRecordError("MLR03_WEIGHT_SUM_INVALID") from exc
    if not _positive(K):
        raise MetaRecordError("MLR03_WEIGHT_SUM_INVALID")
    versions = _versions(spec.code)
    meta = dict(
        status="FIT",
        n_rows=len(a),
        weight_sum=K,
        fit_count=1,
        external_runtime_qualification_fits=0,
    )
    if spec.code == "B1":
        owner = (
            runtime
            if runtime is not None
            else NumericRuntime(
                native_policy="reference",
                work_cache=False,
                limits=NumericLimits(max_workspace_bytes=MAX_WORKSPACE_BYTES),
            )
        )
        before = owner.dispatch_calls
        gram, b, beta = owner.fit(a, y, w, K)
        diag = solution_diagnostics(gram, b, beta, owner.limits)
        probes = 2 * (owner.dispatch_calls - before)
        if owner.native is not None:
            expected = reference_fit(a, y, w, K, owner.limits)
            if any(
                not np.allclose(
                    actual,
                    ref,
                    rtol=owner.limits.parity_rtol,
                    atol=owner.limits.parity_atol,
                )
                for actual, ref in zip((gram, b, beta), expected)
            ):
                raise MetaRecordError("MLR03_NATIVE_PARITY_FAILED")
        meta.update(
            fit_count=1 + int(owner.native is not None) + probes,
            external_runtime_qualification_fits=2 * int(owner.native is not None),
            diagnostics=dict(
                lambda_sum=K,
                **diag,
                runtime_policy=owner.policy,
                selected_backend=owner.selected_blocks["gram_solve"],
                native=wire(owner.native_identity),
                dispatch_probe_fits=probes,
            ),
        )
        state, raw = dict(coefficients=beta.tolist()), a @ beta
    elif spec.code.startswith("H"):
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import HuberRegressor

        epsilon, alpha = _recipe(spec.code)["epsilon"], K * (10 / 12)
        estimator = HuberRegressor(
            fit_intercept=False,
            epsilon=epsilon,
            alpha=alpha,
            max_iter=500,
            tol=1e-8,
            warm_start=False,
        )
        try:
            with warnings.catch_warnings(record=True) as observed:
                warnings.simplefilter("always")
                estimator.fit(a, y, sample_weight=w)
        except (ValueError, FloatingPointError) as exc:
            raise FamilyFitError(spec, str(exc)) from exc
        messages = [f"{v.category.__name__}:{v.message}" for v in observed]
        if (
            any(issubclass(v.category, ConvergenceWarning) for v in observed)
            or estimator.n_iter_ >= 500
        ):
            raise FamilyFitError(
                spec,
                f"CONVERGENCE_FAILED:n_iter={estimator.n_iter_}:" + ";".join(messages),
            )
        raw = a @ estimator.coef_
        s = float(estimator.scale_)
        u = np.abs((y - raw) / s)
        h = np.where(u <= epsilon, u**2, 2 * epsilon * u - epsilon**2)
        objective = (
            K * s
            + float(np.dot(w, s * h))
            + alpha * float(estimator.coef_ @ estimator.coef_)
        )
        state = dict(coefficients=estimator.coef_.tolist())
        meta["diagnostics"] = dict(
            alpha=alpha,
            epsilon=epsilon,
            scale=s,
            n_iter=int(estimator.n_iter_),
            objective=objective,
            warnings=messages,
        )
    else:
        module = _xgboost()
        try:
            booster = module.train(
                _xgb_params(spec.code),
                module.DMatrix(a, label=y, weight=w, nthread=1),
                num_boost_round=64,
            )
            raw = booster.predict(module.DMatrix(a, nthread=1)).astype(np.float64)
            anchor = float(
                booster.predict(module.DMatrix(np.zeros((1, a.shape[1])), nthread=1))[0]
            )
            state = dict(
                ubj_hex=booster.save_raw(raw_format="ubj").hex(), anchor_raw=anchor
            )
        except module.core.XGBoostError as exc:
            raise FamilyFitError(spec, str(exc)) from exc
        meta["diagnostics"] = dict(rounds=64, depth=_xgb_params(spec.code)["max_depth"])
    raw = _check_prediction(raw, len(a))
    served = raw - state["anchor_raw"] if spec.code.startswith("X") else raw
    meta.update(
        train_raw_mse=_mse(y, raw, w, K), train_served_mse=_mse(y, served, w, K)
    )
    return NumericModel(spec, a.shape[1], versions, state, meta)
