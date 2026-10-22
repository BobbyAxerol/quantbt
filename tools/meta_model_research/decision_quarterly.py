"""Cold DV05 reconciliation of the sealed quarterly fast-variant experiment.

No CLI, writes, fits, optimizer, account execution or inference. Original
monthly studies and active-meta arms are not factorial treatment cells. The
existing terminal custody and financial/selection qualification are reused,
not re-certified by this scalar report.
"""

from collections import Counter
from datetime import datetime, timedelta
from math import isclose, isfinite
from statistics import mean

from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.persistence import observation_from_payload
from quantbt.optimization.meta_selection.records import CompatibilityFamily
from tools.mode4_quarterly.analysis import ContrastScope, measure_quarter
from tools.mode4_quarterly.contracts import quarterly_calendar

from .admission import ROOT, read_verified
from .protocol import GROUPS


FAST = ROOT / "upgrade/private/mode5_upgrade_v1/m5-11-6-1/fast-v1"
PUBLIC = ROOT / "docs/mode5/M5_11_6_1_QUARTERLY_SUMMARY.json"
MANIFEST = FAST / "terminal-protected-manifest.json.gz"
PUBLIC_SHA256 = "602fbc20588e3dd99c1c05ced56b89410695ac4114d79415213ca0215c57cdef"
MANIFEST_SHA256 = "b64dd55aa98b9f5caca7dd742f967606d66f5d73b72dcdca32abf8a327f6c6af"
SAMPLERS = ("tpe_legacy", "tpe_multivariate_group")
ANCHORS = ("native", "floor")
FOLDS = quarterly_calendar()
QUARTERS = tuple(f.fold_id for f in FOLDS)
METRICS = ("R", "Q", "IS_effect")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


class _Evidence:
    """Read only hash-qualified members, pinning exactly the consumed files."""

    def __init__(self):
        self.pins = {}
        self.public = self._read(PUBLIC, PUBLIC_SHA256, 146544)
        manifest = self._read(MANIFEST, MANIFEST_SHA256, 1942897)
        self.allowed = {row["path"]: row for row in manifest}
        _require(len(self.allowed) == len(manifest), "duplicate custody path")

    def _read(self, path, sha256, size):
        value = read_verified(path, expected_sha256=sha256, expected_bytes=size,
                              max_bytes=64 * 1024**2)
        relative = str(path.relative_to(ROOT))
        self.pins[relative] = dict(path=relative, bytes=size, sha256=sha256)
        return value

    def read(self, path):
        ref = self.allowed.get(str(path))
        _require(ref is not None, "input is not a sealed quarterly custody member")
        return self._read(path, ref["sha256"], ref["bytes"])


def _count(value):
    _require(type(value) is int and value >= 0, "nonnegative observed count required")
    return value


def _index(rows, key, expected):
    indexed = {}
    for row in rows:
        identity = key(row)
        _require(identity not in indexed, "duplicate quarterly evidence slot")
        indexed[identity] = row
    _require(set(indexed) == set(expected), "incomplete or foreign quarterly roster")
    return indexed


