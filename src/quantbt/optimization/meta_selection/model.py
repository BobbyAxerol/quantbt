"""Origin-sum Ridge fit and complete immutable mathematical model vintage."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .common import MetaRecordError, digest, freeze, utc, wire
from .descriptors import DescriptorSchema, OriginBalancedStandardizer
from .history import HistorySnapshot
from .numerics import NumericLimits, NumericRuntime, reference_fit, solution_diagnostics


@dataclass(frozen=True, slots=True)
class RidgeSettings:
    lambda_reg: float = 10.0
    min_matured_origins: int = 12
    epsilon: float = 0.10
    tie_tolerance: float = 1e-10
    learner_id: str = "ridge_origin_sum_v1"
    target_version: str = "same_origin_signed_relative_decay_v1"
    weight_version: str = "one_origin_sum_nonanchor_1_over_M_v1"
    selection_policy: str = "signed_min_y_predicted_q_floor_v1"
    ood_policy: str = "whole_pool_native_fallback_v1"

    def __post_init__(self):
        if (
            not math.isfinite(self.lambda_reg)
            or self.lambda_reg <= 0
            or not math.isfinite(self.epsilon)
            or self.epsilon < 0
            or not math.isfinite(self.tie_tolerance)
            or self.tie_tolerance < 0
        ):
            raise MetaRecordError(
                "META_POLICY_INVALID: positive lambda, finite nonnegative guard/tie required"
            )
        if type(self.min_matured_origins) is not int or self.min_matured_origins <= 0:
            raise MetaRecordError(
                "META_POLICY_INVALID: minimum origins must be positive"
            )
        expected = (
            "ridge_origin_sum_v1",
            "same_origin_signed_relative_decay_v1",
            "one_origin_sum_nonanchor_1_over_M_v1",
            "signed_min_y_predicted_q_floor_v1",
            "whole_pool_native_fallback_v1",
        )
        if (
            self.learner_id,
            self.target_version,
            self.weight_version,
            self.selection_policy,
            self.ood_policy,
        ) != expected:
            raise MetaRecordError("META_POLICY_VERSION_UNSUPPORTED")


def schema_payload(schema):
    return {
        "parameters": schema.space.metadata()["parameters"],
        "include_activity": schema.include_activity,
        "version": schema.version,
        "schema_id": schema.schema_id,
        "feature_names": schema.feature_names,
    }


def schema_from_payload(payload):
    if set(payload) != {
        "parameters",
        "include_activity",
        "version",
        "schema_id",
        "feature_names",
    }:
        raise MetaRecordError(
            "META_MODEL_SCHEMA_INVALID: complete descriptor basis required"
        )
    ranges = {}
    for p in payload["parameters"]:
        if (
            set(p)
            != {
                "name",
                "kind",
                "low",
                "high",
                "step",
                "scale",
                "categories",
                "active_if",
                "fixed",
                "fixed_value",
            }
            or p["name"] in ranges
        ):
            raise MetaRecordError(
                "META_MODEL_SCHEMA_INVALID: parameter/vocabulary missing"
            )
        kind = p["kind"]
        value = {"kind": kind, "active_if": dict(p["active_if"])}
        if p["fixed"]:
            value.update(kind="fixed", value=p["fixed_value"])
        elif kind in {"categorical", "boolean"}:
            value["choices"] = list(p["categories"])
        else:
            value.update(
                low=p["low"], high=p["high"], step=p["step"], log=p["scale"] == "log"
            )
        ranges[p["name"]] = value
    schema = DescriptorSchema(
        ranges, include_activity=payload["include_activity"], native_policy="reference"
    )
    if (
        schema.schema_id != payload["schema_id"]
        or schema.version != payload["version"]
        or schema.feature_names != tuple(payload["feature_names"])
    ):
        raise MetaRecordError("META_MODEL_SCHEMA_INVALID: basis identity mismatch")
    return schema


def scaler_payload(scaler):
    return {
        "schema_id": scaler.schema_id,
        "training_snapshot_id": scaler.training_snapshot_id,
        "feature_names": scaler.feature_names,
        "numeric_columns": scaler.numeric_columns,
        "mean": scaler.mean.tolist(),
        "scale": scaler.scale.tolist(),
        "constant": scaler.constant.tolist(),
        "observed": scaler.observed.tolist(),
        "constant_tolerance": scaler.constant_tolerance,
        "version": scaler.version,
    }


@dataclass(frozen=True, slots=True)
class MetaModelArtifact:
    family_id: str
    training_snapshot_id: str
    information_as_of: pd.Timestamp
    fit_completed_at: pd.Timestamp
    wall_generated_at: pd.Timestamp
    clock_mode: str
    history_permissions: dict
    revision_references: tuple
    fit_row_references: tuple
    origin_count: int
    schema: dict
    scaler: dict
    settings: RidgeSettings
    numeric_limits: NumericLimits
    coefficients: tuple[float, ...]
    reference_gram: tuple
    reference_b: tuple[float, ...]
    diagnostics: dict
    backend: dict
    basis_version: str = "qms_anchor_contrast_origin_balanced_v1"

    def __post_init__(self):
        for name in ("information_as_of", "fit_completed_at", "wall_generated_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        for name in (
            "history_permissions",
            "schema",
            "scaler",
            "diagnostics",
            "backend",
        ):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        for name in (
            "revision_references",
            "fit_row_references",
            "coefficients",
            "reference_gram",
            "reference_b",
        ):
            object.__setattr__(
                self,
                name,
                tuple(
                    tuple(x) if isinstance(x, (tuple, list)) else x
                    for x in getattr(self, name)
                ),
            )
        if (
            self.basis_version != "qms_anchor_contrast_origin_balanced_v1"
            or self.clock_mode not in {"historical_replay", "observed_live"}
            or self.fit_completed_at < self.information_as_of
            or (
                self.clock_mode == "observed_live"
                and self.wall_generated_at < self.fit_completed_at
            )
        ):
            raise MetaRecordError("META_MODEL_CLOCK_OR_BASIS_INVALID")
        descriptor = schema_from_payload(self.schema)
        scaler = OriginBalancedStandardizer(**dict(self.scaler))
        d = len(descriptor.feature_names)
        if (
            scaler.schema_id != descriptor.schema_id
            or scaler.feature_names != descriptor.feature_names
            or scaler.numeric_columns != descriptor.numeric_columns
            or scaler.training_snapshot_id != self.training_snapshot_id
            or np.shape(self.reference_gram) != (d, d)
            or np.shape(self.reference_b) != (d,)
            or np.shape(self.coefficients) != (d,)
            or type(self.origin_count) is not int
            or self.origin_count < self.settings.min_matured_origins
        ):
            raise MetaRecordError("META_MODEL_SUPPORT_OR_SHAPE_INVALID")
        refs = self.revision_references
        if (
            len(refs) < self.origin_count
            or len({r[0] for r in refs}) != len(refs)
            or any(len(r) != 3 or r[1] != r[2] for r in refs)
        ):
            raise MetaRecordError("META_MODEL_REVISION_REFERENCES_INVALID")
        permissions = self.history_permissions
        if set(permissions) != {
            "corpora",
            "cohorts",
            "exposures",
            "snapshot_order",
        } or any(not permissions[k] for k in ("corpora", "cohorts", "exposures")):
            raise MetaRecordError("META_MODEL_PERMISSIONS_INVALID")
        expected_snapshot = digest(
            {
                "schema": "qms-training-snapshot-v1",
                "family": self.family_id,
                "corpora": permissions["corpora"],
                "cohorts": permissions["cohorts"],
                "exposures": permissions["exposures"],
                "as_of": self.information_as_of,
                "order": permissions["snapshot_order"],
                "references": sorted(refs),
            }
        )
        if expected_snapshot != self.training_snapshot_id:
            raise MetaRecordError("META_MODEL_SNAPSHOT_INVALID")
        ids = [(row[0], row[2]) for row in self.fit_row_references]
        if len(ids) != len(set(ids)) or any(
            len(row) != 4 or (row[0], row[1], row[1]) not in refs
            for row in self.fit_row_references
        ):
            raise MetaRecordError("META_MODEL_FIT_MASK_INVALID")
        if len({r[0] for r in self.fit_row_references}) != self.origin_count:
            raise MetaRecordError("META_MODEL_ORIGIN_SUPPORT_INVALID")
        for tid, _, _ in refs:
            weights = [r[3] for r in self.fit_row_references if r[0] == tid]
            if any(
                not math.isclose(w, 1 / len(weights), rel_tol=0, abs_tol=1e-14)
                for w in weights
            ):
                raise MetaRecordError("META_MODEL_ORIGIN_WEIGHT_INVALID")
        gram, b, beta = (
            np.asarray(a, dtype=float)
            for a in (self.reference_gram, self.reference_b, self.coefficients)
        )
        if not np.allclose(gram, gram.T, rtol=0, atol=1e-12):
            raise MetaRecordError("META_MODEL_GRAM_INVALID")
        try:
            np.linalg.cholesky(gram)
        except np.linalg.LinAlgError as exc:
            raise MetaRecordError("META_MODEL_GRAM_NOT_SPD") from exc
        solution_diagnostics(gram, b, beta, self.numeric_limits)

    @property
    def model_id(self):
        return digest({"schema": "qms-ridge-model-v1", "model": self})

    @property
    def raw_unit_coefficients(self):
        return tuple(np.asarray(self.coefficients) / np.asarray(self.scaler["scale"]))


@dataclass(frozen=True, slots=True)
class FitOutcome:
    model: MetaModelArtifact | None
    reason: str
    origin_count: int

    def __post_init__(self):
        if (
            type(self.origin_count) is not int
            or self.origin_count < 0
            or (self.model is None and self.reason != "META_SUPPORT_INSUFFICIENT")
            or (
                self.model is not None
                and (
                    self.reason != "FIT_VALID"
                    or self.origin_count != self.model.origin_count
                )
            )
        ):
            raise MetaRecordError("META_FIT_DISPOSITION_INVALID")


class RidgeLearner:
    def __init__(self, *, settings=RidgeSettings(), runtime=None):
        self.settings, self.runtime = settings, runtime or NumericRuntime()

    def fit(
        self, schema, snapshot, *, fit_completed_at=None, clock_mode="historical_replay"
    ):
        if not isinstance(snapshot, HistorySnapshot):
            raise MetaRecordError("META_FIT_SNAPSHOT_INVALID")
        if snapshot.origin_count < self.settings.min_matured_origins:
            return FitOutcome(None, "META_SUPPORT_INSUFFICIENT", snapshot.origin_count)
        scaler = OriginBalancedStandardizer.fit(schema, snapshot)
        records, candidate_indices, anchor_indices, ys, weights, row_refs = (
            [],
            [],
            [],
            [],
            [],
            [],
        )
        for revision in sorted(snapshot.revisions, key=lambda r: r.task.task_id):
            task = revision.task
            rows = revision.training_rows
            if not rows:
                continue
            ids = {r.candidate_evaluation_id for r in rows} | {
                task.anchor_candidate_evaluation_id
            }
            candidates = tuple(
                sorted(
                    (c for c in task.candidates if c.evaluation_id in ids),
                    key=lambda c: c.evaluation_id,
                )
            )
            lookup = {
                c.evaluation_id: len(records) + i for i, c in enumerate(candidates)
            }
            records.extend(candidates)
            anchor = lookup[task.anchor_candidate_evaluation_id]
            for row in rows:
                candidate_indices.append(lookup[row.candidate_evaluation_id])
                anchor_indices.append(anchor)
                ys.append(row.y)
                weights.append(row.origin_weight)
                row_refs.append(
                    (
                        task.task_id,
                        revision.revision_id,
                        row.candidate_evaluation_id,
                        row.origin_weight,
                    )
                )
        values, unsupported = self.runtime.transform(schema.encode(records), scaler)
        if unsupported.any():
            raise MetaRecordError("META_HISTORICAL_SUPPORT_INVALID")
        v = np.ascontiguousarray(values[candidate_indices] - values[anchor_indices])
        y, w = (np.ascontiguousarray(a, dtype=float) for a in (ys, weights))
        gram, b, beta = self.runtime.fit(v, y, w, self.settings.lambda_reg)
        diagnostics = solution_diagnostics(gram, b, beta, self.runtime.limits)
        # Independent whole-fit reference is retained as small sufficient statistics
        # for audited boundary inference, not N rows/equity paths in every model.
        rg, rb, rbeta = (
            reference_fit(v, y, w, self.settings.lambda_reg, self.runtime.limits)
            if self.runtime.native is not None
            else (gram, b, beta)
        )
        if any(
            not np.allclose(
                a,
                e,
                rtol=self.runtime.limits.parity_rtol,
                atol=self.runtime.limits.parity_atol,
            )
            for a, e in ((gram, rg), (b, rb), (beta, rbeta))
        ):
            raise MetaRecordError("META_NATIVE_PARITY_FAILED: whole fit")
        completed = utc(
            fit_completed_at
            if fit_completed_at is not None
            else pd.Timestamp.now(tz="UTC")
        )
        model = MetaModelArtifact(
            snapshot.family_id,
            snapshot.snapshot_id,
            snapshot.information_as_of,
            completed,
            pd.Timestamp.now(tz="UTC"),
            clock_mode,
            {
                "corpora": snapshot.authorized_corpora,
                "cohorts": snapshot.outcome_origins,
                "exposures": snapshot.research_exposures,
                "snapshot_order": snapshot.snapshot_order,
            },
            tuple(
                sorted(
                    (r.task.task_id, r.revision_id, r.content_digest)
                    for r in snapshot.revisions
                )
            ),
            tuple(row_refs),
            snapshot.origin_count,
            schema_payload(schema),
            scaler_payload(scaler),
            self.settings,
            self.runtime.limits,
            tuple(beta),
            tuple(map(tuple, rg)),
            tuple(rb),
            {
                **diagnostics,
                "rows": len(y),
                "dimension": len(beta),
                "effective_mean_origin_lambda": self.settings.lambda_reg
                / snapshot.origin_count,
                "reference_fit_verified": True,
                "dense_weight_matrix": False,
                "intercept": False,
                "support_override": self.settings.min_matured_origins != 12,
            },
            wire(self.runtime.metadata),
        )
        return FitOutcome(model, "FIT_VALID", snapshot.origin_count)
