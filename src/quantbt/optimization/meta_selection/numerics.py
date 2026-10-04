"""Small float64 batch boundary; no market, account or current forward inputs."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import math

import numpy as np

from .common import MetaRecordError, freeze


@dataclass(frozen=True, slots=True)
class NumericLimits:
    condition_limit: float = 1e12
    residual_limit: float = 1e-10
    parity_rtol: float = 1e-9
    parity_atol: float = 1e-10
    boundary_band: float = 1e-8
    max_workspace_bytes: int = 256_000_000

    def __post_init__(self):
        if (
            any(
                not math.isfinite(v) or v <= 0
                for v in (
                    self.condition_limit,
                    self.residual_limit,
                    self.parity_rtol,
                    self.parity_atol,
                    self.boundary_band,
                )
            )
            or type(self.max_workspace_bytes) is not int
            or self.max_workspace_bytes <= 0
        ):
            raise MetaRecordError("META_NUMERIC_LIMIT_INVALID")


def validate_fit(v, y, weights, lambda_reg, limits):
    v, y, weights = (np.asarray(a, dtype=np.float64) for a in (v, y, weights))
    if (
        v.ndim != 2
        or min(v.shape, default=0) <= 0
        or y.shape != (len(v),)
        or weights.shape != (len(v),)
        or not np.isfinite(v).all()
        or not np.isfinite(y).all()
        or not np.isfinite(weights).all()
        or (weights <= 0).any()
        or not math.isfinite(lambda_reg)
        or lambda_reg <= 0
    ):
        raise MetaRecordError(
            "META_NUMERIC_INPUT_INVALID: finite positive weighted batch required"
        )
    # Include owned FFI buffers, whitened reference and dense d-by-d solve work.
    required = 3 * v.nbytes + 4 * y.nbytes + 6 * v.shape[1] ** 2 * 8
    if required > limits.max_workspace_bytes:
        raise MetaRecordError(
            "META_RESOURCE_LIMIT: model dimensions are not reduced silently"
        )
    return tuple(np.ascontiguousarray(a) for a in (v, y, weights))


def reference_fit(v, y, weights, lambda_reg, limits=NumericLimits()):
    v, y, weights = validate_fit(v, y, weights, lambda_reg, limits)
    root = np.sqrt(weights)
    white = v * root[:, None]
    gram = white.T @ white
    gram.flat[:: len(gram) + 1] += lambda_reg
    b = white.T @ (root * y)
    try:
        beta = np.linalg.solve(gram, b)
    except np.linalg.LinAlgError as exc:
        raise MetaRecordError("META_SOLVE_FAILED: no automatic jitter") from exc
    return gram, b, beta


def solution_diagnostics(gram, b, beta, limits):
    if not all(np.isfinite(a).all() for a in (gram, b, beta)):
        raise MetaRecordError("META_SOLVE_NONFINITE")
    condition = float(np.linalg.cond(gram))
    denominator = np.linalg.norm(gram) * np.linalg.norm(beta) + np.linalg.norm(b)
    residual = float(
        np.linalg.norm(gram @ beta - b) / max(denominator, np.finfo(float).tiny)
    )
    if not math.isfinite(condition) or condition > limits.condition_limit:
        raise MetaRecordError("META_SOLVE_ILL_CONDITIONED: no automatic jitter")
    if not math.isfinite(residual) or residual > limits.residual_limit:
        raise MetaRecordError("META_SOLVE_RESIDUAL_FAILED")
    return {"condition": condition, "relative_residual": residual}


class NumericRuntime:
    """Resolve once, batch once per block; candidate injection is internal only."""

    def __init__(
        self, *, native_policy="auto", native_module=None, limits=NumericLimits()
    ):
        if native_policy not in {"auto", "require", "reference"}:
            raise MetaRecordError("META_NATIVE_POLICY_INVALID")
        self.policy, self.limits = native_policy, limits
        self.native, self.reason, self.calls, self.copied_bytes = None, None, 0, 0
        self.native_identity = None
        if native_policy != "reference":
            try:
                module = (
                    native_module
                    if native_module is not None
                    else importlib.import_module("_quantbt_native")
                )
                descriptor = module.qms_numeric_descriptor_v1()
                if descriptor != {
                    "abi": "qms-numeric-v1",
                    "dtype": "float64",
                    "fast_math": False,
                    "owned_inputs": True,
                    "blocks": ["transform", "gram_solve", "rank"],
                }:
                    raise MetaRecordError("META_NATIVE_DESCRIPTOR_MISMATCH")
                self._qualify(module)
                self.native = module
                self.native_identity = {
                    "version": module.version(),
                    "api": module.api_version(),
                    "descriptor": descriptor,
                }
            except (
                ImportError,
                AttributeError,
                MetaRecordError,
                ValueError,
                RuntimeError,
            ) as exc:
                self.reason = (
                    f"META_NATIVE_UNAVAILABLE_OR_UNQUALIFIED:{type(exc).__name__}:{exc}"
                )
                if native_policy == "require":
                    raise MetaRecordError(self.reason) from exc
        else:
            self.reason = "EXPLICIT_INDEPENDENT_NUMPY_REFERENCE"

    def _qualify(self, module):
        v = np.array([[1.0, -2.0], [0.5, 3.0], [-1.0, 1.0]])
        y, w = np.array([0.3, -0.1, 0.8]), np.array([0.5, 0.5, 1.0])
        expected = reference_fit(v, y, w, 10.0, self.limits)
        actual = module.qms_fit_v1(v, y, w, 10.0)
        if len(actual) == 3:
            actual = (
                np.asarray(actual[0]).reshape((v.shape[1],) * 2),
                actual[1],
                actual[2],
            )
        if len(actual) != 3 or any(
            np.shape(a) != np.shape(e)
            or not np.allclose(
                a, e, rtol=self.limits.parity_rtol, atol=self.limits.parity_atol
            )
            for a, e in zip(actual, expected)
        ):
            raise MetaRecordError("META_NATIVE_PARITY_FAILED: qualification fit")
        dy, q = module.qms_rank_v1(v, np.asarray(actual[2]), np.array([0.2, 0.4, 0.6]))
        if not np.allclose(
            dy,
            v @ expected[2],
            rtol=self.limits.parity_rtol,
            atol=self.limits.parity_atol,
        ) or not np.allclose(q, [0.2, 0.4, 0.6] - np.asarray(dy)):
            raise MetaRecordError("META_NATIVE_PARITY_FAILED: qualification rank")
        from .descriptors import DescriptorBatch, OriginBalancedStandardizer

        batch = DescriptorBatch(
            "test",
            ("a", "b"),
            ("x", "y"),
            v[:2],
            np.array([[True, True], [False, True]]),
            np.ones(2, dtype=bool),
            (0, 1),
        )
        scaler = OriginBalancedStandardizer(
            "test",
            "snap",
            ("x", "y"),
            (0, 1),
            np.array([1.0, 0.0]),
            np.array([2.0, 1.0]),
            np.array([False, True]),
            np.ones(2, dtype=bool),
        )
        actual = self._native_transform(module, batch, scaler)
        actual = (
            np.asarray(actual[0]).reshape(batch.values.shape),
            np.asarray(actual[1], dtype=bool),
        )
        expected = scaler.transform(batch)
        if not np.array_equal(actual[1], expected[1]) or not np.allclose(
            actual[0], expected[0]
        ):
            raise MetaRecordError("META_NATIVE_PARITY_FAILED: qualification transform")

    @staticmethod
    def _native_transform(module, batch, scaler):
        mask = np.zeros(len(scaler.feature_names), dtype=np.uint8)
        mask[list(scaler.numeric_columns)] = 1
        return module.qms_transform_v1(
            batch.values,
            batch.active.astype(np.uint8),
            batch.valid.astype(np.uint8),
            mask,
            scaler.mean,
            scaler.scale,
            scaler.constant.astype(np.uint8),
            scaler.observed.astype(np.uint8),
            scaler.constant_tolerance,
        )

    def transform(self, batch, scaler):
        if (
            batch.schema_id != scaler.schema_id
            or batch.feature_names != scaler.feature_names
            or batch.numeric_columns != scaler.numeric_columns
        ):
            raise MetaRecordError(
                "META_DESCRIPTOR_SHAPE: schema/feature order mismatch"
            )
        if self.native is None:
            return scaler.transform(batch)
        self.calls += 1
        self.copied_bytes += (
            batch.values.nbytes
            + batch.active.nbytes
            + batch.valid.nbytes
            + len(batch.feature_names) * 19
        )
        values, unsupported = self._native_transform(self.native, batch, scaler)
        return np.asarray(values).reshape(batch.values.shape), np.asarray(
            unsupported, dtype=bool
        )

    def fit(self, v, y, weights, lambda_reg):
        v, y, weights = validate_fit(v, y, weights, lambda_reg, self.limits)
        if self.native is None:
            return reference_fit(v, y, weights, lambda_reg, self.limits)
        self.calls += 1
        self.copied_bytes += v.nbytes + y.nbytes + weights.nbytes
        gram, b, beta = self.native.qms_fit_v1(v, y, weights, lambda_reg)
        return (
            np.asarray(gram).reshape((v.shape[1],) * 2),
            np.asarray(b),
            np.asarray(beta),
        )

    def rank(self, v, beta, delta_is):
        v, beta, delta_is = (
            np.ascontiguousarray(a, dtype=np.float64) for a in (v, beta, delta_is)
        )
        if (
            v.ndim != 2
            or beta.shape != (v.shape[1],)
            or delta_is.shape != (len(v),)
            or not all(np.isfinite(a).all() for a in (v, beta, delta_is))
        ):
            raise MetaRecordError("META_RANK_INPUT_INVALID")
        if (
            3 * v.nbytes + beta.nbytes + 4 * delta_is.nbytes
            > self.limits.max_workspace_bytes
        ):
            raise MetaRecordError("META_RESOURCE_LIMIT: rank batch too large")
        if self.native is None:
            y = v @ beta
            return y, delta_is - y
        self.calls += 1
        self.copied_bytes += v.nbytes + beta.nbytes + delta_is.nbytes
        y, q = self.native.qms_rank_v1(v, beta, delta_is)
        return np.asarray(y), np.asarray(q)

    @property
    def metadata(self):
        selected = "rust" if self.native is not None else "numpy"
        return freeze(
            {
                "requested_backend": self.policy,
                "selected_backend_by_block": {
                    "parameter_encoding": "python_schema_numpy",
                    "historical_scaler_fit": "numpy",
                    "transform": selected,
                    "gram_solve": selected,
                    "rank": selected,
                    "diagnostics": "numpy",
                },
                "fallback_reason": self.reason,
                "native": self.native_identity,
                "numpy_version": np.__version__,
                "ffi_calls": self.calls,
                "input_owned_copy_bytes": self.copied_bytes,
                "qualification_calls": 3 if self.native else 0,
                "numba": "not_used_no_additional_jit_path",
                "fast_math": False,
            }
        )
