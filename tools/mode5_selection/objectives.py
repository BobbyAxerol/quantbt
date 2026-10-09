"""Canonical same-channel components; shared tails and local math have one owner."""
import math

import numpy as np

from tools.mode5_statistics.contracts import MetricValue
from tools.mode5_statistics.tails import local_downside, lower_tail, regret, weighted_mad
from .contracts import FORMULAS


def economic_utility(net_return, drawdown, daily_loss_es, *, dd_weight, tail_weight, preference_id):
    if not preference_id or any(not math.isfinite(w) or w < 0 for w in (dd_weight, tail_weight)):
        raise ValueError("frozen economic preference identity/coefficients required")
    metrics = (net_return, drawdown, daily_loss_es)
    if any(not isinstance(m, MetricValue) or m.unit != "decimal_return" for m in metrics):
        raise ValueError("net account return, drawdown and daily ES require decimal return units")
    if any(m.status != "VALID" for m in metrics):
        return MetricValue("mode5.utility.net_v1", "decimal_return", net_return.sample_count,
                           status="UNDEFINED", reason="economic input unavailable")
    if drawdown.value < 0:
        raise ValueError("canonical drawdown is a positive magnitude, not signed legacy drawdown")
    value = net_return.value-dd_weight*drawdown.value-tail_weight*daily_loss_es.value
    if not math.isfinite(value):
        return MetricValue("mode5.utility.net_v1", "decimal_return", net_return.sample_count,
                           status="INVALID", reason="economic utility overflow")
    return MetricValue("mode5.utility.net_v1", "decimal_return", net_return.sample_count, value,
        components=(("preference_id", preference_id), ("dd_weight", dd_weight), ("tail_weight", tail_weight),
                    ("costs", "already_in_net_return_no_second_fee_deduction")))


def environment_components(values, reference, channel):
    array = np.asarray(values, dtype=float)
    mean = lower_tail(array, 1., weights=reference.weights, unit=channel.unit)
    mad = weighted_mad(array, weights=reference.weights, unit=channel.unit)
    if mean.status != "VALID" or mad.status != "VALID":
        raise ArithmeticError("invalid environment arithmetic")
    weights = np.asarray(reference.weights, dtype=float)
    weights = weights/weights.max()
    weights = weights/weights.sum()
    # Scaling before squaring avoids avoidable overflow on finite utilities.
    scale = max(float(np.abs(array).max()), abs(mean.value))
    sd = 0. if scale == 0 else scale*math.sqrt(float(weights @ ((array/scale-mean.value/scale)**2)))
    try:
        regrets = regret(array, environment_ids=reference.environment_ids, channel=channel.identity, reference=reference)
    except ValueError as exc:
        raise ArithmeticError("invalid regret arithmetic") from exc
    components = dict(floor=float(array.min()), mean=mean.value, sd=sd, mad=mad.value,
        mean_regret=regrets["weighted_mean"], max_regret=regrets["maximum"])
    if any(not math.isfinite(v) for v in components.values()):
        raise ArithmeticError("environment arithmetic overflow")
    return components


def qualify_local(panel, candidate, plan, local):
    if local is None:
        return None, "MISSING_LOCAL_EVIDENCE"
    if (local.candidate_id != candidate.candidate_id or local.channel != panel.channel
            or local.reference_id != plan.local_reference_id
            or local.reference_scale != plan.local_reference_scale):
        raise ValueError("local candidate/channel/reference differs from frozen plan")
    for probe in local.probes:
        panel.access.require(probe.witness)
        if probe.analysis.normalization_reference != panel.reference.identity:
            raise ValueError("local probe aggregate reference differs from center")
        if panel.channel.name == "PSR_EVIDENCE_V1" and probe.value is not None and not 0 <= probe.value <= 1:
            raise ValueError("same evidence probability required for local probe")
    if any(p.status != "COMPLETE" for p in local.probes):
        return None, "INCOMPLETE_LOCAL_PROBES"
    if local.coverage != "OBSERVED_REQUIRED_RADII":
        return None, "INSUFFICIENT_LOCAL_COVERAGE"
    return tuple(p.value for p in local.probes), None


