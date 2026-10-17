"""Research-only learner seam over the existing history, geometry and Q guard."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from quantbt.optimization.meta_selection.artifacts import dumps_decision, loads_decision
from quantbt.optimization.meta_selection.common import (
    MetaRecordError,
    canonical,
    digest,
    freeze,
    utc,
    token,
)
from quantbt.optimization.meta_selection.descriptors import OriginBalancedStandardizer
from quantbt.optimization.meta_selection.model import (
    FitOutcome,
    RidgeSettings,
    scaler_payload,
)
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from quantbt.optimization.meta_selection.selection import (
    MetaSelectionDecision,
    MetaSelector,
    rank_decision,
    select_indices,
)

from .families import FamilySpec, NumericModel, fit_family


VERSION = "m4-ml-family-context-v1"


@dataclass(frozen=True, slots=True)
class PreparedHistory:
    schema_id: str
    family_id: str
    snapshot_id: str
    information_as_of: object
    K: int
    scaler: OriginBalancedStandardizer
    X: np.ndarray
    y: np.ndarray
    weights: np.ndarray


def prepare_history(schema, snapshot, runtime):
    """Use exactly V1's historical candidates, scaler and origin replacement weights."""
    if snapshot.origin_count < 12:
        return None
    estimated = (
        (len(snapshot.training_rows) + snapshot.origin_count)
        * len(schema.feature_names)
        * 64
    )
    if estimated > runtime.limits.max_workspace_bytes:
        raise MetaRecordError("MLR_FAMILY_WORKSPACE_EXCEEDED")
    scaler = OriginBalancedStandardizer.fit(schema, snapshot)
    records, indices, anchors, ys, weights = [], [], [], [], []
    for revision in sorted(snapshot.revisions, key=lambda r: r.task.task_id):
        if revision.task.family.descriptor_schema_id != schema.schema_id:
            raise MetaRecordError("MLR_FAMILY_HISTORY_SCHEMA_INVALID")
        rows, task = revision.training_rows, revision.task
        if not rows:
            continue
        ids = {r.candidate_evaluation_id for r in rows} | {
            task.anchor_candidate_evaluation_id
        }
        candidates = sorted(
            (c for c in task.candidates if c.evaluation_id in ids),
            key=lambda c: c.evaluation_id,
        )
        lookup = {c.evaluation_id: len(records) + i for i, c in enumerate(candidates)}
        records.extend(candidates)
        for row in rows:
            indices.append(lookup[row.candidate_evaluation_id])
            anchors.append(lookup[task.anchor_candidate_evaluation_id])
            ys.append(row.y)
            weights.append(row.origin_weight)
    values, unsupported = runtime.transform(schema.encode(records), scaler)
    if unsupported.any():
        raise MetaRecordError("MLR_FAMILY_HISTORICAL_SUPPORT_INVALID")
    arrays = (
        np.ascontiguousarray(values[indices] - values[anchors]),
        np.ascontiguousarray(ys, dtype=float),
        np.ascontiguousarray(weights, dtype=float),
    )
    if not np.isclose(arrays[2].sum(), snapshot.origin_count, atol=1e-12, rtol=1e-12):
        raise MetaRecordError("MLR_FAMILY_ORIGIN_WEIGHT_INVALID")
    # Byte-backed arrays cannot be made writable again by toggling NumPy flags.
    arrays = tuple(
        np.frombuffer(a.tobytes(), dtype=a.dtype).reshape(a.shape) for a in arrays
    )
    return PreparedHistory(
        schema.schema_id,
        snapshot.family_id,
        snapshot.snapshot_id,
        snapshot.information_as_of,
        snapshot.origin_count,
        scaler,
        *arrays,
    )


