"""Exact discrete mass tails and immutable finite-panel reference components."""

from dataclasses import dataclass
from functools import cached_property
import math

import numpy as np

from quantbt.mode5.diagnostics.identity import digest as canonical_digest
from .contracts import MetricValue, vector


def _distribution(values, weights):
    values = vector(values)
    weights = np.ones(len(values)) if weights is None else vector(weights)
    if (not len(values) or weights.shape != values.shape or not np.isfinite(values).all()
            or not np.isfinite(weights).all() or np.any(weights < 0) or not np.any(weights > 0)):
        raise ValueError("nonempty finite distribution with positive total weight required")
    keep = weights > 0
    weights = weights[keep] / weights.max()
    weights /= weights.sum()
    return values[keep], weights


def lower_tail(values, alpha, *, weights=None, unit="utility"):
    array = vector(values)
    n = len(array)
    def result(value=None, status="VALID", reason=None, components=()):
        return MetricValue("mode5.lower_environment_mass_v1", unit, n, value, status, reason, components)
    if not math.isfinite(alpha) or not 0 < alpha <= 1:
        return result(status="INVALID", reason="tail mass alpha must be in (0,1]")
    try:
        array, weights = _distribution(array, weights)
    except ValueError as exc:
        return result(status="INVALID", reason=str(exc))
    remaining = alpha
    contributions, used_weights = [], []
    for j in np.argsort(array, kind="stable"):
        used = min(float(weights[j]), remaining)
        if used > 0:
            # Scale probability first: averaging finite extremes stays finite.
            contributions.append((used / alpha) * float(array[j]))
            used_weights.append(used)
        remaining = max(0., remaining - used)
        if remaining == 0:
            break
    try:
        value = math.fsum(contributions)
    except OverflowError:
        return result(status="INVALID", reason="tail numeric overflow")
    if not math.isfinite(value):
        return result(status="INVALID", reason="tail numeric overflow")
    components = (("alpha_mass", alpha), ("consumed_mass", math.fsum(used_weights)),
        ("positive_weight_observations", len(array)), ("tail_atoms", len(used_weights)),
        ("largest_tail_mass_fraction", max(used_weights) / alpha),
        ("definition", "lower_environment_utility_probability_mass"))
    return result(value, components=components)


def expected_shortfall(losses, confidence, *, weights=None, unit="decimal_return"):
    if not math.isfinite(confidence) or not 0 <= confidence < 1:
        return MetricValue("mode5.upper_loss_mass_es_v1", unit, len(vector(losses)),
            status="INVALID", reason="loss confidence must be in [0,1)")
    tail = lower_tail(-vector(losses), 1-confidence, weights=weights, unit=unit)
    components = tuple((k, v) for k, v in tail.components if k != "definition")
    return MetricValue("mode5.upper_loss_mass_es_v1", unit, tail.sample_count,
        -tail.value if tail.value is not None else None, tail.status, tail.reason,
        components + (("confidence", confidence), ("definition", "upper_daily_loss_probability_mass")))


def weighted_median(values, *, weights=None, unit="utility"):
    array = vector(values)
    try:
        observed, probabilities = _distribution(array, weights)
    except ValueError as exc:
        return MetricValue("mode5.weighted_median_lower_tie_v1", unit, len(array), status="INVALID", reason=str(exc))
    order = np.argsort(observed, kind="stable")
    cumulative = np.cumsum(probabilities[order])
    j = min(int(np.searchsorted(cumulative, .5, side="left")), len(order)-1)
    return MetricValue("mode5.weighted_median_lower_tie_v1", unit, len(array), float(observed[order[j]]),
        components=(("positive_weight_observations", len(observed)), ("half_mass_tie", "lower")))


def weighted_mad(values, *, weights=None, unit="utility"):
    center = weighted_median(values, weights=weights, unit=unit)
    if center.status != "VALID":
        return MetricValue("mode5.weighted_mad_lower_tie_v1", unit, center.sample_count,
                           status=center.status, reason=center.reason)
    deviations = np.abs(vector(values) - center.value)
    median = weighted_median(deviations, weights=weights, unit=unit)
    return MetricValue("mode5.weighted_mad_lower_tie_v1", unit, median.sample_count,
        median.value, median.status, median.reason, (("median", center.value),))


def local_downside(center, neighbors, *, unit="utility"):
    """Canonical finite-probe downside; missing data must be handled by admission."""
    values = vector(neighbors)
    if not math.isfinite(center) or not len(values) or not np.isfinite(values).all():
        return MetricValue("mode5.local_downside_v1", unit, len(values), status="INVALID",
                           reason="complete finite center and nonempty probe panel required")
    downside = max(0., center - min(center, float(values.min())))
    if not math.isfinite(downside):
        return MetricValue("mode5.local_downside_v1", unit, len(values), status="INVALID", reason="downside overflow")
    return MetricValue("mode5.local_downside_v1", unit, len(values), downside,
                       components=(("scope", "finite_evaluated_probes_only"),))


@dataclass(frozen=True)
class FrozenReference:
    reference_id: str
    environment_ids: tuple[str, ...]
    values: tuple[float, ...]
    weights: tuple[float, ...]
    channel: str
    revision: str

    def __post_init__(self):
        for name in ("environment_ids", "values", "weights"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.reference_id or not self.channel or not self.revision:
            raise ValueError("frozen reference/channel/revision identity required")
        if not self.environment_ids or len(set(self.environment_ids)) != len(self.environment_ids):
            raise ValueError("unique environment identities required")
        if len(self.values) != len(self.environment_ids):
            raise ValueError("reference values must cover the exact environment roster")
        _distribution(self.values, self.weights)

    @cached_property
    def identity(self):
        return canonical_digest(dict(reference_id=self.reference_id, environment_ids=self.environment_ids,
            values=self.values, weights=self.weights, channel=self.channel, revision=self.revision,
            version="frozen_reference_regret_v1"))


def regret(values, *, environment_ids, channel, reference):
    if not isinstance(reference, FrozenReference):
        raise TypeError("typed frozen reference required")
    if tuple(environment_ids) != reference.environment_ids or channel != reference.channel:
        raise ValueError("candidate environment roster/channel differs from frozen reference")
    array = vector(values)
    if len(array) != len(reference.values) or not np.isfinite(array).all():
        raise ValueError("complete finite candidate panel required")
    components = np.asarray(reference.values) - array
    mean = lower_tail(components, 1., weights=reference.weights, unit=channel)
    if mean.status != "VALID":
        raise ValueError("regret arithmetic invalid")
    active = np.asarray(reference.weights) > 0
    return {"formula_id": "frozen_reference_regret_v1", "reference_identity": reference.identity,
        "channel": channel, "environment_ids": reference.environment_ids,
        "components": tuple(float(v) for v in components), "weighted_mean": mean.value,
        "maximum": float(components[active].max()), "positive_weight_environments": int(active.sum())}