def _sampling(search, sealed, sampler):
    """Observable dispatch is not a guess about random/startup fallback."""
    telemetry = search["sampler"]
    rows = telemetry["rows"]
    _require(telemetry["recipe"] == sampler and telemetry["attempts"] == 128
             and telemetry["requested_trials"] == 128 and len(rows) == 128
             and len({r["trial_id"] for r in rows}) == 128,
             "registered sampler/budget differs")
    states = Counter(r["state"] for r in rows)
    _require(set(states) <= {"COMPLETE", "PRUNED", "FAIL", "CANCELLED"}
             and dict(states) == telemetry["states"], "attempt states differ")
    relative = sum(bool(r["relative_dimensions"]) for r in rows)
    _require(relative == telemetry["relative_proposal_trials"], "relative dispatch differs")
    independent = sum(_count(n) for n in telemetry["independent_sample_calls"].values())
    fallback = telemetry.get("actual_fallback_count")
    _require(fallback is None or _count(fallback) <= 128, "invalid sampler fallback count")
    metadata = search["native"]["selection_metadata"]
    selector = metadata.get("selector")
    native_fallback = selector.startswith("fallback_") if isinstance(selector, str) else None
    reason = metadata.get("reason")
    candidates = sealed["base_task"]["candidates"]
    return dict(attempts=128, states=dict(states),
        unique_effective=_count(telemetry["unique_effective_candidates"]),
        duplicate_attempts=_count(telemetry["duplicate_attempts"]),
        feasible_complete=_count(telemetry["feasible_complete"]),
        captured_candidates=len(candidates),
        valid_raw_IS=sum(c["observation"]["status"] == "VALID" for c in candidates),
        relative_proposal_trials=relative, independent_parameter_calls=independent,
        actual_sampler_fallback_count=fallback,
        warm_start_attempts=_count(telemetry["warm_start_attempts"]),
        native_fallback=native_fallback,
        native_fallback_reason=reason if reason in {
            "insufficient_cluster_points", "no_dense_train_plateau"} else None,
        floor_supported=sealed["alternate_disposition"] == "SELECTED")


def _cell(evidence, group, sampler):
    directory = FAST / "studies-v3" / group / sampler
    pairs = _index(evidence.read(directory / "pairs.json.gz"),
        lambda r: (r["fold"], r["anchor"], r["mode"]),
        ((n, a, m) for n in range(19) for a in ANCHORS for m in ("off", "active")))
    arms, coverage = {}, []
    meta = {a: dict(fitted_quarters=0, fallback_quarters=0, learned_proposal_quarters=0,
                   not_fitted_quarters=0, effective_parameter_change_quarters=0,
                   first_fit=None) for a in ANCHORS}
    for n, fold in enumerate(FOLDS):
        target = directory / "folds" / f"{n:02d}"
        sealed = evidence.read(target / "sealed-selection.json.gz")
        forward = evidence.read(target / "forward.json.gz")
        search = evidence.read(target / "search.json.gz")
        base = sealed["base_task"]
        _require(sealed["before_current_forward"] is True,
                 "quarterly decisions were not sealed before forward")
        candidates = {c["evaluation_id"]: c for c in base["candidates"]}
        _require(len(candidates) == len(base["candidates"]), "duplicate IS candidate")
        outcomes = {o["evaluation_id"]: o["observation"] for o in forward["outcomes"]}
        _require(len(outcomes) == len(forward["outcomes"]), "duplicate forward witness")
        _require(len(sealed["families"]) == 2, "missing native/floor family")
        families = dict(zip(ANCHORS, sealed["families"], strict=True))
        _require(families["native"]["anchor"] == base["anchor_candidate_evaluation_id"],
                 "native family is not the base anchor")
        physical = digest({k: v for k, v in base["family"].items() if k != "sampler_policy_id"})
        identity = dict(physical=physical, seed=search["sampler"]["seed"],
            source=search["source_strategy_identity"],
            objective=search["sampler"]["optimization_mode"],
            objective_scope=search["sampler"]["objective_scope"],
            schedule=search["sampler"]["optimization_schedule"])
        _require(identity["objective"] == "mode_4_is_only_robust"
                 and identity["schedule"] == "per_fold_causal",
                 "quarterly objective or schedule changed")
        for anchor in ANCHORS:
            family = families[anchor]
            anchor_id = family["anchor"]
            family_id = CompatibilityFamily(**family["family"]).family_id
            _require(anchor_id in candidates and anchor_id in outcomes, "missing anchor witness")
            for mode in ("off", "active"):
                pair = pairs[n, anchor, mode]
                winner = family["anchor" if mode == "off" else "selected"]
                _require(pair["quarter"] == fold.fold_id and pair["family_id"] == family_id
                         and pair["model_id"] == family["decision"]["model_id"]
                         and pair["fit_status"] == family["decision"]["status"],
                         "pair family/calendar/decision differs")
                _require(pair["is_observation"] == candidates[winner]["observation"]
                         and pair["forward_observation"] == outcomes[winner]
                         and pair["native_is"] == candidates[anchor_id]["observation"]
                         and pair["native_forward"] == outcomes[anchor_id],
                         "raw pair differs from sealed IS/forward witness")
            pair = pairs[n, anchor, "off"]
            obs = {role: observation_from_payload(pair[key]) for role, key in (
                ("is", "is_observation"), ("forward", "forward_observation"))}
            _require(all(o.verification == "original_result" for o in obs.values()),
                     "authoritative raw metric observations required")
            arms[n, anchor] = dict(observations=obs, identity=identity)
            fitted = family["decision"]["model_id"] is not None
            learned = family["decision"]["status"] == "META_MODEL_PROPOSAL"
            meta[anchor]["fitted_quarters"] += int(fitted)
            meta[anchor]["not_fitted_quarters"] += int(not fitted)
            meta[anchor]["learned_proposal_quarters"] += int(learned)
            meta[anchor]["fallback_quarters"] += int(not learned)
            meta[anchor]["effective_parameter_change_quarters"] += int(
                candidates[family["selected"]]["effective_params"] != candidates[anchor_id]["effective_params"])
            if fitted and meta[anchor]["first_fit"] is None:
                meta[anchor]["first_fit"] = fold.fold_id
        coverage.append(dict(quarter=fold.fold_id, **_sampling(search, sealed, sampler)))
    return arms, dict(quarters=coverage, meta_decisions_all_slots=meta,
        states=dict(sum((Counter(r["states"]) for r in coverage), Counter())),
        totals={name: sum(r[name] for r in coverage) for name in (
            "attempts", "unique_effective", "duplicate_attempts", "feasible_complete",
            "captured_candidates", "valid_raw_IS", "relative_proposal_trials",
            "independent_parameter_calls", "warm_start_attempts")},
        native_fallback_quarters=sum(r["native_fallback"] is True for r in coverage),
        native_fallback_unknown_quarters=sum(r["native_fallback"] is None for r in coverage),
        floor_unsupported_quarters=sum(not r["floor_supported"] for r in coverage),
        actual_sampler_fallback_count=None if any(r["actual_sampler_fallback_count"] is None
            for r in coverage) else sum(_count(r["actual_sampler_fallback_count"]) for r in coverage),
        sampler_fallback_interpretation="independent parameter calls are not identified random fallbacks")


