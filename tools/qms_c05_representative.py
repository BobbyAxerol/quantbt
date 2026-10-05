"""Review-only finite-support projection, independent of public selectors."""

from dataclasses import dataclass
import math
from types import MappingProxyType

import numpy as np

from quantbt.optimization.parameter_space import NormalizedSearchSpace
from tools.qms_c05_latent import digest

VERSION = "qms-feasible-support-projection-v1-proposed"
BINDINGS = frozenset(("market", "calendar", "accounting", "objective", "metric",
                      "execution_seed", "is_cutoff", "strategy", "space"))


@dataclass(frozen=True, slots=True)
class EvaluatedPoint:
    evaluation_id: str
    candidate_id: str
    params: dict
    bindings: dict
    raw_is_sharpe: float
    output_ref: str
    feasible: bool = True
    role: str = "IS"
    verification: str = "original_result"

    def __post_init__(self):
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))


def parameter_geometry(space, effective):
    """Scalar logical-block calculation; no fitted scaler or IS metric."""
    values = []
    for spec in space.specs:
        if not spec.variable:
            continue
        active = spec.name in effective
        if spec.choices:
            values.extend(float(active and effective[spec.name] == c) / math.sqrt(2)
                          for c in spec.choices)
        else:
            value = 0.0
            if active:
                low, high, raw = float(spec.low), float(spec.high), float(effective[spec.name])
                if spec.log:
                    low, high, raw = math.log(low), math.log(high), math.log(raw)
                value = (raw - low) / (high - low)
            values.append(value / math.sqrt(2) if spec.active_if else value)
        if spec.active_if:
            values.append(float(active) / math.sqrt(2))
    return np.asarray(values, dtype=np.float64)


def representative(ranges, points, *, strategy_id, bindings):
    """Never creates params or replaces an own IS witness by cluster averages."""
    if set(bindings) != BINDINGS or any(not isinstance(v, str) or not v for v in bindings.values()) or not strategy_id:
        raise ValueError("complete current-IS bindings and strategy identity required")
    space = NormalizedSearchSpace(ranges)
    if bindings["strategy"] != strategy_id or bindings["space"] != space.identity:
        raise ValueError("current strategy/schema bindings mismatch")
    support, evaluation_ids, excluded = {}, set(), []
    for point in points:
        if not point.evaluation_id or point.evaluation_id in evaluation_ids:
            raise ValueError("evaluation IDs must be present and unique")
        evaluation_ids.add(point.evaluation_id)
        if point.role != "IS" or point.verification != "original_result" or dict(point.bindings) != bindings:
            raise ValueError("exact original current-IS witness required")
        effective = space.effective(point.params)
        if dict(point.params) != effective:
            raise ValueError("witness must bind exact canonical effective params")
        candidate = space.candidate_key(effective, strategy_identity=strategy_id)
        if point.candidate_id != candidate:
            raise ValueError("original witness candidate mismatch")
        if type(point.feasible) is not bool or not isinstance(point.raw_is_sharpe, (int, float)) or isinstance(point.raw_is_sharpe, bool):
            raise ValueError("explicit feasibility and raw numeric IS required")
        if not point.output_ref or not isinstance(point.output_ref, str):
            raise ValueError("own original-result output reference required")
        if not point.feasible or not math.isfinite(point.raw_is_sharpe):
            excluded.append(point.evaluation_id)
            continue
        tie_key = digest(dict(strategy=strategy_id, effective=effective))
        # Geometry is unique-candidate weighted; all original evaluation IDs survive.
        if candidate not in support:
            support[candidate] = dict(point=point, tie_key=tie_key,
                                      geometry=parameter_geometry(space, effective), ids=[])
        row = support[candidate]
        row["ids"].append(point.evaluation_id)
        if point.evaluation_id < row["point"].evaluation_id:
            row["point"] = point
    if not support:
        raise ValueError("no admissible original-IS support")
    candidates = sorted(support, key=lambda key: (support[key]["tie_key"], key))
    center = np.mean([support[key]["geometry"] for key in candidates], axis=0)
    center.setflags(write=False)
    distances = {key: math.fsum(float(v) * float(v) for v in support[key]["geometry"] - center)
                 for key in candidates}
    minimum = min(distances.values())
    tied = [key for key in candidates if distances[key] <= minimum + 1e-12]
    selected = min(tied, key=lambda key: (support[key]["tie_key"], key,
                                         support[key]["point"].evaluation_id))
    return dict(schema=VERSION, space_identity=space.identity, candidate_id=selected,
                selected=support[selected]["point"], center=center, distances=distances,
                support_ids=tuple(candidates), tie_ids=tuple(tied), excluded=tuple(excluded),
                evaluation_ids=tuple(sorted(evaluation_ids)),
                auxiliary_is_evaluations=0, activation=False)