def evaluate(panel, plan, *, local_evidence=()):
    plan.require(panel)
    locals_by_id = {row.candidate_id: row for row in local_evidence}
    if len(locals_by_id) != len(local_evidence) or set(locals_by_id)-{c.candidate_id for c in panel.candidates}:
        raise ValueError("unique local records matching candidate roster required")
    family = FORMULAS[plan.formula.version][0]
    if family == "pareto":
        raise ValueError("Pareto uses the explicit normalized vector reducer")
    if family not in {"local", "unified"} and local_evidence:
        raise ValueError("unused local evidence cannot be silently accepted")
    p, rows = plan.formula.params, []
    binding = dict(plan_identity=plan.identity, formula_identity=plan.formula.identity,
                   reference_identity=panel.reference.identity)
    for c in panel.candidates:
        reasons = [name for name, ok in (("INFEASIBLE", c.feasible), ("RISK_FAIL", c.risk_pass),
            ("QUALITY_FAIL", c.quality_pass), ("INSUFFICIENT_SUPPORT", c.support_pass),
            ("UNEVALUATED_REPRESENTATIVE", c.evaluated)) if not ok]
        if any(m.status != "VALID" for m in c.metrics):
            reasons.append("INCOMPLETE_ENVIRONMENTS")
        probes = None
        if family in {"local", "unified"}:
            probes, reason = qualify_local(panel, c, plan, locals_by_id.get(c.candidate_id))
            if reason:
                reasons.append(reason)
        row = dict(candidate_id=c.candidate_id, params_digest=c.params_digest, gate_ref=c.gate_ref,
            **binding,
            representative_kind=c.representative_kind, eligible=not reasons, reasons=reasons,
            score=None, components=None)
        # Risk/quality failures remain visible with their valid numerical components.
        if all(m.status == "VALID" for m in c.metrics):
            try:
                values = tuple(m.value for m in c.metrics)
                parts = environment_components(values, panel.reference, panel.channel)
                parts["activity_penalty"] = c.activity_penalty
                score, version = None, plan.formula.version
                if version == "environment_floor_mean_v1":
                    score = parts["floor"]+p["mean"]*parts["mean"]-c.activity_penalty
                elif version == "legacy_floor_mean_regret_v1":
                    score = parts["floor"]-p["mean"]*parts["mean_regret"]-c.activity_penalty
                elif version == "finite_panel_minimax_regret_v1":
                    score = -parts["max_regret"]-c.activity_penalty
                elif version in {"legacy_spec_1_1_quantile", "environment_lower_tail_v2"}:
                    if version == "legacy_spec_1_1_quantile":
                        if len(set(panel.reference.weights)) != 1:
                            raise ValueError("legacy linear quantile/MAD replay requires equal weights")
                        tail = float(np.quantile(values, p["alpha"], method="linear"))
                        parts["mad"] = float(np.median(np.abs(np.asarray(values)-np.median(values))))
                        parts["tail_definition"] = "linear_quantile_floor_heuristic_not_CVaR"
                    else:
                        tail_result = lower_tail(values, p["alpha"], weights=panel.reference.weights, unit=panel.channel.unit)
                        if tail_result.status != "VALID":
                            raise ArithmeticError("invalid tail arithmetic")
                        tail = tail_result.value
                        parts["tail_definition"] = "lower_environment_utility_tail"
                    parts["tail"] = tail
                    relative_weights = np.asarray(panel.reference.weights)/max(panel.reference.weights)
                    minimum_mass = math.fsum(w for x, w in zip(values, relative_weights, strict=True)
                                             if x == parts["floor"])/math.fsum(relative_weights)
                    parts["floor_tail_redundancy"] = version == "environment_lower_tail_v2" and p["alpha"] <= minimum_mass
                    score = p["floor"]*parts["floor"]+p["tail"]*tail-p["dispersion"]*parts["mad"]-c.activity_penalty
                elif probes is not None:
                    downside = local_downside(parts["mean"], probes, unit=panel.channel.unit)
                    if downside.status != "VALID":
                        raise ArithmeticError("invalid local downside")
                    parts.update(fragility=downside.value, normalized_fragility=downside.value/plan.local_reference_scale,
                        local_reference_id=plan.local_reference_id, local_identity=locals_by_id[c.candidate_id].identity,
                        covariance_status=locals_by_id[c.candidate_id].covariance_status,
                        empirical_local_worst=min(parts["mean"], *probes), aggregate="weighted_environment_mean_v1")
                    if version == "local_downside_v1":
                        score = parts["mean"]-p["gamma"]*parts["fragility"]-c.activity_penalty
                    else:
                        score = (p["floor"]*parts["floor"]+p["mean"]*parts["mean"]-
                                 p["dispersion"]*parts["sd"]-p["fragility"]*parts["fragility"]-c.activity_penalty)
                if score is not None and not math.isfinite(score):
                    raise ArithmeticError("objective overflow")
                row.update(score=score, components=parts)
            except (ArithmeticError, OverflowError):
                row["eligible"] = False
                row["reasons"].append("ARITHMETIC_INVALID")
        rows.append(row)
    return tuple(rows)
