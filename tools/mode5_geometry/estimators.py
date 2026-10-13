"""Validated numeric sensitivity, separate from legacy design admission.

Saltelli (2010) S1, Jansen/Saltelli ST and Saltelli (2002) S2 formulas:
https://salib.readthedocs.io/en/latest/_modules/SALib/analyze/sobol.html
Morris elementary-effect summaries:
https://salib.readthedocs.io/en/latest/_modules/SALib/analyze/morris.html
No finance, fitted surrogate, outcome-dependent row selection or branch pooling.
"""

from dataclasses import asdict

import numpy as np

from .design import SaltelliLayout
from .sensitivity import validate_saltelli_outputs
from .structured import (
    IndependentInputs,
    TrajectoryLayout,
    _finite_array,
    _trajectory_steps,
)


def _representation(representation, dimensions):
    if (
        not isinstance(representation, IndependentInputs)
        or len(representation.names) != dimensions
    ):
        raise ValueError("aligned declared independent representation required")
    return asdict(representation)


def _bootstrap_config(seed, resamples, confidence_level):
    if (
        type(seed) is not int
        or not 0 <= seed < 2**32
        or type(resamples) is not int
        or resamples < 2
        or type(confidence_level) not in {float, int}
        or not 0 < confidence_level < 1
    ):
        raise ValueError(
            "registered bootstrap seed, resamples >= 2 and confidence in (0, 1) required"
        )


def _scaled_outputs(y):
    # Subtract first to preserve small variations on a large offset. Opposite
    # finite extremes may overflow subtraction, so only those use divide first.
    with np.errstate(over="ignore", invalid="ignore"):
        shifted = y - y[0]
    if np.isfinite(shifted).all():
        scale = float(np.max(np.abs(shifted)))
        return (shifted / scale if scale else np.zeros_like(y)), scale
    scale = float(np.max(np.abs(y)))
    return y / scale - y[0] / scale, scale


def _saltelli_point(block, dimensions, second_order):
    constant = bool(np.all(block == block.flat[0]))
    base = np.r_[block[:, 0], block[:, -1]]
    centered = block - float(np.mean(base))
    a, b = centered[:, 0], centered[:, -1]
    variance = float(np.var(np.r_[a, b]))
    status = (
        "UNDEFINED_CONSTANT_OUTPUT"
        if constant
        else ("UNDEFINED_ZERO_BASE_VARIANCE" if variance == 0 else "ESTIMATED")
    )
    if status != "ESTIMATED":
        return status, None, variance
    ab = centered[:, 1 : 1 + dimensions]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        s1 = np.mean(b[:, None] * (ab - a[:, None]), axis=0) / variance
        st = 0.5 * np.mean((a[:, None] - ab) ** 2, axis=0) / variance
        s2 = []
        if second_order:
            ba = centered[:, 1 + dimensions : 1 + 2 * dimensions]
            for j in range(dimensions):
                for k in range(j + 1, dimensions):
                    s2.append(
                        np.mean(ba[:, j] * ab[:, k] - a * b) / variance - s1[j] - s1[k]
                    )
        values = np.r_[s1, st, st - s1, s2]
    if not np.isfinite(values).all():
        raise ValueError("sensitivity estimate is not numerically finite")
    return status, values, variance


def _bootstrap(data, evaluate, *, seed, resamples, confidence_level, unit):
    rng = np.random.default_rng(seed)
    values, invalid = [], 0
    for _ in range(resamples):
        _, estimates, _ = evaluate(data[rng.integers(len(data), size=len(data))])
        if estimates is None:
            invalid += 1
        else:
            values.append(estimates)
    # Degenerate replications are counted, never silently filtered into a CI.
    intervals = None
    if invalid == 0:
        alpha = (1 - confidence_level) / 2
        intervals = np.quantile(np.array(values), [alpha, 1 - alpha], axis=0).T
    return intervals, dict(
        method="percentile_block_bootstrap_v1",
        seed=seed,
        resamples=resamples,
        confidence_level=confidence_level,
        resample_unit=unit,
        valid_resamples=len(values),
        invalid_resamples=invalid,
        status="AVAILABLE" if not invalid else "UNAVAILABLE_DEGENERATE_RESAMPLES",
        interpretation="design-row uncertainty only; not temporal OOS or a randomized-QMC error guarantee",
    )


