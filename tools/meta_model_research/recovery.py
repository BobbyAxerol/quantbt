"""Cold recovery of completed model-replay groups, never full-WFO recovery."""

from collections import Counter
from copy import deepcopy
import math

import numpy as np

from .linear import _diagnostics


def add_null_evidence(row, revision, panel):
    row = deepcopy(row)
    metrics = row["served_metrics"]
    has_errors = row["scored_rows"] > 0
    members = revision.panel.members if panel == "union" else revision.panel.base_members
    row["metric_null_reasons"] = {
        key: ("INSUFFICIENT_VARIATION_OR_COMPARABLE_PAIRS" if has_errors else row["metric_status"])
        for key, value in metrics.items() if value is None}
    row["label_statuses"] = dict(Counter(o.observation.status.value
        for o in revision.outcomes if o.evaluation_id in members))
    return row


def complete_metric_evidence(row, predictions, revision, panel):
    """Restore omitted null/status telemetry and independently check served loss."""
    row = deepcopy(row)
    members = (revision.panel.members if panel == "union" else revision.panel.base_members)
    by_id = {p["evaluation_id"]: p for p in predictions}
    truth, predicted, q, qh, errors = [], [], [], [], []
    for r in revision.training_rows:
        if r.candidate_evaluation_id not in members:
            continue
        p = by_id.get(r.candidate_evaluation_id)
        if p is None or p["yhat"] is None:
            continue
        error = p["yhat"] - r.y
        if not math.isclose(p["qhat"] - r.q, -error, rel_tol=1e-9, abs_tol=1e-10):
            raise ValueError("recovered Y/Q error units differ")
        truth.append(r.y)
        predicted.append(p["yhat"])
        q.append(r.q)
        qh.append(p["qhat"])
        errors.append(error)
    if len(errors) != row["scored_rows"]:
        raise ValueError("recovered served-row support differs")
    metrics = row["served_metrics"]
    if errors:
        expected = dict(y_mse=float(np.mean(np.square(errors))),
                        y_mae=float(np.mean(np.abs(errors))))
        for name, a, b in (("y", truth, predicted), ("q", q, qh)):
            expected.update({f"{name}_{key}": value
                             for key, value in _diagnostics(np.array(a), np.array(b)).items()})
        for key, value in expected.items():
            if ((metrics[key] is None) != (value is None) or
                    value is not None and not math.isclose(metrics[key], value, rel_tol=1e-9, abs_tol=1e-10)):
                raise ValueError("recovered metric differs from retained served predictions")
    elif row["loss"] is not None:
        raise ValueError("missing predictions cannot produce a loss")
    return add_null_evidence(row, revision, panel)


def recover_group(rows, predictions, corpus, panel, recipe):
    """Only fixed P0/P1 survive; derive corrected fallback from existing P0."""
    indexed = {(r["fold"], r["policy"]): r for r in rows}
    scores = {(r["fold"], r["policy"]): r for r in predictions}
    if len(indexed) != len(rows) or len(scores) != len(predictions):
        raise ValueError("duplicate recovered decision")
    recovered, retained_predictions = [], []
    for fold in range(57):
        for policy in ("P0", "P1"):
            row = indexed[fold, policy]
            if row["group"] != corpus.group or row["panel"] != panel:
                raise ValueError("recovered group/panel mismatch")
            from .replay import view
            snapshot = view(corpus.snapshot(fold), panel)
            task = corpus.revisions[fold].task
            if (row["snapshot_id"] != snapshot.snapshot_id or row["K"] != snapshot.origin_count
                    or row["cutoff"] != task.data_cutoff.isoformat()
                    or row["anchor"] != task.anchor_candidate_evaluation_id
                    or row["winner"] not in {c.evaluation_id for c in task.candidates}):
                raise ValueError("recovered permitted snapshot/current pool differs")
            lam = 10. if policy == "P0" else row["K"] * (10/12)
            if row["K"] >= 12 and row["training"]["lambda_sum"] != lam:
                raise ValueError("recovered regularization units differ")
            score = scores[fold, policy]
            if score["fit_id"] != row["research_fit_id"]:
                raise ValueError("recovered prediction/fit identity differs")
            row = complete_metric_evidence(row, score["predictions"], corpus.revisions[fold], panel)
            row["recovery"] = "HASH_PINNED_COMPLETED_FIXED_POLICY_NO_MODEL_REFIT"
            recovered.append(row)
            retained_predictions.append(score)
        if fold >= 25:
            if recipe["policy"] != "P0":
                raise ValueError("new supported calibration cannot reuse old P2 decisions")
            row = deepcopy(recovered[-2])
            row.update(policy="P2", resolved_policy="P0", recipe_reason=recipe["reason"],
                       recovery="CORRECTED_CALIBRATION_FALLBACK_FROM_RETAINED_P0")
            recovered.append(row)
            retained_predictions.append(dict(scores[fold, "P0"], policy="P2"))
    return recovered, retained_predictions
