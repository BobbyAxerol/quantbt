"""Research-only forward-contrast Ridge over the existing causal numeric owners."""

from dataclasses import replace

import numpy as np

from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.numerics import (
    reference_fit,
    solution_diagnostics,
)
from .learners import prepare_history


def forward_labels(snapshot):
    """Match prepare_history's exact row order; no current task/outcomes input."""
    deltas, labels, weights = [], [], []
    for revision in sorted(snapshot.revisions, key=lambda r: r.task.task_id):
        task = revision.task
        by_id = {c.evaluation_id: c for c in task.candidates}
        anchor_is = task.anchor.observation.raw_sharpe
        for row in revision.training_rows:
            candidate_is = by_id[row.candidate_evaluation_id].observation.raw_sharpe
            delta = candidate_is - anchor_is
            deltas.append(delta)
            labels.append(delta - row.y)
            weights.append(row.origin_weight)
    values = tuple(np.asarray(x, dtype=float) for x in (deltas, labels, weights))
    if any(not np.isfinite(x).all() for x in values):
        raise ValueError("finite mature forward target required")
    return values


def fit_forward(schema, snapshot, task, runtime):
    """Fit Q directly, retaining V1 history/scaler/weights/regularization/OOD."""
    if (
        snapshot.information_as_of > task.data_cutoff
        or snapshot.family_id != task.family.family_id
    ):
        raise ValueError("forward target history frontier/family mismatch")
    prepared = prepare_history(schema, snapshot, runtime)
    if prepared is None:
        return dict(
            status="META_SUPPORT_INSUFFICIENT", predictions=[], fit=None, charge=0
        )
    delta, q, w = forward_labels(snapshot)
    if not np.array_equal(w, prepared.weights) or not np.allclose(
        delta - q, prepared.y, rtol=1e-12, atol=1e-12
    ):
        raise ValueError("forward/Y label row identity mismatch")
    gram, rhs, beta = runtime.fit(prepared.X, q, w, 10.0)
    reference = reference_fit(prepared.X, q, w, 10.0, runtime.limits)
    if any(
        not np.allclose(a, b, rtol=1e-9, atol=1e-10)
        for a, b in zip((gram, rhs, beta), reference)
    ):
        raise ValueError("forward target Rust/reference parity")
    diag = solution_diagnostics(gram, rhs, beta, runtime.limits)
    model = dict(
        schema="m4.ml07.q-ridge.v1",
        snapshot=snapshot.snapshot_id,
        schema_id=schema.schema_id,
        K=snapshot.origin_count,
        target="raw_forward_contrast_Q",
        lambda_reg=10.0,
        coefficients=beta.tolist(),
        numeric=diag,
    )
    batch = schema.encode(task.candidates)
    batch = replace(
        batch,
        valid=batch.valid
        & np.array(
            [c.observation.verification != "unverified" for c in task.candidates]
        ),
    )
    ai = next(
        i
        for i, c in enumerate(task.candidates)
        if c.evaluation_id == task.anchor_candidate_evaluation_id
    )
    result = dict(fit=model, model_id=digest(model), charge=2, predictions=[])
    if not batch.valid[ai]:
        return dict(result, status="META_NOT_APPLICABLE_METRIC")
    values, unsupported = runtime.transform(batch, prepared.scaler)
    if (unsupported & batch.valid).any():
        return dict(result, status="META_OOD_NATIVE_FALLBACK")
    indices = np.flatnonzero(batch.valid)
    selected = tuple(task.candidates[i] for i in indices)
    x = np.ascontiguousarray(values[indices] - values[ai])
    delta_is = np.asarray(
        [
            c.observation.raw_sharpe - task.anchor.observation.raw_sharpe
            for c in selected
        ]
    )
    # Native rank returns (V beta, deltaIS-V beta): here those roles are Q and implied Y.
    qhat, yhat = runtime.rank(x, beta, delta_is)
    geometry = schema.parameter_geometry(selected)
    local_ai = next(
        i
        for i, c in enumerate(selected)
        if c.evaluation_id == task.anchor_candidate_evaluation_id
    )
    distances = np.linalg.norm(geometry - geometry[local_ai], axis=1)
    if qhat[local_ai] != 0.0 or yhat[local_ai] != 0.0:
        raise ValueError("forward target anchor must be exact zero")
    predictions = [
        dict(
            evaluation_id=c.evaluation_id,
            candidate_id=c.candidate_id,
            raw_is=c.observation.raw_sharpe,
            yhat=float(yhat[i]),
            qhat=float(qhat[i]),
            distance=float(distances[i]),
            eligible=bool(qhat[i] >= -0.1),
            exclusion=None if qhat[i] >= -0.1 else "PREDICTED_Q_FLOOR",
        )
        for i, c in enumerate(selected)
    ]
    return dict(result, status="META_MODEL_PROPOSAL", predictions=predictions)
