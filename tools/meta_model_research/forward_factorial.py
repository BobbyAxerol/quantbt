"""Cold ML07 factorial decision support, independent of the monthly fit lane.

Reuse ML06's hash-qualified custody owner and all-pair cross-bind validation.
Only original raw reset-window observations enter the reducers. No accounts,
optimizers, model fits, evidence writes, inference or routing live here.
"""

from datetime import timedelta
from math import isfinite
from statistics import mean

from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.persistence import observation_from_payload
from tools.mode4_quarterly.analysis import ContrastScope, measure_quarter

from . import decision_quarterly as quarterly
from .decision_quarterly import _Evidence


MODES = ("off", "active")
MIN_ACTUALLY_LEARNED = 6
_require = quarterly._require
_METRICS = quarterly.METRICS


class _Capture:
    """Retain just the documents already consumed by the all-pair validator."""

    def __init__(self, evidence):
        self.evidence, self.documents = evidence, {}

    def read(self, path):
        value = self.evidence.read(path)
        if path.name in {"pairs.json.gz", "sealed-selection.json.gz"}:
            self.documents[path] = value
        return value


def _decision(family, base, number):
    decision, snapshot, fit = (family[k] for k in ("decision", "snapshot", "fit"))
    origins = 0 if snapshot is None else snapshot["origin_count"]
    _require(type(origins) is int and 0 <= origins <= max(0, number - 1),
             "quarterly history origin count differs")
    model = None if fit is None else fit["model"]
    fitted = model is not None
    _require(fitted == (decision["model_id"] is not None), "model readiness differs")
    family_id = quarterly.CompatibilityFamily(**family["family"]).family_id
    _require(decision["anchor_evaluation_id"] == family["anchor"]
             and decision["actual_evaluation_id"] == family["selected"]
             and decision["mode"] == "active"
             and decision["task_id"] == family["task_id"], "sealed activation differs")
    if fitted:
        _require(origins >= 12 and fit["origin_count"] == model["origin_count"] == origins
                 and model["family_id"] == family_id
                 and model["training_snapshot_id"] == snapshot["snapshot_id"] ==
                 decision["training_snapshot_id"]
                 and digest(dict(schema="qms-ridge-model-v1", model=model)) == decision["model_id"],
                 "model family/history/snapshot differs")
    learned = decision["status"] == "META_MODEL_PROPOSAL"
    _require(not learned or fitted, "learned decision without fitted model")
    _require(learned or family["selected"] == family["anchor"], "fallback changed anchor")
    candidates = {c["evaluation_id"]: c for c in base["candidates"]}
    changed = (candidates[family["selected"]]["effective_params"] !=
               candidates[family["anchor"]]["effective_params"])
    return dict(fitted=fitted, learned=learned, fallback=not learned, changed=changed,
        matured_origins=origins, fit_status=decision["status"], family_ref=family_id,
        model_ref=None if not fitted else decision["model_id"],
        anchor_ref=digest(family["anchor"]), selected_ref=digest(family["selected"]))


def _load_cell(evidence, group, sampler):
    captured = _Capture(evidence)
    off, support = quarterly._cell(captured, group, sampler)
    directory = quarterly.FAST / "studies-v3" / group / sampler
    pairs = {(r["fold"], r["anchor"], r["mode"]): r
             for r in captured.documents[directory / "pairs.json.gz"]}
    arms, states = {}, {}
    stable_families = {}
    for n in range(len(quarterly.QUARTERS)):
        sealed = captured.documents[directory / "folds" / f"{n:02d}" / "sealed-selection.json.gz"]
        base = sealed["base_task"]
        families = dict(zip(quarterly.ANCHORS, sealed["families"], strict=True))
        _require(len({quarterly.CompatibilityFamily(**f["family"]).family_id
                      for f in families.values()}) == 2, "anchor families are not distinct")
        _require(len({f["family"]["window_policy_id"] for f in families.values()}) == 1,
                 "anchor family window policies differ")
        def physical(family):
            return {k: v for k, v in family.items()
                    if k not in {"anchor_policy_id", "window_policy_id"}}
        for anchor, family in families.items():
            _require(physical(family["family"]) == physical(base["family"]),
                     "rebased family physical identity differs")
            state = _decision(family, base, n)
            _require(stable_families.setdefault(anchor, state["family_ref"]) == state["family_ref"],
                     "history family changed across quarters")
            state["selector_supported"] = anchor == "native" or sealed["alternate_disposition"] == "SELECTED"
            states[n, anchor] = state
            for mode in MODES:
                pair = pairs[n, anchor, mode]
                _require(pair["matured_origins"] == state["matured_origins"]
                         and pair["changed"] is (mode == "active" and family["selected"] != family["anchor"]),
                         "pair history or changed identity differs")
                obs = {role: observation_from_payload(pair[key]) for role, key in
                       (("is", "is_observation"), ("forward", "forward_observation"))}
                _require(all(o.verification == "original_result" for o in obs.values()),
                         "authoritative original active observations required")
                arms[n, anchor, mode] = dict(observations=obs, identity=off[n, anchor]["identity"])
    return arms, states, support