def _prefix_sizes(count, sizes):
    if sizes is None:
        return sorted({max(2, count // 4), max(2, count // 2), count})
    sizes = tuple(sizes)
    if (
        not sizes
        or any(type(n) is not int or not 2 <= n <= count for n in sizes)
        or list(sizes) != sorted(set(sizes))
        or sizes[-1] != count
    ):
        raise ValueError(
            "convergence prefixes must increase, contain complete blocks and end at full count"
        )
    return sizes


def _convergence(data, evaluate, unpack, sizes):
    records, previous = [], None
    for count in sizes:
        status, values, _ = evaluate(data[:count])
        change = (
            float(np.max(np.abs(values - previous)))
            if values is not None and previous is not None
            else None
        )
        records.append(
            dict(
                prefix_size=count,
                status=status,
                estimates=unpack(values),
                max_abs_change_from_previous=change,
            )
        )
        previous = values
    return dict(
        status="PREFIX_DIAGNOSTICS_ONLY",
        prefixes=records,
        interpretation="ordered complete-design prefixes, not a convergence certificate or branch-averaged ranking",
    )


def _saltelli_unpack(values, names, *, intervals=False):
    if values is None:
        return None
    d = len(names)
    result = {
        key: values[i * d : (i + 1) * d].tolist()
        for i, key in enumerate(("S1", "ST", "ST_minus_S1"))
    }
    pairs = [(names[j], names[k]) for j in range(d) for k in range(j + 1, d)]
    result["S2"] = [
        dict(
            axes=list(pair),
            **{
                "interval" if intervals else "value": value.tolist()
                if intervals
                else float(value)
            },
        )
        for pair, value in zip(pairs, values[3 * d :])
    ]
    return result


def estimate_saltelli(
    layout,
    inputs,
    outputs,
    *,
    method,
    representation,
    bootstrap_seed,
    bootstrap_resamples,
    confidence_level=0.95,
    convergence_sizes=None,
):
    """Estimate dimensionless S1/ST, optionally S2, only after full admission.

    `method` must be saltelli_pick_freeze_v1. A representation declaration is
    required in addition to exact interleaved A/B/cross validation. Bootstrap
    resamples whole base rows with their A/B/all-cross outputs together, using
    a private seeded RNG. Finite-sample indices and CI are never clipped.
    """
    if not isinstance(layout, SaltelliLayout) or layout.base_n < 2:
        raise ValueError("SaltelliLayout with base_n >= 2 required")
    declared = _representation(representation, layout.dimensions)
    _bootstrap_config(bootstrap_seed, bootstrap_resamples, confidence_level)
    sizes = _prefix_sizes(layout.base_n, convergence_sizes)
    x = _finite_array(inputs, (layout.rows, layout.dimensions))
    y = _finite_array(outputs, (layout.rows,))
    normalized, scale = _scaled_outputs(y)
    admission = validate_saltelli_outputs(
        layout, x, normalized, method=method, independent_axes=True
    )
    input_blocks = x.reshape(
        layout.base_n, layout.rows // layout.base_n, layout.dimensions
    )
    if not np.all(np.any(input_blocks[:, 0] != input_blocks[:, -1], axis=0)):
        raise ValueError("insufficient A/B pick-freeze variation on a declared axis")
    block = normalized.reshape(layout.base_n, layout.rows // layout.base_n)

    def evaluate(rows):
        return _saltelli_point(rows, layout.dimensions, layout.second_order)

    def unpack(values):
        return _saltelli_unpack(values, representation.names)

    status, values, variance = evaluate(block)
    intervals, bootstrap = (
        None,
        dict(
            status="NOT_RUN_UNDEFINED_OUTPUT",
            seed=bootstrap_seed,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
            resample_unit="A_B_all_cross_block_row",
            valid_resamples=0,
            invalid_resamples=0,
        ),
    )
    if values is not None:
        intervals, bootstrap = _bootstrap(
            block,
            evaluate,
            seed=bootstrap_seed,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
            unit="A_B_all_cross_block_row",
        )
    return dict(
        method="saltelli_numeric_v1",
        design_method=method,
        status=status,
        design_status=admission["status"],
        representation=declared,
        base_n=layout.base_n,
        input_rows=layout.rows,
        execution_cells=layout.execution_cells,
        index_unit="variance_fraction",
        sensitivity_indices=unpack(values),
        confidence_intervals=_saltelli_unpack(
            intervals, representation.names, intervals=True
        ),
        bootstrap=bootstrap,
        convergence=_convergence(block, evaluate, unpack, sizes),
        numerics=dict(
            output_reference=float(y[0]),
            output_scale=scale,
            scaled_base_variance=variance,
        ),
        parameter_removal_authorized=False,
        interpretation="indices for the declared product measure/branch/latent mapping only; ST-S1 indicates aggregate interaction, not effect sign",
    )


def _screen_point(effects):
    values = np.r_[
        np.mean(effects, axis=0),
        np.mean(np.abs(effects), axis=0),
        np.std(effects, axis=0, ddof=1),
    ]
    if not np.isfinite(values).all():
        raise ValueError("elementary-effect summary is not numerically finite")
    status = "NO_OBSERVED_EFFECT_ON_DESIGN" if np.all(effects == 0) else "SCREENED"
    return status, values, None


def _screen_unpack(values, dimensions):
    return {
        key: values[i * dimensions : (i + 1) * dimensions].tolist()
        for i, key in enumerate(("mu", "mu_star", "sigma"))
    }


def trajectory_screen(
    layout,
    inputs,
    outputs,
    *,
    method,
    representation,
    output_unit,
    bootstrap_seed,
    bootstrap_resamples,
    confidence_level=0.95,
    convergence_sizes=None,
):
    """Signed Morris effects per normalized input span, not global indices.

    Each validated grid trajectory changes every axis once. mu is signed,
    mu_star measures magnitude, sigma indicates variation across contexts
    (nonlinearity OR interaction, not proof of either separately). Bootstrap
    resamples full trajectories jointly across axes. Use separately per metric.
    """
    if (
        not isinstance(layout, TrajectoryLayout)
        or layout.trajectories < 2
        or method != "morris_trajectory_v1"
    ):
        raise ValueError(
            "registered Morris trajectory design with >= 2 trajectories required"
        )
    declared = _representation(representation, layout.dimensions)
    if type(output_unit) is not str or not output_unit.strip():
        raise ValueError("declared output unit required")
    _bootstrap_config(bootstrap_seed, bootstrap_resamples, confidence_level)
    sizes = _prefix_sizes(layout.trajectories, convergence_sizes)
    x, axes, signed_steps = _trajectory_steps(layout, inputs)
    y = _finite_array(outputs, (layout.rows,))
    normalized, scale = _scaled_outputs(y)
    changes = np.diff(
        normalized.reshape(layout.trajectories, layout.dimensions + 1), axis=1
    )
    effects = np.empty_like(changes)
    np.put_along_axis(effects, axes, changes / signed_steps, axis=1)
    status, values, _ = _screen_point(effects)
    intervals, bootstrap = _bootstrap(
        effects,
        _screen_point,
        seed=bootstrap_seed,
        resamples=bootstrap_resamples,
        confidence_level=confidence_level,
        unit="complete_trajectory",
    )
    with np.errstate(over="ignore", invalid="ignore"):
        values, intervals, original_effects = (
            values * scale,
            intervals * scale,
            effects * scale,
        )
    if not all(np.isfinite(v).all() for v in (values, intervals, original_effects)):
        raise ValueError("elementary effects are not representable in output units")

    def unpack(v):
        return _screen_unpack(v, layout.dimensions)

    convergence = _convergence(
        effects, _screen_point, lambda v: unpack(v * scale), sizes
    )
    for record in convergence["prefixes"]:
        if record["max_abs_change_from_previous"] is not None:
            record["max_abs_change_from_previous"] *= scale
    signs = []
    for column in effects.T:
        positive, negative = bool(np.any(column > 0)), bool(np.any(column < 0))
        signs.append(
            "MIXED"
            if positive and negative
            else "POSITIVE"
            if positive
            else "NEGATIVE"
            if negative
            else "ZERO"
        )
    unique = len(np.unique(x, axis=0))
    return dict(
        method=method,
        status=status,
        representation=declared,
        trajectory_count=layout.trajectories,
        input_rows=layout.rows,
        unique_input_rows=unique,
        duplicate_input_rows=layout.rows - unique,
        execution_cells=layout.execution_cells,
        unique_execution_cells=unique * layout.stress_multiplier,
        design_seed=layout.seed,
        levels=layout.levels,
        delta=layout.delta,
        output_unit=output_unit,
        effect_unit=f"{output_unit} per normalized input span",
        effects=unpack(values),
        effect_sign=signs,
        elementary_effects=original_effects.tolist(),
        confidence_intervals=unpack(intervals),
        bootstrap=bootstrap,
        convergence=convergence,
        sensitivity_indices=None,
        parameter_removal_authorized=False,
        interpretation="descriptive trajectory screening; sigma mixes nonlinearity and interaction, not independent-input Sobol or structural inactivity",
    )