def _summary(rows):
    valid = [r for r in rows if r["status"] == "PAIRED_VALID"]
    means = {k: mean(r["metrics"][k] for r in valid) if valid else None for k in METRICS}
    _require(all(v is None or isfinite(v) for v in means.values()), "nonfinite quarterly mean")
    return dict(eligible_quarters=19, paired_quarters=len(valid),
        undefined_or_incompatible_quarters=19 - len(valid),
        paired_mask=[r["status"] == "PAIRED_VALID" for r in rows],
        available_pair_means_descriptive=means,
        all_quarter_means=means if len(valid) == 19 else None, quarters=rows)


def _contrast(group, name, references, policies):
    scope = ContrastScope(name, "legacy_reference", "reference-meta-off", "policy-meta-off")
    rows = []
    for n, quarter in enumerate(QUARTERS):
        reference, policy = references[n], policies[n]
        _require(reference["identity"] == policy["identity"],
                 "unmatched source/objective/seed/financial contract")
        a, b = reference["observations"], policy["observations"]
        result = measure_quarter(group, quarter, dict(reference_is=a["is"],
            reference_forward=a["forward"], policy_is=b["is"], policy_forward=b["forward"]), scope=scope)
        rows.append(dict(quarter=quarter, status=result.status, reasons=list(result.reasons),
            metrics={k: result.metrics[k] for k in METRICS},
            raw=dict(reference_IS=a["is"].raw_sharpe, reference_FWD=a["forward"].raw_sharpe,
                     policy_IS=b["is"].raw_sharpe, policy_FWD=b["forward"].raw_sharpe)))
    return _summary(rows)


