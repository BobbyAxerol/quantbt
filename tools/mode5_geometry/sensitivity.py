"""Explicit paired screening and structured-design admission, not TPE Sobol."""

import numpy as np

from .design import SaltelliLayout


def validate_saltelli_outputs(layout, inputs, outputs, *, method, independent_axes):
    if not isinstance(layout, SaltelliLayout) or method != "saltelli_pick_freeze_v1" or independent_axes is not True:
        raise ValueError("structured independent-input Saltelli design required")
    x, y = np.asarray(inputs, dtype=float), np.asarray(outputs, dtype=float)
    if x.shape != (layout.rows, layout.dimensions) or y.shape != (layout.rows,):
        raise ValueError("incomplete structured rows; dropping invalid rows is forbidden")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("invalid structured data; retain failed design, no filtering")
    stride = 2*layout.dimensions+2 if layout.second_order else layout.dimensions+2
    block = x.reshape(layout.base_n, stride, layout.dimensions)
    for j in range(layout.dimensions):
        cross = block[:, 0].copy()
        cross[:, j] = block[:, -1, j]
        if not np.array_equal(block[:, 1+j], cross):
            raise ValueError("A/B cross matrices do not match design")
        if layout.second_order:
            reverse = block[:, -1].copy()
            reverse[:, j] = block[:, 0, j]
            if not np.array_equal(block[:, 1+layout.dimensions+j], reverse):
                raise ValueError("reverse cross matrix mismatch")
    variance = float(np.var(np.r_[y[::stride], y[stride-1::stride]]))
    return dict(status="UNDEFINED_CONSTANT_OUTPUT" if variance == 0 else "STRUCTURED_DESIGN_VALID",
        base_n=layout.base_n, input_rows=layout.rows, execution_cells=layout.execution_cells,
        output_variance=variance, sensitivity_indices=None,
        interpretation="design admission only; a separately registered SALib analysis is required for global indices/CI")


def paired_screen(center_metrics, probe_metrics, *, units):
    """No inferential CI from one market path; retain each invalid/adverse cell."""
    if set(center_metrics) != set(units) or not units or any(not unit for unit in units.values()):
        raise ValueError("explicit aligned metric units required")
    rows, results = [], {}
    for record in probe_metrics:
        if set(record["metrics"]) != set(center_metrics):
            raise ValueError("incomplete metric columns must use explicit nulls")
        if record["status"] not in {"COMPLETE", "FAILED", "INFEASIBLE", "CANCELLED"}:
            raise ValueError("unknown evaluation status")
        deltas = {}
        for metric, center in center_metrics.items():
            value = record["metrics"][metric]
            if center is not None and not np.isfinite(center) or value is not None and not np.isfinite(value):
                raise ValueError("nonfinite metric; represent unavailable as null")
            deltas[metric] = value-center if record["status"] == "COMPLETE" and value is not None and center is not None else None
        rows.append(dict(record, deltas=deltas))
    for metric, unit in units.items():
        values = [r["deltas"][metric] for r in rows if r["deltas"][metric] is not None]
        results[metric] = dict(unit=unit, paired_count=len(values),
            minimum_delta=min(values) if values else None, maximum_delta=max(values) if values else None,
            status="UNAVAILABLE" if not values else ("NO_OBSERVED_CHANGE" if all(v == 0 for v in values) else "OBSERVED_CHANGE"),
            confidence_interval=None)
    return dict(method="paired_local_multi_metric_v1", rows=rows, results=results,
        parameter_removal_authorized=False, sensitivity_indices=None,
        inference="descriptive matched-path effects; not independent-input Sobol, global inactivity or temporal OOS")
