"""Research policy identities around the unchanged origin-sum Ridge owners.

P2 denotes one registered grid arm, not a calibration selector. The caller owns
group exclusion, inner chronology, calibration support and fallback to P0.
Nothing here opens a corpus, calls a financial evaluator or activates a policy.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass
import json
import math
from typing import Literal

import numpy as np

from quantbt.optimization.meta_selection.artifacts import (
    dumps_decision, dumps_model, loads_decision, loads_model,
)
from quantbt.optimization.meta_selection.common import (
    MetaRecordError, canonical, digest, freeze, strict_fields, token, utc, wire,
)
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import HistorySnapshot, SealedTaskRevision
from quantbt.optimization.meta_selection.model import FitOutcome, RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from quantbt.optimization.meta_selection.persistence import _unique_object
from quantbt.optimization.meta_selection.records import MetaTask
from quantbt.optimization.meta_selection.selection import MetaSelectionDecision, MetaSelector


ALPHA_GRID = (0.1, 0.3, 10 / 12, 1.0, 3.0, 10.0)
FREEZE_ID = "43b8c86475ef0922fbaf2ccec6fccb6f10d59e2d6ffc913b66b912d93ea070ea"
POLICY_VERSION = "m4-ml-linear-policy-v1"
BUNDLE_VERSION = "m4-ml-linear-artifact-v1"


@dataclass(frozen=True, slots=True)
class Policy:
    name: Literal["P0", "P1", "P2"] = "P0"
    alpha: float | None = None
    version: str = POLICY_VERSION

    def __post_init__(self):
        if self.version != POLICY_VERSION or self.name not in {"P0", "P1", "P2"}:
            raise MetaRecordError("MLR_POLICY_VERSION_INVALID")
        if self.name == "P1" and self.alpha is None:
            object.__setattr__(self, "alpha", 10 / 12)
        if self.name == "P0":
            valid = self.alpha is None
        else:
            valid = (type(self.alpha) in {float, int} and math.isfinite(self.alpha)
                     and (self.alpha == 10 / 12 if self.name == "P1"
                          else self.alpha in ALPHA_GRID))
        if not valid:
            raise MetaRecordError("MLR_POLICY_ALPHA_INVALID")
        if self.alpha is not None:
            object.__setattr__(self, "alpha", float(self.alpha))

    @property
    def policy_id(self):
        return digest(dict(schema=POLICY_VERSION, freeze_id=FREEZE_ID, policy=self))

    def lambda_for(self, origin_count: int) -> float | None:
        if type(origin_count) is not int or origin_count < 0:
            raise MetaRecordError("MLR_ORIGIN_COUNT_INVALID")
        if not origin_count:
            return None
        return 10.0 if self.name == "P0" else origin_count * self.alpha

    def settings(self, origin_count: int) -> RidgeSettings:
        # K=0 cannot fit: this positive sentinel is used only by V1's no-fit path.
        return RidgeSettings(lambda_reg=self.lambda_for(origin_count) or 10.0)


@dataclass(frozen=True, slots=True)
class ResearchFit:
    policy: Policy
    family_id: str
    schema_id: str
    snapshot_id: str
    information_as_of: object
    origin_count: int
    outcome: FitOutcome

    def __post_init__(self):
        object.__setattr__(self, "information_as_of", utc(self.information_as_of))
        if not isinstance(self.policy, Policy) or not isinstance(self.outcome, FitOutcome):
            raise MetaRecordError("MLR_FIT_TYPE_INVALID")
        for value in (self.family_id, self.schema_id, self.snapshot_id):
            token(value)
        settings = self.policy.settings(self.origin_count)
        model = self.outcome.model
        if (self.outcome.origin_count != self.origin_count
                or (model is None) != (self.origin_count < 12)
                or (model is not None and (
                    model.settings != settings or model.family_id != self.family_id
                    or model.schema["schema_id"] != self.schema_id
                    or model.training_snapshot_id != self.snapshot_id
                    or model.information_as_of != self.information_as_of))):
            raise MetaRecordError("MLR_FIT_CONTEXT_INVALID")

    @property
    def fit_id(self):
        return digest(dict(schema="m4-ml-linear-fit-v1", freeze_id=FREEZE_ID,
                           policy=self.policy, family=self.family_id, schema_id=self.schema_id,
                           snapshot=self.snapshot_id, as_of=self.information_as_of,
                           K=self.origin_count, lambda_reg=self.policy.lambda_for(self.origin_count),
                           reason=self.outcome.reason,
                           model_id=self.outcome.model.model_id if self.outcome.model else None))


@dataclass(frozen=True, slots=True)
class ResearchArtifact:
    fit: ResearchFit
    decision: MetaSelectionDecision
    task_digest: str

    def __post_init__(self):
        token(self.task_digest)
        model = self.fit.outcome.model
        if (self.decision.mode not in {"proposal", "shadow"}
                or self.fit.information_as_of > self.decision.information_as_of
                or self.decision.model_id != (model.model_id if model else None)
                or self.decision.training_snapshot_id != (self.fit.snapshot_id if model else None)):
            raise MetaRecordError("MLR_DECISION_CONTEXT_INVALID")

    @property
    def artifact_id(self):
        return digest(dict(schema=BUNDLE_VERSION, payload=_payload(self)))


class LinearResearch:
    """Run-local, bounded immutable fit reuse; no cross-basis sufficient statistics.

    The attempt counter charges before entering RidgeLearner. A separate solve
    bill counts successful numeric/reference/probe fits and conservatively charges
    failed attempts; both bills have the same hard ceiling. Qualification of an
    injected runtime predates this owner and is reported separately, not hidden.
    The cache byte bound measures serialized retained values, not process RSS.
    """

    def __init__(self, *, runtime=None, max_fits=4000, max_cache_entries=8,
                 max_cache_bytes=8_000_000):
        if (type(max_fits) is not int or not 0 <= max_fits <= 4000
                or type(max_cache_entries) is not int or not 0 <= max_cache_entries <= 64
                or type(max_cache_bytes) is not int or not 0 <= max_cache_bytes <= 8_000_000):
            raise MetaRecordError("MLR_BUDGET_INVALID")
        self.runtime = runtime or NumericRuntime(native_policy="reference")
        if not isinstance(self.runtime, NumericRuntime):
            raise MetaRecordError("MLR_RUNTIME_INVALID")
        self.max_fits, self.max_cache_entries = max_fits, max_cache_entries
        self.max_cache_bytes = max_cache_bytes
        self.fit_count = self.cache_hits = 0
        self.regression_fit_count = self.failed_regression_fit_charge = 0
        self._cache = OrderedDict()

    @property
    def cache_bytes(self):
        return sum(size for _, size in self._cache.values())

    @property
    def metadata(self):
        return dict(fit_count=self.fit_count, max_fits=self.max_fits, cache_hits=self.cache_hits,
                    regression_fit_count=self.regression_fit_count,
                    failed_regression_fit_charge=self.failed_regression_fit_charge,
                    regression_fit_charge=self.regression_fit_count + self.failed_regression_fit_charge,
                    external_runtime_qualification_fits=2 if self.runtime.native is not None else 0,
                    cache_entries=len(self._cache), cache_bytes=self.cache_bytes,
                    max_cache_entries=self.max_cache_entries, max_cache_bytes=self.max_cache_bytes)

    def clear_cache(self):
        self._cache.clear()
        self.runtime.work_cache.clear()

    def fit(self, policy: Policy, schema: DescriptorSchema, snapshot: HistorySnapshot, *,
            fit_completed_at=None, clock_mode="historical_replay") -> ResearchFit:
        if not (isinstance(policy, Policy) and isinstance(schema, DescriptorSchema)
                and isinstance(snapshot, HistorySnapshot)):
            raise MetaRecordError("MLR_FIT_INPUT_INVALID")
        completed = utc(fit_completed_at) if fit_completed_at is not None else None
        if (clock_mode not in {"historical_replay", "observed_live"}
                or (completed is not None and completed < snapshot.information_as_of)):
            raise MetaRecordError("MLR_FIT_CLOCK_INVALID")
        if snapshot.origin_count >= 12 and completed is None:
            raise MetaRecordError("MLR_FIT_COMPLETION_REQUIRED")
        settings = policy.settings(snapshot.origin_count)
        key = digest(dict(freeze_id=FREEZE_ID, policy=policy, schema_id=schema.schema_id,
                          snapshot=snapshot.snapshot_id, settings=settings, completed=completed,
                          clock_mode=clock_mode, limits=self.runtime.limits,
                          backend=self.runtime.policy, native=self.runtime.native_identity))
        if key in self._cache:
            self.cache_hits += 1
            self._cache.move_to_end(key)
            return self._cache[key][0]
        supported = snapshot.origin_count >= 12
        before_hits, before_probes = self.runtime.work_cache.hits, self.runtime.dispatch_calls
        charge = 1 + int(self.runtime.native is not None)
        if self.runtime.native is not None and self.runtime.policy == "auto":
            n, d = len(snapshot.training_rows), len(schema.feature_names)
            bucket = (int(np.log2(n)), int(np.log2(d))) if n and d else None
            if (((n >= 4096 and d >= 8) or (n >= 512 and d >= 24))
                    and bucket not in self.runtime.dispatch and len(self.runtime.dispatch) < 8):
                charge += 6
        if supported:
            if (self.fit_count >= self.max_fits or self.regression_fit_count
                    + self.failed_regression_fit_charge + charge > self.max_fits):
                raise MetaRecordError("MLR_FIT_BUDGET_EXHAUSTED")
            self.fit_count += 1
        try:
            outcome = RidgeLearner(settings=settings, runtime=self.runtime).fit(
                schema, snapshot, fit_completed_at=completed, clock_mode=clock_mode)
        except Exception:
            if supported:
                self.failed_regression_fit_charge += charge
            raise
        if supported:
            self.regression_fit_count += (int(self.runtime.work_cache.hits == before_hits)
                                         + int(self.runtime.native is not None)
                                         + 2 * (self.runtime.dispatch_calls - before_probes))
        result = ResearchFit(policy, snapshot.family_id, schema.schema_id, snapshot.snapshot_id,
                             snapshot.information_as_of, snapshot.origin_count, outcome)
        size = len(canonical(result).encode()) + len(key)
        if self.max_cache_entries and size <= self.max_cache_bytes:
            while self._cache and (len(self._cache) >= self.max_cache_entries
                                   or self.cache_bytes + size > self.max_cache_bytes):
                self._cache.popitem(last=False)
            self._cache[key] = (result, size)
        return result

    def propose(self, task: MetaTask, fitted: ResearchFit, *, schema: DescriptorSchema,
                full_ranking=False, mode="proposal", ready_at=None) -> ResearchArtifact:
        if (not isinstance(task, MetaTask) or not isinstance(fitted, ResearchFit)
                or schema.schema_id != fitted.schema_id
                or task.family.family_id != fitted.family_id
                or fitted.information_as_of > task.data_cutoff):
            raise MetaRecordError("MLR_PROPOSAL_CONTEXT_INVALID")
        decision = MetaSelector(runtime=self.runtime).propose(
            task, fitted.outcome, schema=schema, mode=mode, full_ranking=full_ranking,
            ready_at=ready_at)
        return ResearchArtifact(fitted, decision, digest(task))


def _payload(artifact):
    fitted, model = artifact.fit, artifact.fit.outcome.model
    return dict(freeze_id=FREEZE_ID, policy=wire(fitted.policy), family_id=fitted.family_id,
                schema_id=fitted.schema_id, snapshot_id=fitted.snapshot_id,
                information_as_of=wire(fitted.information_as_of), origin_count=fitted.origin_count,
                fit_reason=fitted.outcome.reason, model_id=model.model_id if model else None,
                model_bundle=dumps_model(model) if model else None,
                decision_id=artifact.decision.decision_id,
                decision_bundle=dumps_decision(artifact.decision), task_digest=artifact.task_digest)


def dumps_artifact(artifact: ResearchArtifact) -> str:
    return canonical(dict(schema=BUNDLE_VERSION, payload=_payload(artifact),
                          artifact_id=artifact.artifact_id))


def loads_artifact(text: str, *, expected_artifact_id: str, available_as_of,
                   task: MetaTask, schema: DescriptorSchema, max_bytes=16_000_000) -> ResearchArtifact:
    """Require trusted identity/readiness and supplied task; never restore a corpus.

    Existing model/decision loaders own closed-field and numeric validation. A
    fresh reference prediction verifies the entire supplied pool, without fitting
    coefficients or consulting forward labels.
    """
    try:
        if (not isinstance(text, str) or type(max_bytes) is not int
                or not 0 < max_bytes <= 16_000_000 or len(text.encode()) > max_bytes):
            raise MetaRecordError("MLR_ARTIFACT_SIZE_INVALID")
        document = json.loads(text, object_pairs_hook=_unique_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(
                                  MetaRecordError("MLR_ARTIFACT_NONFINITE")))
        if (set(document) != {"schema", "payload", "artifact_id"}
                or document["schema"] != BUNDLE_VERSION
                or not expected_artifact_id or document["artifact_id"] != expected_artifact_id
                or digest(dict(schema=BUNDLE_VERSION, payload=document["payload"])) != expected_artifact_id):
            raise MetaRecordError("MLR_ARTIFACT_ID_INVALID")
        p = document["payload"]
        if (set(p) != {"freeze_id", "policy", "family_id", "schema_id", "snapshot_id",
                       "information_as_of", "origin_count", "fit_reason", "model_id",
                       "model_bundle", "decision_id", "decision_bundle", "task_digest"}
                or p["freeze_id"] != FREEZE_ID or p["task_digest"] != digest(task)):
            raise MetaRecordError("MLR_ARTIFACT_CONTEXT_INVALID")
        policy = Policy(**strict_fields(Policy, p["policy"]))
        if (p["model_bundle"] is None) != (p["model_id"] is None):
            raise MetaRecordError("MLR_ARTIFACT_MODEL_INVALID")
        model = (loads_model(p["model_bundle"], expected_model_id=p["model_id"],
                             available_as_of=available_as_of) if p["model_bundle"] is not None else None)
        decision = loads_decision(p["decision_bundle"], expected_decision_id=p["decision_id"],
                                  available_as_of=available_as_of)
        fitted = ResearchFit(policy, p["family_id"], p["schema_id"], p["snapshot_id"],
                             p["information_as_of"], p["origin_count"],
                             FitOutcome(model, p["fit_reason"], p["origin_count"]))
        restored = ResearchArtifact(fitted, decision, p["task_digest"])
        reference = LinearResearch(max_fits=0).propose(
            task, fitted, schema=schema, mode=decision.mode,
            full_ranking=decision.numeric.get("full_ranking_materialized", False),
            ready_at=decision.ready_at).decision
        exact = ("task_id", "anchor_evaluation_id", "proposed_evaluation_id", "actual_evaluation_id",
                 "proposed_params", "raw_best_evaluation_id", "information_as_of", "fit_completed_at",
                 "decision_sealed_at", "ready_at", "clock_mode", "status", "tie_set", "ranked_ids", "guard")
        if any(getattr(decision, k) != getattr(reference, k) for k in exact):
            raise MetaRecordError("MLR_RESTORED_DECISION_MISMATCH")
        actual = {p["evaluation_id"]: p for p in decision.predictions}
        expected = {p["evaluation_id"]: p for p in reference.predictions}
        if actual.keys() != expected.keys():
            raise MetaRecordError("MLR_RESTORED_POOL_MISMATCH")
        for eid, prediction in actual.items():
            if prediction.keys() != expected[eid].keys():
                raise MetaRecordError("MLR_RESTORED_PREDICTION_MISMATCH")
            for key, value in prediction.items():
                target = expected[eid][key]
                if key in {"yhat", "qhat"} and value is not None and target is not None:
                    if not math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-10):
                        raise MetaRecordError("MLR_RESTORED_PREDICTION_MISMATCH")
                elif value != target:
                    raise MetaRecordError("MLR_RESTORED_PREDICTION_MISMATCH")
        return restored
    except MetaRecordError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        raise MetaRecordError("MLR_ARTIFACT_CORRUPT") from exc


@dataclass(frozen=True, slots=True)
class PanelMetrics:
    artifact_id: str
    task_id: str
    origin: object
    revision_id: str
    available_as_of: object
    panel: str
    panel_members: tuple[str, ...]
    known_rows: int
    scored_rows: int
    status: str
    metrics: dict
    null_reasons: dict
    errors: tuple
    label_statuses: dict
    estimand: str = "conditional_known_labeled_nonanchor_panel_not_full_pool_oracle_v1"

    def __post_init__(self):
        for name in ("origin", "available_as_of"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        for name in ("metrics", "null_reasons", "errors", "label_statuses"):
            object.__setattr__(self, name, freeze(getattr(self, name)))


def _midranks(values):
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    return (np.cumsum(counts) - (counts - 1) / 2)[inverse]


def _diagnostics(truth, predicted):
    centered, x = truth - truth.mean(), predicted - predicted.mean()
    slope = float(np.dot(x, centered) / np.dot(x, x)) if len(x) > 1 and np.dot(x, x) > 0 else None
    a, b = _midranks(truth), _midranks(predicted)
    a, b = a - a.mean(), b - b.mean()
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    rank = float(np.dot(a, b) / denominator) if denominator else None
    correct, pairs = 0.0, 0
    for i in range(len(truth)):
        for j in range(i):
            if truth[i] != truth[j]:
                pairs += 1
                correct += (0.5 if predicted[i] == predicted[j] else
                            float((truth[i] > truth[j]) == (predicted[i] > predicted[j])))
    return dict(calibration_slope=slope,
                calibration_intercept=float(truth.mean() - slope * predicted.mean()) if slope is not None else None,
                spearman=rank, pair_accuracy=correct / pairs if pairs else None)


def evaluate_revision(artifact: ResearchArtifact, revision: SealedTaskRevision, *,
                      available_as_of, snapshot_order=None,
                      panel: Literal["union", "base"] = "union") -> PanelMetrics:
    """Score saved *served* predictions on a declared origin's known label panel.

    Availability is checked separately from the original decision cutoff. The
    exact Y/Q error identity uses one algebraic residual after checking both
    served units; this avoids presenting floating subtraction noise as two tests.
    """
    task, decision = revision.task, artifact.decision
    if (panel not in {"union", "base"} or digest(task) != artifact.task_digest
            or task.task_id != decision.task_id):
        raise MetaRecordError("MLR_EVALUATION_CONTEXT_INVALID")
    cutoff = utc(available_as_of)
    HistorySnapshot(task.family.family_id, (task.corpus_id,), (task.outcome_origin,),
                    (task.research_exposure,), cutoff, (revision,), snapshot_order)
    members = revision.panel.members if panel == "union" else revision.panel.base_members
    rows = [r for r in revision.training_rows if r.candidate_evaluation_id in members]
    predictions = {p["evaluation_id"]: p for p in decision.predictions}
    errors, y, yh, q, qh = [], [], [], [], []
    for row in rows:
        p = predictions.get(row.candidate_evaluation_id)
        if p is None or p["yhat"] is None:
            continue
        error = p["yhat"] - row.y
        if (not math.isclose(p["qhat"], row.raw_is - row.anchor_is - p["yhat"],
                             rel_tol=1e-9, abs_tol=1e-10)
                or not math.isclose(p["qhat"] - row.q, -error, rel_tol=1e-9, abs_tol=1e-10)):
            raise MetaRecordError("MLR_SERVED_Y_Q_UNITS_INVALID")
        y.append(row.y)
        yh.append(p["yhat"])
        q.append(row.q)
        qh.append(p["qhat"])
        errors.append(dict(evaluation_id=row.candidate_evaluation_id, y_error=error, q_error=-error))
    metrics, nulls = {}, {}
    if errors:
        residual = np.array([r["y_error"] for r in errors])
        mae, mse, bias = (float(v) for v in (np.mean(np.abs(residual)),
                                            np.mean(residual ** 2), np.mean(residual)))
        metrics.update(y_mae=mae, q_mae=mae, y_mse=mse, q_mse=mse,
                       y_rmse=math.sqrt(mse), q_rmse=math.sqrt(mse), y_bias=bias, q_bias=-bias)
        for name, truth, predicted in (("y", y, yh), ("q", q, qh)):
            for key, value in _diagnostics(np.array(truth), np.array(predicted)).items():
                metrics[f"{name}_{key}"] = value
                if value is None:
                    nulls[f"{name}_{key}"] = "INSUFFICIENT_VARIATION_OR_COMPARABLE_PAIRS"
        if any(v is not None and not math.isfinite(v) for v in metrics.values()):
            raise MetaRecordError("MLR_METRIC_NONFINITE")
        status = "SCORED" if len(errors) == len(rows) else "PARTIAL_SERVED_PANEL"
    else:
        status = "NO_SERVED_PREDICTIONS" if rows else "NO_VALID_LABELED_PANEL_ROWS"
        for key in ("y_mae", "q_mae", "y_mse", "q_mse", "y_rmse", "q_rmse", "y_bias", "q_bias",
                    "y_calibration_slope", "y_calibration_intercept", "y_spearman", "y_pair_accuracy",
                    "q_calibration_slope", "q_calibration_intercept", "q_spearman", "q_pair_accuracy"):
            metrics[key], nulls[key] = None, status
    statuses = Counter(o.observation.status.value for o in revision.outcomes if o.evaluation_id in members)
    return PanelMetrics(artifact.artifact_id, task.task_id, task.origin, revision.revision_id,
                        cutoff, panel, tuple(members), len(rows), len(errors), status,
                        metrics, nulls, tuple(errors), dict(statuses))
