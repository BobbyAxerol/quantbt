"""Compiled, schema-driven float64 batches and historical origin-balanced scaling."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from ..parameter_space import NormalizedSearchSpace
from .common import MetaRecordError, digest, frozen_array
from .records import OutcomeStatus


@dataclass(frozen=True, slots=True)
class DescriptorBatch:
    schema_id: str
    evaluation_ids: tuple[str, ...]
    feature_names: tuple[str, ...]
    values: np.ndarray
    active: np.ndarray
    valid: np.ndarray
    numeric_columns: tuple[int, ...]

    def __post_init__(self):
        for name in ("evaluation_ids", "feature_names", "numeric_columns"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        shape = (len(self.evaluation_ids), len(self.feature_names))
        if (
            np.shape(self.values) != shape
            or np.shape(self.active) != shape
            or np.shape(self.valid) != (shape[0],)
        ):
            raise MetaRecordError(
                "META_DESCRIPTOR_SHAPE: no padding/truncation allowed"
            )
        if (
            len(set(self.evaluation_ids)) != shape[0]
            or len(set(self.feature_names)) != shape[1]
        ):
            raise MetaRecordError("duplicate descriptor IDs/features")
        if len(set(self.numeric_columns)) != len(self.numeric_columns) or any(
            type(c) is not int or c < 0 or c >= shape[1] for c in self.numeric_columns
        ):
            raise MetaRecordError("numeric descriptor columns invalid")
        if not np.isfinite(
            np.asarray(self.values)[np.asarray(self.valid, dtype=bool)]
        ).all():
            raise MetaRecordError("valid descriptor rows must be finite")
        for name, dtype in (
            ("values", np.float64),
            ("active", np.bool_),
            ("valid", np.bool_),
        ):
            object.__setattr__(
                self, name, frozen_array(getattr(self, name), dtype=dtype)
            )


class DescriptorSchema:
    version = "qms-parameters_raw_is_activity_v1"

    def __init__(self, ranges, *, include_activity=True, native_policy="auto"):
        if native_policy not in {"auto", "require", "reference"}:
            raise MetaRecordError("invalid descriptor native policy")
        if native_policy == "require":
            raise NotImplementedError(
                "META_NATIVE_CAPABILITY_MISSING: installed ABI has no QMS descriptor transform"
            )
        self.space = NormalizedSearchSpace(ranges)
        self.include_activity = bool(include_activity)
        names, numeric, blocks = [], [], []
        for spec in self.space.specs:
            if not spec.variable:
                continue
            start = len(names)
            if spec.choices:
                names.extend(
                    f"{spec.name}:category:{i}" for i in range(len(spec.choices))
                )
            else:
                numeric.append(len(names))
                names.append(f"{spec.name}:numeric")
            if spec.active_if:
                names.append(f"{spec.name}:active")
            blocks.append((spec, start, len(names)))
        self.parameter_columns = len(names)
        numeric.append(len(names))
        names.append("raw_is_sharpe")
        if self.include_activity:
            numeric.append(len(names))
            names.append("log1p_is_activity")
        self.feature_names, self.numeric_columns, self.blocks = (
            tuple(names),
            tuple(numeric),
            tuple(blocks),
        )
        self.schema_id = digest(
            {
                "version": self.version,
                "space": self.space.metadata(),
                "features": self.feature_names,
                "include_activity": self.include_activity,
            }
        )
        self.backend = {
            "requested": native_policy,
            "selected": "numpy_reference",
            "reason": "QMS-03 record foundation; installed ABI has no meta transform; native numeric addition owned by QMS-04",
            "dtype": "float64",
            "batch_boundary": "one_contiguous_matrix_per_pool",
            "ffi_calls": 0,
            "fast_math": False,
        }

    def _parameter_values(self, candidates):
        candidates = tuple(candidates)
        values = np.zeros((len(candidates), self.parameter_columns), dtype=np.float64)
        active = np.zeros_like(values, dtype=bool)
        params = [self.space.effective(c.effective_params) for c in candidates]
        for spec, start, stop in self.blocks:
            mask = np.array([spec.name in p for p in params], dtype=bool)
            if spec.choices:
                for offset, choice in enumerate(spec.choices):
                    values[:, start + offset] = [
                        float(mask[i] and p.get(spec.name) == choice) / np.sqrt(2)
                        for i, p in enumerate(params)
                    ]
                    active[:, start + offset] = mask
            else:
                low, high = float(spec.low), float(spec.high)
                if spec.log:
                    low, high = math.log(low), math.log(high)
                present = np.array(
                    [float(p[spec.name]) for p in params if spec.name in p]
                )
                if spec.log:
                    present = np.log(present)
                values[mask, start] = (present - low) / (high - low)
                active[:, start] = mask
            if spec.active_if:
                values[:, stop - 1] = mask
                active[:, stop - 1] = True
        return values, active

    def parameter_geometry(self, candidates):
        values, _active = self._parameter_values(candidates)
        for spec, start, stop in self.blocks:
            if spec.active_if:
                values[:, stop - 1] /= np.sqrt(2)
                if not spec.choices:
                    values[:, start] /= np.sqrt(2)
        return frozen_array(values)

    def encode(self, candidates):
        candidates = tuple(candidates)
        parameters, parameter_active = self._parameter_values(candidates)
        values = np.full((len(candidates), len(self.feature_names)), np.nan)
        active = np.ones_like(values, dtype=bool)
        values[:, : self.parameter_columns] = parameters
        active[:, : self.parameter_columns] = parameter_active
        valid = np.array(
            [
                c.observation.status == OutcomeStatus.VALID
                and (
                    not self.include_activity
                    or c.observation.activity_count is not None
                )
                for c in candidates
            ],
            dtype=bool,
        )
        for i, c in enumerate(candidates):
            if valid[i]:
                values[i, self.parameter_columns] = c.observation.raw_sharpe
                if self.include_activity:
                    values[i, self.parameter_columns + 1] = np.log1p(
                        c.observation.activity_count
                    )
        return DescriptorBatch(
            self.schema_id,
            tuple(c.evaluation_id for c in candidates),
            self.feature_names,
            values,
            active,
            valid,
            self.numeric_columns,
        )


@dataclass(frozen=True, slots=True)
class OriginBalancedStandardizer:
    schema_id: str
    training_snapshot_id: str
    feature_names: tuple[str, ...]
    numeric_columns: tuple[int, ...]
    mean: np.ndarray
    scale: np.ndarray
    constant: np.ndarray
    observed: np.ndarray
    constant_tolerance: float = 1e-12
    version: str = "origin_balanced_zscore_v1"

    def __post_init__(self):
        object.__setattr__(self, "feature_names", tuple(self.feature_names))
        object.__setattr__(self, "numeric_columns", tuple(self.numeric_columns))
        if (
            self.version != "origin_balanced_zscore_v1"
            or self.constant_tolerance != 1e-12
        ):
            raise MetaRecordError(
                "numeric support changes require a new transform version"
            )
        n = len(self.feature_names)
        for name, dtype in (
            ("mean", np.float64),
            ("scale", np.float64),
            ("constant", np.bool_),
            ("observed", np.bool_),
        ):
            if np.shape(getattr(self, name)) != (n,):
                raise MetaRecordError("META_DESCRIPTOR_SHAPE: scaler mismatch")
            object.__setattr__(
                self, name, frozen_array(getattr(self, name), dtype=dtype)
            )
        if (
            not np.isfinite(self.mean).all()
            or not np.isfinite(self.scale).all()
            or (self.scale <= 0).any()
        ):
            raise MetaRecordError("invalid numeric transform; no epsilon rescue")

    @classmethod
    def fit(cls, schema, snapshot):
        from .history import HistorySnapshot

        if not isinstance(snapshot, HistorySnapshot):
            raise MetaRecordError(
                "fit requires an authorized immutable history snapshot"
            )
        batches = []
        for revision in snapshot.revisions:
            if revision.task.family.descriptor_schema_id != schema.schema_id:
                raise MetaRecordError("descriptor family/schema mismatch")
            ids = {row.candidate_evaluation_id for row in revision.training_rows}
            if ids:
                ids.add(revision.task.anchor_candidate_evaluation_id)
                batches.append(
                    schema.encode(
                        c for c in revision.task.candidates if c.evaluation_id in ids
                    )
                )
        if not batches:
            raise MetaRecordError(
                "META_SUPPORT_INSUFFICIENT: no matured labeled origins"
            )
        if any(not batch.valid.all() for batch in batches):
            raise MetaRecordError("historical descriptor support is not qualified")
        values = np.concatenate([b.values for b in batches])
        active = np.concatenate([b.active for b in batches])
        weights = np.concatenate(
            [np.full(len(b.evaluation_ids), 1 / len(b.evaluation_ids)) for b in batches]
        )
        mean = np.zeros(len(schema.feature_names))
        scale = np.ones_like(mean)
        constant, observed = (
            np.zeros_like(mean, dtype=bool),
            np.zeros_like(mean, dtype=bool),
        )
        for col in schema.numeric_columns:
            mask = active[:, col]
            if not mask.any():
                constant[col] = True
                continue
            observed[col] = True
            w, x = weights[mask], values[mask, col]
            mean[col] = np.dot(w, x) / w.sum()
            variance = np.dot(w, (x - mean[col]) ** 2) / w.sum()
            constant[col] = np.all(np.abs(x - mean[col]) <= 1e-12)
            if not constant[col]:
                scale[col] = np.sqrt(variance)
        return cls(
            schema.schema_id,
            snapshot.snapshot_id,
            schema.feature_names,
            schema.numeric_columns,
            mean,
            scale,
            constant,
            observed,
        )

    def transform(self, batch):
        if (
            batch.schema_id != self.schema_id
            or batch.feature_names != self.feature_names
            or batch.numeric_columns != self.numeric_columns
        ):
            raise MetaRecordError(
                "META_DESCRIPTOR_SHAPE: schema/feature order mismatch"
            )
        values = np.array(batch.values, copy=True)
        unsupported = ~np.array(batch.valid, copy=True)
        for col in self.numeric_columns:
            mask = batch.active[:, col] & batch.valid
            if self.constant[col]:
                unsupported |= mask & (
                    ~self.observed[col]
                    | (
                        np.abs(values[:, col] - self.mean[col])
                        > self.constant_tolerance
                    )
                )
                values[mask, col] = 0.0
            else:
                values[mask, col] = (values[mask, col] - self.mean[col]) / self.scale[
                    col
                ]
            values[~batch.active[:, col], col] = 0.0
        return frozen_array(values), frozen_array(unsupported, dtype=bool)
