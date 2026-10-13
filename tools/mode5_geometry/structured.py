"""Declared independent representations and design-only pick/freeze trajectories."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .design import SaltelliLayout


@dataclass(frozen=True)
class IndependentInputs:
    """A product-measure declaration, not a statistical independence test.

    Marginals describe the actual sampling distributions in axis order. Branch
    results are conditional on branch_id; latent results describe mapping_id,
    not the importance of the original coupled parameters.
    """

    names: tuple[str, ...]
    marginals: tuple[str, ...]
    representation_id: str
    kind: str
    independent_axes: bool
    branch_id: str | None = None
    mapping_id: str | None = None

    def __post_init__(self):
        if type(self.names) is not tuple or type(self.marginals) is not tuple:
            raise ValueError("immutable axis names and marginal declarations required")
        labels = (self.representation_id, *self.names, *self.marginals)
        if (
            not self.names
            or len(self.names) != len(self.marginals)
            or any(type(s) is not str or not s.strip() for s in labels)
            or len(set(self.names)) != len(self.names)
            or self.independent_axes is not True
            or self.kind
            not in {"numeric_product", "fixed_branch", "independent_latent"}
        ):
            raise ValueError(
                "declared independent numeric representation and marginals required"
            )
        if any(
            v is not None and (type(v) is not str or not v.strip())
            for v in (self.branch_id, self.mapping_id)
        ):
            raise ValueError("nonempty branch/mapping identity required")
        if self.kind == "fixed_branch" and self.branch_id is None:
            raise ValueError("fixed-branch representation requires branch_id")
        if self.kind == "independent_latent" and self.mapping_id is None:
            raise ValueError("latent representation requires mapping_id")
        if (
            self.kind == "numeric_product"
            and self.branch_id is not None
            or self.kind != "independent_latent"
            and self.mapping_id is not None
        ):
            raise ValueError("branch/latent identity does not match representation")


def _finite_array(values, shape):
    if np.ma.isMaskedArray(values) and np.any(np.ma.getmaskarray(values)):
        raise ValueError(
            "finite complete rows required; masked rows cannot be admitted"
        )
    raw = np.asarray(values)
    if np.iscomplexobj(raw):
        raise ValueError("real finite complete rows required")
    result = np.asarray(raw, dtype=float)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(
            "finite complete rows required; dropping invalid rows is forbidden"
        )
    return result


def saltelli_inputs(layout, a, b):
    """Interleave supplied A, AB_j, optional BA_j, B; never sample/reject rows.

    The caller must sample A/B from the declared independent product measure.
    This assembly does not make a dependent/ordinary trial panel independent.
    """
    if not isinstance(layout, SaltelliLayout):
        raise ValueError("SaltelliLayout required")
    shape = (layout.base_n, layout.dimensions)
    a, b = _finite_array(a, shape), _finite_array(b, shape)
    stride = layout.rows // layout.base_n
    block = np.empty((layout.base_n, stride, layout.dimensions))
    block[:, 0], block[:, -1] = a, b
    for j in range(layout.dimensions):
        block[:, 1 + j] = a
        block[:, 1 + j, j] = b[:, j]
        if layout.second_order:
            block[:, 1 + layout.dimensions + j] = b
            block[:, 1 + layout.dimensions + j, j] = a[:, j]
    return block.reshape(layout.rows, layout.dimensions)


def saltelli_completion(layout, records):
    """Expose every required output slot, including absent/failed/censored work.

    Records have exact row_id, status and output (explicit null if unavailable).
    This is an output-completion ledger only: even complete outputs still need
    input-layout/representation admission through estimate_saltelli. Use once
    per metric, and retain the original execution records outside this reducer.
    """
    if not isinstance(layout, SaltelliLayout):
        raise ValueError("SaltelliLayout required")
    supplied = {}
    allowed = {
        "COMPLETE",
        "FAILED",
        "INFEASIBLE",
        "CANCELLED",
        "CENSORED",
        "NOT_EVALUATED",
    }
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("explicit Saltelli output records required")
        row, status = record.get("row_id"), record.get("status")
        if (
            type(row) is not int
            or not 0 <= row < layout.rows
            or row in supplied
            or type(status) is not str
            or status not in allowed
            or "output" not in record
        ):
            raise ValueError(
                "unique in-layout row_id, declared status and explicit output required"
            )
        value = record["output"]
        finite = isinstance(value, (float, int, np.number)) and not np.iscomplexobj(
            value
        )
        if finite:
            value = float(value)
            finite = bool(np.isfinite(value))
        supplied[row] = dict(
            row_id=row,
            status=status,
            output=value if finite else None,
            reason="INVALID_OR_MISSING_OUTPUT"
            if status == "COMPLETE" and not finite
            else None,
        )
    rows = [
        supplied.get(
            row,
            dict(
                row_id=row,
                status="NOT_EVALUATED",
                output=None,
                reason="MISSING_REQUIRED_ROW",
            ),
        )
        for row in range(layout.rows)
    ]
    incomplete = [r for r in rows if r["status"] != "COMPLETE" or r["output"] is None]
    return dict(
        method="saltelli_completion_ledger_v1",
        status="COMPLETE_OUTPUT_LEDGER"
        if not incomplete
        else "INCOMPLETE_OR_CENSORED_DESIGN",
        expected_rows=layout.rows,
        observed_rows=len(supplied),
        complete_rows=layout.rows - len(incomplete),
        planned_execution_cells=layout.execution_cells,
        status_counts=dict(sorted(Counter(r["status"] for r in rows).items())),
        rows=rows,
        missing_rows=incomplete,
        sensitivity_indices=None,
        interpretation="output slots only, not design admission or executed-finance counts; no filtering, completion imputation or indices",
    )


@dataclass(frozen=True)
class TrajectoryLayout:
    trajectories: int
    dimensions: int
    seed: int
    levels: int = 4
    stress_multiplier: int = 1
    schema: str = "morris_trajectory_layout_v1"

    def __post_init__(self):
        if (
            any(
                type(v) is not int or v < 1
                for v in (self.trajectories, self.dimensions, self.stress_multiplier)
            )
            or type(self.seed) is not int
            or not 0 <= self.seed < 2**32
            or type(self.levels) is not int
            or self.levels < 4
            or self.levels % 2
            or self.schema != "morris_trajectory_layout_v1"
        ):
            raise ValueError(
                "positive counts, even levels >= 4 and registered seed required"
            )

    @property
    def rows(self):
        return self.trajectories * (self.dimensions + 1)

    @property
    def execution_cells(self):
        return self.rows * self.stress_multiplier

    @property
    def delta(self):
        return self.levels / (2 * (self.levels - 1))


def trajectory_layout(trajectories, dimensions, *, seed, levels=4, stress_multiplier=1):
    return TrajectoryLayout(trajectories, dimensions, seed, levels, stress_multiplier)


def trajectory_inputs(layout):
    """Seeded Morris grid paths in normalized independent coordinates [0, 1].

    One randomly ordered signed move per axis per trajectory, without output
    selection or optimized trajectory subsampling. Map coordinates to declared
    marginal quantiles before evaluation, retaining this original design.
    """
    if not isinstance(layout, TrajectoryLayout):
        raise ValueError("TrajectoryLayout required")
    rng = np.random.default_rng(layout.seed)
    block = np.empty((layout.trajectories, layout.dimensions + 1, layout.dimensions))
    for path in block:
        base = rng.integers(0, layout.levels // 2, size=layout.dimensions)
        signs = rng.choice([-1, 1], size=layout.dimensions)
        grid = base + (signs < 0) * (layout.levels // 2)
        path[0] = grid / (layout.levels - 1)
        for step, axis in enumerate(rng.permutation(layout.dimensions), 1):
            grid[axis] += signs[axis] * (layout.levels // 2)
            path[step] = grid / (layout.levels - 1)
    return block.reshape(layout.rows, layout.dimensions)


def _trajectory_steps(layout, inputs):
    if not isinstance(layout, TrajectoryLayout):
        raise ValueError("TrajectoryLayout required")
    x = _finite_array(inputs, (layout.rows, layout.dimensions))
    grid = x * (layout.levels - 1)
    tolerance = 32 * np.finfo(float).eps * layout.levels
    if (
        np.any(x < 0)
        or np.any(x > 1)
        or not np.allclose(grid, np.rint(grid), rtol=0, atol=tolerance)
    ):
        raise ValueError(
            "trajectory inputs must retain declared normalized grid coordinates"
        )
    block = x.reshape(layout.trajectories, layout.dimensions + 1, layout.dimensions)
    steps = np.diff(block, axis=1)
    changed = steps != 0
    if not np.all(changed.sum(axis=2) == 1):
        raise ValueError("each trajectory step must change exactly one axis")
    axes = changed.argmax(axis=2)
    if not np.all(np.sort(axes, axis=1) == np.arange(layout.dimensions)):
        raise ValueError("each trajectory must cover every axis exactly once")
    signed_steps = np.take_along_axis(steps, axes[:, :, None], axis=2)[:, :, 0]
    if not np.allclose(np.abs(signed_steps), layout.delta, rtol=0, atol=tolerance):
        raise ValueError("trajectory step does not match declared Morris delta")
    return x, axes, signed_steps