@dataclass(frozen=True, slots=True)
class FamilyFit:
    spec: FamilySpec
    family_id: str
    schema_id: str
    snapshot_id: str
    information_as_of: object
    fit_completed_at: object
    K: int
    model: NumericModel | None
    scaler: dict | None
    training: dict
    version: str = VERSION

    def __post_init__(self):
        if (
            self.version != VERSION
            or type(self.K) is not int
            or self.K < 0
            or not isinstance(self.spec, FamilySpec)
            or (self.model is None) != (self.K < 12)
        ):
            raise MetaRecordError("MLR_FAMILY_CONTEXT_INVALID")
        for identity in (self.family_id, self.schema_id, self.snapshot_id):
            token(identity)
        for name in ("information_as_of", "fit_completed_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if self.fit_completed_at < self.information_as_of:
            raise MetaRecordError("MLR_FAMILY_CONTEXT_CLOCK_INVALID")
        if self.model is not None:
            if (
                not isinstance(self.model, NumericModel)
                or self.model.spec != self.spec
                or self.scaler["schema_id"] != self.schema_id
            ):
                raise MetaRecordError("MLR_FAMILY_CONTEXT_RECIPE_INVALID")
            if self.scaler["training_snapshot_id"] != self.snapshot_id:
                raise MetaRecordError("MLR_FAMILY_CONTEXT_SCALER_INVALID")
            scaler = OriginBalancedStandardizer(**dict(self.scaler))
            if self.model.dimension != len(scaler.feature_names):
                raise MetaRecordError("MLR_FAMILY_CONTEXT_DIMENSION_INVALID")
            meta = self.model.metadata
            if (
                not np.isclose(meta["weight_sum"], self.K, rtol=1e-12, atol=1e-12)
                or self.training.get("K") != self.K
                or self.training.get("N") != meta["n_rows"]
                or self.training.get("d") != self.model.dimension
                or self.training.get("status") != "FIT"
                or canonical(self.training.get("backend")) != canonical(meta)
                or not np.isclose(
                    self.training.get("served_y_mse"),
                    meta["train_served_mse"],
                    rtol=1e-9,
                    atol=1e-10,
                )
            ):
                raise MetaRecordError("MLR_FAMILY_CONTEXT_NORMALIZATION_INVALID")
            object.__setattr__(self, "scaler", freeze(self.scaler))
        object.__setattr__(self, "training", freeze(self.training))

    @property
    def fit_id(self):
        return digest(dict(schema=VERSION, context=self))


@dataclass(frozen=True, slots=True)
class FamilyArtifact:
    fit: FamilyFit
    decision: object
    task_digest: str

    def __post_init__(self):
        token(self.task_digest)
        if (
            not isinstance(self.fit, FamilyFit)
            or not isinstance(self.decision, MetaSelectionDecision)
            or self.decision.model_id != (self.fit.fit_id if self.fit.model else None)
            or self.decision.training_snapshot_id
            != (self.fit.snapshot_id if self.fit.model else None)
            or self.fit.information_as_of > self.decision.information_as_of
        ):
            raise MetaRecordError("MLR_FAMILY_ARTIFACT_CONTEXT_INVALID")

    @property
    def artifact_id(self):
        return digest(
            dict(
                schema=VERSION,
                fit_id=self.fit.fit_id,
                decision_id=self.decision.decision_id,
                task=self.task_digest,
            )
        )


class FamilyResearch:
    """Run-local bounded preparation/fit ownership; never owns account or optimizer state."""

    def __init__(self, *, runtime=None, max_fits=2000, max_cache_bytes=8_000_000):
        if type(max_fits) is not int or not 0 <= max_fits <= 2000:
            raise MetaRecordError("MLR_FAMILY_FIT_BUDGET_INVALID")
        if type(max_cache_bytes) is not int or not 0 <= max_cache_bytes <= 8_000_000:
            raise MetaRecordError("MLR_FAMILY_CACHE_BUDGET_INVALID")
        self.runtime = runtime or NumericRuntime(native_policy="reference")
        self.max_fits, self.max_cache_bytes = max_fits, max_cache_bytes
        self.fits = self.failed_fits = self.cache_hits = 0
        self.regression_fit_charge = 2 if self.runtime.native is not None else 0
        self.cache = OrderedDict()
        self.prepared = None
        self.prepared_limits = None
        self.source_id = digest(
            {
                p.name: sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__), Path(__file__).with_name("families.py"))
            }
        )

    def clear(self):
        self.cache.clear()
        self.prepared = None
        self.prepared_limits = None
        self.runtime.work_cache.clear()

    def fit(self, spec, schema, snapshot, *, fit_completed_at):
        completed = utc(fit_completed_at)
        if completed < snapshot.information_as_of:
            raise MetaRecordError("MLR_FAMILY_FIT_CLOCK_INVALID")
        key = digest(
            dict(
                source=self.source_id,
                recipe=spec.recipe_id,
                schema=schema.schema_id,
                snapshot=snapshot.snapshot_id,
                completed=completed,
                backend=self.runtime.policy,
                native=self.runtime.native_identity,
                numeric_limits=self.runtime.limits,
            )
        )
        if key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(key)
            return self.cache[key][0]
        if snapshot.origin_count < 12:
            return FamilyFit(
                spec,
                snapshot.family_id,
                schema.schema_id,
                snapshot.snapshot_id,
                snapshot.information_as_of,
                completed,
                snapshot.origin_count,
                None,
                None,
                dict(status="NO_FIT", K=snapshot.origin_count),
            )
        charge = (
            (
                8
                if self.runtime.policy == "auto"
                else 1 + int(self.runtime.native is not None)
            )
            if spec.code == "B1"
            else 1
        )
        if (
            self.fits >= self.max_fits
            or self.regression_fit_charge + charge > self.max_fits
        ):
            raise MetaRecordError("MLR_FAMILY_FIT_BUDGET_EXHAUSTED")
        self.fits += 1
        charged = False
        try:
            if (
                self.prepared is None
                or self.prepared.snapshot_id != snapshot.snapshot_id
                or self.prepared.schema_id != schema.schema_id
                or self.prepared_limits != self.runtime.limits
            ):
                self.prepared = None
                self.prepared = prepare_history(schema, snapshot, self.runtime)
                self.prepared_limits = self.runtime.limits
            prepared = self.prepared
            model = fit_family(
                spec, prepared.X, prepared.y, prepared.weights, runtime=self.runtime
            )
            self.regression_fit_charge += model.metadata["fit_count"]
            charged = True
            prediction = model.predict(prepared.X)
            errors = prediction - prepared.y
            training = dict(
                status="FIT",
                K=prepared.K,
                N=len(prepared.y),
                d=prepared.X.shape[1],
                served_y_mse=float(np.dot(prepared.weights, errors**2) / prepared.K),
                served_y_mae=float(
                    np.dot(prepared.weights, np.abs(errors)) / prepared.K
                ),
                backend=dict(model.metadata),
            )
            result = FamilyFit(
                spec,
                snapshot.family_id,
                schema.schema_id,
                snapshot.snapshot_id,
                snapshot.information_as_of,
                completed,
                snapshot.origin_count,
                model,
                scaler_payload(prepared.scaler),
                training,
            )
        except Exception:
            self.failed_fits += 1
            if not charged:
                self.regression_fit_charge += charge
            raise
        size = len(canonical(result).encode())
        if size <= self.max_cache_bytes:
            while self.cache and (
                len(self.cache) >= 32
                or sum(n for _, n in self.cache.values()) + size > self.max_cache_bytes
            ):
                self.cache.popitem(last=False)
            self.cache[key] = (result, size)
        return result

    def propose(self, task, fitted, *, schema, full_ranking=False, mode="proposal"):
        if (
            task.family.family_id != fitted.family_id
            or schema.schema_id != fitted.schema_id
            or fitted.information_as_of > task.data_cutoff
            or fitted.fit_completed_at > task.decision_sealed_at
        ):
            raise MetaRecordError("MLR_FAMILY_PROPOSAL_CONTEXT_INVALID")
        # Reuse original fallback, raw-best, activation and clock conventions.
        decision = MetaSelector(runtime=self.runtime).propose(
            task,
            FitOutcome(None, "META_SUPPORT_INSUFFICIENT", 0),
            schema=schema,
            mode=mode,
        )
        if fitted.model is None:
            return FamilyArtifact(fitted, decision, digest(task))
        decision = replace(
            decision,
            model_id=fitted.fit_id,
            training_snapshot_id=fitted.snapshot_id,
            fit_completed_at=fitted.fit_completed_at,
        )
        candidates = task.candidates
        batch = schema.encode(candidates)
        batch = replace(
            batch,
            valid=batch.valid
            & np.array(
                [c.observation.verification != "unverified" for c in candidates]
            ),
        )
        ai = next(
            i
            for i, c in enumerate(candidates)
            if c.evaluation_id == task.anchor_candidate_evaluation_id
        )
        if not batch.valid[ai]:
            decision = replace(decision, status="META_NOT_APPLICABLE_METRIC")
        else:
            values, unsupported = self.runtime.transform(
                batch, OriginBalancedStandardizer(**dict(fitted.scaler))
            )
            if (unsupported & batch.valid).any():
                decision = replace(
                    decision,
                    status="META_OOD_NATIVE_FALLBACK",
                    guard=dict(
                        ood_policy=RidgeSettings().ood_policy,
                        unsupported_ids=tuple(
                            c.evaluation_id
                            for i, c in enumerate(candidates)
                            if unsupported[i] and batch.valid[i]
                        ),
                    ),
                )
            else:
                indices = np.flatnonzero(batch.valid)
                selected = tuple(candidates[i] for i in indices)
                anchor = candidates[ai]
                local_ai = next(
                    i
                    for i, c in enumerate(selected)
                    if c.evaluation_id == anchor.evaluation_id
                )
                X = np.ascontiguousarray(values[indices] - values[ai])
                y = fitted.model.predict(X)
                q = (
                    np.array(
                        [
                            c.observation.raw_sharpe - anchor.observation.raw_sharpe
                            for c in selected
                        ]
                    )
                    - y
                )
                if y[local_ai] != 0.0 or q[local_ai] != 0.0:
                    raise MetaRecordError("MLR_FAMILY_SERVED_ANCHOR_INVALID")
                geometry = schema.parameter_geometry(selected)
                distances = np.linalg.norm(geometry - geometry[local_ai], axis=1)
                settings = RidgeSettings()
                wi, ti, safe = select_indices(
                    y,
                    q,
                    distances,
                    tuple((c.candidate_id, c.evaluation_id) for c in selected),
                    epsilon=settings.epsilon,
                    tie_tolerance=settings.tie_tolerance,
                )
                predictions = tuple(
                    dict(
                        evaluation_id=c.evaluation_id,
                        candidate_id=c.candidate_id,
                        raw_is=c.observation.raw_sharpe,
                        yhat=float(y[i]),
                        qhat=float(q[i]),
                        distance=float(distances[i]),
                        eligible=bool(safe[i]),
                        exclusion=None if safe[i] else "PREDICTED_Q_FLOOR",
                    )
                    for i, c in enumerate(selected)
                )
                predictions += tuple(
                    dict(
                        evaluation_id=c.evaluation_id,
                        candidate_id=c.candidate_id,
                        raw_is=c.observation.raw_sharpe,
                        yhat=None,
                        qhat=None,
                        distance=None,
                        eligible=False,
                        exclusion=c.observation.status.value,
                    )
                    for i, c in enumerate(candidates)
                    if not batch.valid[i]
                )
                decision = replace(
                    decision,
                    proposed_evaluation_id=selected[wi].evaluation_id,
                    proposed_params=dict(selected[wi].effective_params),
                    status="META_MODEL_PROPOSAL",
                    predictions=predictions,
                    tie_set=tuple(sorted(selected[i].evaluation_id for i in ti)),
                    guard=dict(
                        epsilon=settings.epsilon,
                        tie_tolerance=settings.tie_tolerance,
                        selection_policy=settings.selection_policy,
                        ood_policy=settings.ood_policy,
                        safe_count=int(safe.sum()),
                        anchor_exact_zero=True,
                    ),
                    numeric=dict(
                        current_forward_inputs=False,
                        research_context=VERSION,
                        family_recipe=fitted.spec.recipe_id,
                        model_backend=dict(fitted.model.metadata),
                    ),
                )
                if full_ranking:
                    decision = replace(decision, ranked_ids=rank_decision(decision))
        return FamilyArtifact(fitted, decision, digest(task))