def _raw(observation):
    return dict(status=observation.status.value, raw_sharpe=observation.raw_sharpe,
        activity_count=observation.activity_count, sample_count=observation.sample_count,
        window_start=observation.window_start.isoformat(), window_end=observation.window_end.isoformat(),
        input_frontier=observation.input_frontier.isoformat())


def _contrast(group, name, references, policies, *, own_anchor=False):
    scope = ContrastScope(name, "own_anchor" if own_anchor else "legacy_reference", "reference", "policy")
    rows = []
    for quarter, fold, reference, policy in zip(
            quarterly.QUARTERS, quarterly.FOLDS, references, policies, strict=True):
        _require(reference["identity"] == policy["identity"],
                 "unmatched source/objective/seed/financial contract")
        a, b = reference["observations"], policy["observations"]
        result = measure_quarter(group, quarter, dict(reference_is=a["is"], reference_forward=a["forward"],
            policy_is=b["is"], policy_forward=b["forward"]), scope=scope)
        rows.append(dict(quarter=quarter, origin=(fold.is_end - timedelta(hours=1)).isoformat(),
            status=result.status, reasons=list(result.reasons), metrics={k: result.metrics[k] for k in _METRICS}))
    return rows


def _difference(reference, policy):
    """Subtract per-quarter contrasts before reduction, never unequal-mask means."""
    rows = []
    for a, b in zip(reference, policy, strict=True):
        _require(a["quarter"] == b["quarter"] and a["origin"] == b["origin"], "DID calendar differs")
        valid = a["status"] == b["status"] == "PAIRED_VALID"
        metrics = {k: b["metrics"][k] - a["metrics"][k] if valid else None for k in _METRICS}
        _require(all(v is None or isfinite(v) for v in metrics.values()), "nonfinite factorial difference")
        rows.append(dict(quarter=a["quarter"], origin=a["origin"],
            status="PAIRED_VALID" if valid else "UNDEFINED",
            reasons=[] if valid else ["EXACT_COMMON_SUPPORT_REQUIRED", *a["reasons"], *b["reasons"]],
            metrics=metrics))
    return rows


def _summary(rows, eligible):
    mask = [e and r["status"] == "PAIRED_VALID" for r, e in zip(rows, eligible, strict=True)]
    valid = [r for r, keep in zip(rows, mask, strict=True) if keep]
    means = {k: mean(r["metrics"][k] for r in valid) if valid else None for k in _METRICS}
    _require(all(v is None or isfinite(v) for v in means.values()), "nonfinite factorial mean")
    return dict(calendar_quarters=len(rows), eligible_mask=eligible, eligible_quarters=sum(eligible),
        paired_mask=mask, paired_quarters=sum(mask),
        paired_quarter_ids=[r["quarter"] for r, keep in zip(rows, mask, strict=True) if keep],
        undefined_or_incompatible_quarters=sum(eligible) - sum(mask),
        available_pair_means_descriptive=means,
        all_eligible_means=means if valid and len(valid) == sum(eligible) else None,
        all_quarter_means=means if len(valid) == len(rows) else None,
        quarters=[dict(r, status="EXCLUDED", reasons=["OUTSIDE_COHORT"], metrics=dict.fromkeys(_METRICS))
                  if not e else dict(r) for r, e in zip(rows, eligible, strict=True)])