def _interaction(legacy_selector, group_selector, sampler_only):
    rows = []
    for a, b, cross in zip(legacy_selector["quarters"], group_selector["quarters"],
                            sampler_only["quarters"], strict=True):
        _require(a["quarter"] == b["quarter"] == cross["quarter"], "interaction calendar differs")
        valid = a["status"] == b["status"] == cross["status"] == "PAIRED_VALID"
        metrics = {k: b["metrics"][k] - a["metrics"][k] if valid else None for k in METRICS}
        _require(all(v is None or isfinite(v) for v in metrics.values()), "nonfinite interaction")
        rows.append(dict(quarter=a["quarter"], status="PAIRED_VALID" if valid else "UNDEFINED",
            reasons=[] if valid else ["FOUR_ARM_COMMON_SUPPORT_REQUIRED"], metrics=metrics))
    return dict(definition="group selector contrast minus legacy selector contrast, meta off",
                formulas=dict(Q="(O_group_floor-O_group_native)-(O_legacy_floor-O_legacy_native)",
                    IS_effect="(I_group_native-I_group_floor)-(I_legacy_native-I_legacy_floor)",
                    R="IS_effect+Q"),
                **_summary(rows))


def _reconcile(actual, expected):
    _require(actual["paired_mask"] == expected["paired_mask"]
             and actual["paired_quarters"] == expected["paired_quarters"],
             "retained contrast support differs")
    for key in METRICS:
        a, b = actual["available_pair_means_descriptive"][key], expected["available_pair_means_descriptive"][key]
        _require(a is None and b is None or a is not None and b is not None
                 and isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), "retained raw contrast differs")


def _prefix(evidence, group):
    data = evidence.read(FAST / "studies-v3" / group / SAMPLERS[0] /
                         "folds/00/prefix-diagnostics.json.gz")
    # The producer runs this after the first legacy IS optimizer. Its cutoff
    # is a data vintage, not a wall-clock proof of pre-search availability.
    cutoff = datetime.fromisoformat(data["source_cutoff"])
    eligible = cutoff == FOLDS[0].is_end - timedelta(hours=1) and data["no_forward_outcomes_used"] is True
    legacy_first = "UNAVAILABLE_DEPENDS_ON_ITS_COMPLETED_POOL"
    group_first = "NOT_PROVEN_NO_DIAGNOSTIC_AVAILABLE_AT_OR_STUDY_START_ORDER"
    later = "NOT_PROVEN_NO_PER_STUDY_ADVICE_SEAL"
    return dict(prefix_data_eligible=eligible, source_quarter="2022Q1",
        legacy_first_search=legacy_first, group_first_search=group_first, later_searches=later,
        study_availability=[dict(quarter=quarter, sampler=sampler,
            status="INELIGIBLE_PREFIX" if not eligible else
            legacy_first if n == 0 and sampler == SAMPLERS[0] else group_first if n == 0 else later)
            for n, quarter in enumerate(QUARTERS) for sampler in SAMPLERS],
        validated_pre_search_router=False, neutral_design_sensitivity=False,
        compatibility="REGISTERED_GROUP_TPE_HYPOTHESIS_NOT_OUTCOME_WINNER",
        valid_raw_prefix=_count(data["valid_raw"]),
        unique_effective_prefix=_count(data["unique_effective"]))