def dumps_family_artifact(artifact):
    fitted = artifact.fit
    return canonical(
        dict(
            version=VERSION,
            fit=dict(
                spec=fitted.spec.code,
                family_id=fitted.family_id,
                schema_id=fitted.schema_id,
                snapshot_id=fitted.snapshot_id,
                information_as_of=fitted.information_as_of,
                fit_completed_at=fitted.fit_completed_at,
                K=fitted.K,
                scaler=fitted.scaler,
                training=fitted.training,
                model=fitted.model.to_payload() if fitted.model else None,
            ),
            decision=dumps_decision(artifact.decision),
            decision_id=artifact.decision.decision_id,
            task_digest=artifact.task_digest,
            fit_id=fitted.fit_id,
            artifact_id=artifact.artifact_id,
        )
    )


def _loads_family_artifact(text, *, expected_artifact_id, task, schema):
    if len(text.encode()) > 4_000_000:
        raise MetaRecordError("MLR_FAMILY_ARTIFACT_BUDGET_EXCEEDED")
    from quantbt.optimization.meta_selection.persistence import _unique_object

    payload = json.loads(text, object_pairs_hook=_unique_object)
    if (
        set(payload)
        != {
            "version",
            "fit",
            "decision",
            "decision_id",
            "task_digest",
            "fit_id",
            "artifact_id",
        }
        or payload["version"] != VERSION
    ):
        raise MetaRecordError("MLR_FAMILY_ARTIFACT_VERSION_INVALID")
    context = dict(payload["fit"])
    spec = FamilySpec(context.pop("spec"))
    model = (
        NumericModel.from_payload(context.pop("model"))
        if context["model"]
        else context.pop("model")
    )
    fitted = FamilyFit(spec=spec, model=model, **context)
    decision = loads_decision(
        payload["decision"],
        expected_decision_id=payload["decision_id"],
        available_as_of=task.decision_sealed_at,
    )
    artifact = FamilyArtifact(fitted, decision, payload["task_digest"])
    if (
        payload["artifact_id"] != expected_artifact_id
        or artifact.artifact_id != expected_artifact_id
        or payload["fit_id"] != fitted.fit_id
        or payload["task_digest"] != digest(task)
    ):
        raise MetaRecordError("MLR_FAMILY_ARTIFACT_ID_INVALID")
    engine = FamilyResearch(max_fits=0)
    other = engine.propose(
        task,
        fitted,
        schema=schema,
        mode=decision.mode,
        full_ranking=bool(decision.ranked_ids),
    )
    semantic = (
        "task_id",
        "anchor_evaluation_id",
        "proposed_evaluation_id",
        "actual_evaluation_id",
        "proposed_params",
        "raw_best_evaluation_id",
        "model_id",
        "training_snapshot_id",
        "information_as_of",
        "fit_completed_at",
        "decision_sealed_at",
        "ready_at",
        "clock_mode",
        "mode",
        "status",
        "tie_set",
        "ranked_ids",
        "guard",
    )
    if any(getattr(other.decision, k) != getattr(decision, k) for k in semantic):
        raise MetaRecordError("MLR_FAMILY_RESTORED_FULL_POOL_MISMATCH")
    expected = {p["evaluation_id"]: p for p in decision.predictions}
    actual = {p["evaluation_id"]: p for p in other.decision.predictions}
    if expected.keys() != actual.keys():
        raise MetaRecordError("MLR_FAMILY_RESTORED_FULL_POOL_MISMATCH")
    for eid, original in expected.items():
        for name, value in original.items():
            got = actual[eid][name]
            if (
                name in {"yhat", "qhat", "distance"}
                and value is not None
                and got is not None
            ):
                same = np.isclose(
                    got,
                    value,
                    rtol=engine.runtime.limits.parity_rtol,
                    atol=engine.runtime.limits.parity_atol,
                )
            else:
                same = got == value
            if not same:
                raise MetaRecordError("MLR_FAMILY_RESTORED_FULL_POOL_MISMATCH")
    return artifact


def loads_family_artifact(text, *, expected_artifact_id, task, schema):
    try:
        return _loads_family_artifact(
            text, expected_artifact_id=expected_artifact_id, task=task, schema=schema
        )
    except MetaRecordError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        RecursionError,
    ) as exc:
        raise MetaRecordError("MLR_FAMILY_ARTIFACT_CORRUPT") from exc