def _report(rows, participants):
    # Off contrasts use their corresponding active decisions for cohort masks.
    # For multiple cells, fitted/learned require ALL; fallback/change mean ANY.
    masks = dict(all_calendar=[True] * len(rows),
        fitted=[all(s["fitted"] for s in states) for states in zip(*participants, strict=True)],
        actually_learned=[all(s["learned"] for s in states) for states in zip(*participants, strict=True)],
        fallback_involved=[any(s["fallback"] for s in states) for states in zip(*participants, strict=True)],
        not_fitted_involved=[any(not s["fitted"] for s in states) for states in zip(*participants, strict=True)],
        changed=[any(s["changed"] for s in states) for states in zip(*participants, strict=True)])
    cohorts = {name: _summary(rows, mask) for name, mask in masks.items()}
    learned = cohorts["actually_learned"]
    return dict(cohorts=cohorts, support=dict(minimum_actually_learned_quarters=MIN_ACTUALLY_LEARNED,
        actually_learned_quarters=learned["eligible_quarters"],
        actually_learned_paired_quarters=learned["paired_quarters"],
        minimum_met=learned["paired_quarters"] >= MIN_ACTUALLY_LEARNED,
        descriptive_only=True))


def _group(group, cells, states, support):
    def arm(sampler, anchor, mode):
        return [cells[sampler][n, anchor, mode] for n in range(len(quarterly.QUARTERS))]

    def decision(sampler, anchor):
        return [states[sampler][n, anchor] for n in range(len(quarterly.QUARTERS))]

    arms, meta = {}, {}
    for sampler in quarterly.SAMPLERS:
        for anchor in quarterly.ANCHORS:
            decisions = decision(sampler, anchor)
            name = f"{sampler}/{anchor}"
            meta[name] = _report(_contrast(group, name, arm(sampler, anchor, "off"),
                arm(sampler, anchor, "active"), own_anchor=True), [decisions])
            for mode in MODES:
                rows = []
                for n, (cell, state) in enumerate(zip(arm(sampler, anchor, mode), decisions, strict=True)):
                    active = mode == "active"
                    rows.append(dict(quarter=quarterly.QUARTERS[n],
                        origin=(quarterly.FOLDS[n].is_end - timedelta(hours=1)).isoformat(),
                        raw={role: _raw(o) for role, o in cell["observations"].items()},
                        family_ref=state["family_ref"], source_identity_ref=digest(cell["identity"]),
                        anchor_ref=state["anchor_ref"],
                        selected_ref=state["selected_ref"] if active else state["anchor_ref"],
                        model_ref=state["model_ref"] if active else None,
                        matured_origins=state["matured_origins"] if active else None,
                        fit_status=state["fit_status"] if active else "META_OFF",
                        fitted=active and state["fitted"], actually_learned=active and state["learned"],
                        fallback=active and state["fallback"], changed=active and state["changed"],
                        valid_IS=cell["observations"]["is"].status.value == "VALID",
                        valid_forward=cell["observations"]["forward"].status.value == "VALID",
                        selector_supported=state["selector_supported"]))
                arms[f"{name}/{mode}"] = dict(quarters=rows,
                    counts={key: sum(r[key] for r in rows) for key in
                            ("fitted", "actually_learned", "fallback", "changed", "selector_supported",
                             "valid_IS", "valid_forward")})
    legacy, challenger = quarterly.SAMPLERS
    comparisons = {f"sampler/{a}": ((legacy, a), (challenger, a)) for a in quarterly.ANCHORS}
    comparisons.update({f"selector/{s}": ((s, "native"), (s, "floor")) for s in quarterly.SAMPLERS})
    comparisons["combined"] = ((legacy, "native"), (challenger, "floor"))
    contrasts, raw = {mode: {} for mode in MODES}, {mode: {} for mode in MODES}
    for name, (a, b) in comparisons.items():
        for mode in MODES:
            raw[mode][name] = _contrast(group, name, arm(*a, mode), arm(*b, mode))
            contrasts[mode][name] = _report(raw[mode][name], [decision(*a), decision(*b)])
    all_states = [decision(s, a) for s in quarterly.SAMPLERS for a in quarterly.ANCHORS]
    for mode in MODES:
        raw[mode]["sampler_selector"] = _difference(
            raw[mode][f"selector/{legacy}"], raw[mode][f"selector/{challenger}"])
        contrasts[mode]["sampler_selector"] = _report(raw[mode]["sampler_selector"], all_states)
    interactions, matched = {}, {}
    for name in raw["off"]:
        participants = all_states if name == "sampler_selector" else [decision(*p) for p in comparisons[name]]
        difference = _difference(raw["off"][name], raw["active"][name])
        matched[name] = {}
        for mode in MODES:
            rows = [dict(row) if common["status"] == "PAIRED_VALID" else
                    dict(row, status=common["status"], reasons=common["reasons"], metrics=dict.fromkeys(_METRICS))
                    for row, common in zip(raw[mode][name], difference, strict=True)]
            matched[name][mode] = _report(rows, participants)
        interactions[name] = dict(definition="active contrast minus off contrast on exact common quarters",
            **_report(difference, participants))
    return dict(arms=arms, own_anchor_meta=meta, contrasts=contrasts,
        matched_off_active=matched, meta_interactions=interactions, sampler_support=support)