def run_quarterly():
    """Return sanitized source-bound per-group DV05 tables; never write outputs."""
    evidence = _Evidence()
    public = evidence.public
    _require(public == evidence.read(FAST / "public-summary-v4.json"),
             "public summary differs from sealed handoff")
    _require(public["schema"] == "m51161.public-quarterly-summary.v1"
             and public["scope"]["quarters"] == 19 and public["scope"]["IS_days"] == 365
             and public["scope"]["trials_per_fold"] == 128
             and public["scope"]["research_variants_not_original_alpha_equivalence"] is True,
             "not the registered quarterly fast variant")
    retained = evidence.read(FAST / "quarterly-readback-v3.json")
    _require(retained["schema"] == "m51161.private-study-readback.v1"
             and retained["calendar"] == list(QUARTERS), "quarterly readback identity differs")
    registrations = [evidence.read(FAST / name) for name in (
        "study-registration.json", "study-v2-registration.json", "continuation-v3-registration.json")]
    _require(all((r["folds"], r["train_days"], r["attempts_per_fold"], r["seed"]) ==
                 (19, 365, 128, 731) for r in registrations[:2])
             and registrations[2]["source_scope"] == registrations[1]["source_identity"],
             "quarterly registration or continuation source differs")
    groups = {}
    for group in GROUPS:
        arms, support = {}, {}
        for sampler in SAMPLERS:
            key = f"{group}/{sampler}"
            _require(not retained["cells"][key]["input_issues"], "unqualified quarterly inputs")
            arms[sampler], support[sampler] = _cell(evidence, group, sampler)
            sealed_summary = public["cells"][key]
            _require(support[sampler]["totals"]["attempts"] == sealed_summary["logical_proposals"]
                     and support[sampler]["totals"]["relative_proposal_trials"] ==
                     sealed_summary["relative_proposal_trials"], "public sampler counts differ")
            for anchor, actual in support[sampler]["meta_decisions_all_slots"].items():
                expected = sealed_summary["all_sealed_decisions"][anchor]
                _require(actual["fitted_quarters"] == expected["fitted_quarters"]
                         and actual["first_fit"] == expected["first_fit"]
                         and actual["effective_parameter_change_quarters"] == expected["actual_parameter_changes"],
                         "public all-slot model/decision counts differ")
        def arm(sampler, anchor):
            return [arms[sampler][n, anchor] for n in range(19)]
        legacy, group_tpe = SAMPLERS
        contrasts = {}
        comparisons = {
            "sampler_only": (legacy, "native", group_tpe, "native"),
            "primary": (legacy, "native", group_tpe, "floor"),
            f"selector_only/{legacy}": (legacy, "native", legacy, "floor"),
            f"selector_only/{group_tpe}": (group_tpe, "native", group_tpe, "floor"),
        }
        for name, (s0, a0, s1, a1) in comparisons.items():
            table = _contrast(group, name, arm(s0, a0), arm(s1, a1))
            for expected in (retained["contrasts"][group][name]["summary"], public["contrasts"][group][name]):
                _reconcile(table, expected)
            contrasts[name] = table
        contrasts["interaction"] = _interaction(contrasts[f"selector_only/{legacy}"],
            contrasts[f"selector_only/{group_tpe}"], contrasts["sampler_only"])
        groups[group] = dict(contrasts=contrasts, support=support, prefix_advice=_prefix(evidence, group),
            advisory=dict(disposition="NO_CLEAR_WINNER", evidence="MATCHED_FAST_VARIANT_RESPONSE_ONLY",
                measured_response={name: dict(paired_quarters=table["paired_quarters"],
                    means=table["available_pair_means_descriptive"]) for name, table in contrasts.items()},
                competing_explanation="pool support, selector interaction and undefined raw metrics",
                missing_proof="original-route confirmation and prospectively sealed prefix advice",
                next_test="separately register original-route matched sampler/selector confirmation"))
    return dict(schema="m4.ml06.quarterly-reconciliation.v1", status="COLD_RECONCILED_DESCRIPTIVE",
        groups=groups, input_pins=[evidence.pins[k] for k in sorted(evidence.pins)],
        source_identities=[r["source_identity"] for r in registrations[:2]],
        limitations=["quarterly/365D fast variants only; no monthly/original pooling",
            "raw reset-forward Sharpe, not cluster/objective scores or continuous-account equity",
            "each contrast has its own mask; interaction uses four-arm common quarters",
            "undefined Sharpe is not zero; available means are not the complete-family estimand",
            "independent dispatch does not identify random/startup/sampler fallback",
            "prefix cutoff is not advice availability; no validated pre-search router",
            "adaptive reviewed pools do not establish neutral-design sensitivity or pristine OOS",
            "reuses sealed qualification; scalar readback is not new financial requalification",
            "RSI reference is not a registered two-sampler factorial group",
            "no new intervals, economic promotion or automatic sampler/selector recommendation"],
        new_model_fits=0, new_optimizer_proposals=0, new_financial_calls=0)
