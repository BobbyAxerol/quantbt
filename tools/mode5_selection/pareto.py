"""Finite-panel Pareto and fixed-preference compromise, not an evolutionary search."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from tools.mode5_diagnostics.identity import digest


@dataclass(frozen=True)
class ParetoPreference:
    reference_id: str
    environment_ids: tuple[str, ...]
    channel_identity: str
    ideal: tuple[float, ...]
    worst: tuple[float, ...]
    directions: tuple[int, ...]
    weights: tuple[float, ...]
    extrapolation: str
    zero_range: str = "non_discriminative_v1"

    def __post_init__(self):
        for name in ("environment_ids", "ideal", "worst", "directions", "weights"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        n = len(self.environment_ids)
        if (not self.reference_id or not self.channel_identity or not n
                or len(set(self.environment_ids)) != n
                or any(len(getattr(self, name)) != n for name in ("ideal", "worst", "directions", "weights"))
                or any(type(d) is not int or d not in {-1, 1} for d in self.directions)
                or any(not math.isfinite(v) for v in (*self.ideal, *self.worst, *self.weights))
                or any(w <= 0 for w in self.weights)
                or any((a-b)*d < 0 for a, b, d in zip(self.ideal, self.worst, self.directions, strict=True))):
            raise ValueError("finite matched direction-aware reference/positive preferences required")
        if self.extrapolation not in {"allow_and_report_v1", "reject_v1"} or self.zero_range != "non_discriminative_v1":
            raise ValueError("explicit extrapolation/zero-range policy required")

    @property
    def identity(self):
        return digest({"schema": "mode5.pareto_preferences.v1", **asdict(self)})


def nondominated(values, directions):
    values = np.asarray(values, dtype=float)
    directions = np.asarray(directions)
    if (values.ndim != 2 or not len(values) or directions.shape != (values.shape[1],)
            or not np.isfinite(values).all() or not np.isin(directions, (-1, 1)).all()):
        raise ValueError("complete finite matrix and explicit directions required")
    oriented = values * directions
    front = np.ones(len(values), dtype=bool)
    # Bound pairwise temporary storage instead of allocating an N*N*E tensor.
    for start in range(0, len(values), 32):
        block = oriented[start:start+32]
        dominates = (oriented[:, None, :] >= block[None, :, :]).all(axis=2)
        dominates &= (oriented[:, None, :] > block[None, :, :]).any(axis=2)
        front[start:start+len(block)] = ~dominates.any(axis=0)
    return tuple(int(i) for i in np.flatnonzero(front))


def reduce_pareto(panel, plan, preference):
    plan.require(panel)
    if (preference.identity != plan.pareto_preference_identity
            or preference.environment_ids != panel.reference.environment_ids or preference.channel_identity != panel.channel.identity):
        raise ValueError("Pareto environment/channel reference mismatch")
    rows = []
    ideal, worst = np.asarray(preference.ideal), np.asarray(preference.worst)
    directions = np.asarray(preference.directions)
    widths = np.abs(ideal-worst)
    if not np.isfinite(widths).all():
        raise ValueError("Pareto reference width overflow")
    varying = widths != 0
    for c in panel.candidates:
        reasons = [name for name, flag in (("INFEASIBLE", c.feasible), ("RISK_FAIL", c.risk_pass),
            ("QUALITY_FAIL", c.quality_pass), ("INSUFFICIENT_SUPPORT", c.support_pass),
            ("UNEVALUATED_REPRESENTATIVE", c.evaluated)) if not flag]
        complete = all(m.status == "VALID" for m in c.metrics)
        if not complete:
            reasons.append("INCOMPLETE_ENVIRONMENTS")
        row = dict(candidate_id=c.candidate_id, params_digest=c.params_digest, gate_ref=c.gate_ref,
            representative_kind=c.representative_kind, reasons=reasons, score=None, components=None, values=None)
        if complete:
            values = np.asarray([m.value for m in c.metrics])
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                normalized = np.zeros(len(values))
                normalized[varying] = (directions*(ideal-values))[varying]/widths[varying]
            extra = ((values-ideal)*directions > 0) | ((values-worst)*directions < 0)
            if extra.any() and preference.extrapolation == "reject_v1":
                reasons.append("REFERENCE_EXTRAPOLATION")
            weighted = np.asarray(preference.weights)*normalized
            value = float(weighted.max()+plan.formula.params["rho"]*weighted.sum())+c.activity_penalty
            if not np.isfinite(normalized).all() or not math.isfinite(value):
                reasons.append("ARITHMETIC_INVALID")
            else:
                row.update(score=-value, values=tuple(float(v) for v in values), components=dict(
                    normalized_gaps=tuple(float(v) for v in normalized), chebyshev=value,
                    extrapolated=tuple(bool(v) for v in extra), non_discriminative=tuple(bool(v) for v in ~varying),
                    preference_identity=preference.identity, activity_penalty=c.activity_penalty))
        row["eligible"] = not reasons
        rows.append(row)
    valid = [r for r in rows if r["eligible"]]
    if valid:
        # An explicitly non-discriminative zero-width dimension also cannot dominate.
        front_indices = nondominated([[x for x, keep in zip(r["values"], varying, strict=True) if keep] or [0.]
                                      for r in valid], tuple(directions[varying]) or (1,))
        front_ids = {valid[i]["candidate_id"] for i in front_indices}
    else:
        front_ids = set()
    for row in rows:
        row["pareto_front"] = row["candidate_id"] in front_ids
    return tuple(rows), tuple(sorted(front_ids))