def run_factorial():
    """Return sanitized, JSON-compatible full-factorial readback; never persist."""
    evidence = _Evidence()
    public = evidence.public
    _require(public == evidence.read(quarterly.FAST / "public-summary-v4.json"),
             "public summary differs from sealed handoff")
    _require(public["schema"] == "m51161.public-quarterly-summary.v1"
             and public["scope"]["quarters"] == 19 and public["scope"]["IS_days"] == 365
             and public["scope"]["trials_per_fold"] == 128
             and public["scope"]["research_variants_not_original_alpha_equivalence"] is True,
             "not the registered quarterly fast variant")
    retained = evidence.read(quarterly.FAST / "quarterly-readback-v3.json")
    _require(retained["schema"] == "m51161.private-study-readback.v1"
             and retained["calendar"] == list(quarterly.QUARTERS), "quarterly readback identity differs")
    registrations = [evidence.read(quarterly.FAST / name) for name in
        ("study-registration.json", "study-v2-registration.json", "continuation-v3-registration.json")]
    _require(all((r["folds"], r["train_days"], r["attempts_per_fold"], r["seed"]) ==
                 (19, 365, 128, 731) for r in registrations[:2])
             and registrations[2]["source_scope"] == registrations[1]["source_identity"],
             "quarterly registration or continuation source differs")
    groups = {}
    for group in quarterly.GROUPS:
        cells, states, support = {}, {}, {}
        for sampler in quarterly.SAMPLERS:
            key = f"{group}/{sampler}"
            _require(not retained["cells"][key]["input_issues"], "unqualified quarterly inputs")
            cells[sampler], states[sampler], support[sampler] = _load_cell(evidence, group, sampler)
            expected = public["cells"][key]
            _require(support[sampler]["totals"]["attempts"] == expected["logical_proposals"]
                     and support[sampler]["totals"]["relative_proposal_trials"] == expected["relative_proposal_trials"],
                     "public sampler counts differ")
            for anchor, actual in support[sampler]["meta_decisions_all_slots"].items():
                sealed = expected["all_sealed_decisions"][anchor]
                _require(actual["fitted_quarters"] == sealed["fitted_quarters"]
                         and actual["first_fit"] == sealed["first_fit"]
                         and actual["effective_parameter_change_quarters"] == sealed["actual_parameter_changes"],
                         "public model/decision counts differ")
        groups[group] = _group(group, cells, states, support)
    return dict(schema="m4.ml07.forward-factorial.v1", status="COLD_DESCRIPTIVE_READBACK",
        calendar=list(quarterly.QUARTERS), groups=groups,
        input_pins=[evidence.pins[k] for k in sorted(evidence.pins)],
        source_identity_refs=[digest(r["source_identity"]) for r in registrations[:2]],
        definitions=dict(R="(I_reference-O_reference)-(I_policy-O_policy)",
            Q="O_policy-O_reference", IS_effect="I_reference-I_policy", R_identity="R=IS_effect+Q",
            sampler="group TPE minus legacy, same selector and meta mode",
            selector="floor minus native, same sampler and meta mode",
            sampler_selector="group selector effect minus legacy selector effect",
            meta_interaction="active effect minus off effect; sampler_selector is the eight-arm triple difference",
            cohorts="fitted/learned require every participating active cell; fallback/changed require any"),
        limitations=["quarterly/365D fast variants only, not monthly/730D originals",
            "reuses sealed custody and financial qualification; not new financial certification",
            "all-calendar and available/cohort means differ; gaps remain null calendar slots",
            "six actually learned paired quarters is descriptive support, not efficacy or promotion",
            "model fit, learned proposal, fallback, and effective parameter change are distinct",
            "raw reset-window Sharpe is not a continuous-account Sharpe or optimizer objective",
            "reviewed adaptive pools are not pristine OOS or neutral-design sensitivity",
            "independent sampler dispatch does not identify random fallback",
            "no inference, router validation, sampler recommendation or production adoption"],
        new_model_fits=0, new_optimizer_proposals=0, new_financial_calls=0)
