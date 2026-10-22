"""ML-06 prefix diagnostics on admitted monthly evidence, without fitting.

The caller owns registration and persistence. Only retained IS inputs, saved
models/decisions and the exact permitted history snapshot are consumed. Public
exports omit parameter names/values, descriptor coordinates and source paths.
"""

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from quantbt.diagnostics import (
    AccessPolicy, AccessWitness, AlphaDiagnostics, DiagnosticContext,
    DiagnosticObservation,
)
from quantbt.optimization.meta_selection.artifacts import loads_decision, loads_model
from quantbt.optimization.meta_selection.common import canonical, digest, utc
from quantbt.optimization.meta_selection.descriptors import OriginBalancedStandardizer
from quantbt.optimization.meta_selection.model import schema_payload
from quantbt.optimization.meta_selection.records import OutcomeStatus

from .admission import Corpus, read_verified


VERSION = "m4.ml06.monthly-prefix-diagnostics.v1"


def _require(condition, reason):
    if not condition:
        raise ValueError("MLR06_DIAGNOSTICS_" + reason)


def _unavailable(reason):
    return dict(status="UNAVAILABLE", value=None, reason=reason)


def _bundle(payload, schema):
    return canonical(dict(schema=schema, payload=payload, content_digest=digest(payload)))


def _source(corpus, fold):
    """Reverify exact bytes rather than trusting mutable decoded dictionaries."""
    documents, refs = {}, {}
    for name in ("revision", "selection"):
        suffix = ("folds", f"{fold:02d}", name + ".json.gz")
        matches = [p for p in corpus.pins if Path(p["path"]).parts[-3:] == suffix]
        _require(len(matches) == 1, "SOURCE_PIN_ROSTER")
        ref = matches[0]
        documents[name] = read_verified(
            ref["path"], expected_sha256=ref["sha256"], expected_bytes=ref["bytes"])
        refs[name] = dict(sha256=ref["sha256"], bytes=ref["bytes"])
    saved = corpus.selections[fold]
    _require(digest(saved) == digest(documents["selection"]), "SELECTION_BYTES_CHANGED")
    revision = documents["revision"]
    task = corpus.revisions[fold].task
    _require(digest(revision["payload"]) == revision["content_digest"], "REVISION_DIGEST")
    _require(digest(saved["task"]) == digest(task) ==
             digest(revision["payload"]["task"]), "TASK_BINDING")
    return saved, dict(refs, task_digest=digest(task),
                       model_digest=digest(saved["model"]) if saved["model"] else None)


def _retained(corpus, fold, saved):
    task, record = corpus.revisions[fold].task, saved["record"]
    snapshot = corpus.snapshot(fold)
    _require(snapshot.information_as_of <= task.data_cutoff, "FUTURE_SNAPSHOT")
    _require(snapshot.family_id == task.family.family_id, "SNAPSHOT_FAMILY")
    # HistorySnapshot owns role, manifest, maturity and revision availability.
    _require(all(r.task.origin < task.origin for r in snapshot.revisions), "NONPREFIX_HISTORY")
    candidates = {c.evaluation_id: c for c in task.candidates}
    anchor, selected = task.anchor_candidate_evaluation_id, record["selected_evaluation_id"]
    _require(selected in candidates and record["native_selected_evaluation_id"] == anchor,
             "SELECTED_OR_ANCHOR_ID")
    _require(record["current_outer_oos_used_for_selection"] is False, "CURRENT_FORWARD_RIGHTS")
    for key, eid in (("selected_params", selected), ("native_selected_params", anchor)):
        _require(digest(record[key]) == digest(candidates[eid].effective_params), "PARAM_BINDING")
    _require(utc(record["information_as_of"]) == task.data_cutoff and
             utc(record["decision_sealed_at"]) == task.decision_sealed_at, "DECISION_CLOCK")
    _require(record["training_snapshot_id"] == snapshot.snapshot_id, "SNAPSHOT_BINDING")
    proposal = record["proposal"]
    decision = loads_decision(
        _bundle(proposal, "qms-decision-bundle-v1"),
        expected_decision_id=digest(dict(schema="qms-selection-decision-v1", decision=proposal)),
        available_as_of=task.decision_sealed_at)
    _require(decision.task_id == task.task_id and decision.anchor_evaluation_id == anchor and
             decision.information_as_of == task.data_cutoff and
             decision.decision_sealed_at == task.decision_sealed_at and
             decision.training_snapshot_id == (snapshot.snapshot_id if saved["model"] else None) and
             decision.status == record["final_selection_reason"], "PROPOSAL_BINDING")
    _require((decision.actual_evaluation_id or decision.proposed_evaluation_id) == selected,
             "ACTUAL_SELECTION_BINDING")
    _require(decision.proposed_evaluation_id in candidates and
             digest(decision.proposed_params) ==
             digest(candidates[decision.proposed_evaluation_id].effective_params), "PROPOSAL_PARAMS")
    model = None
    if saved["model"] is not None:
        model = loads_model(_bundle(saved["model"], "qms-model-bundle-v1"),
                            expected_model_id=decision.model_id,
                            available_as_of=task.decision_sealed_at)
        _require(model.training_snapshot_id == snapshot.snapshot_id and
                 model.information_as_of == snapshot.information_as_of and
                 model.family_id == task.family.family_id and
                 digest(model.schema) == digest(schema_payload(corpus.schema)) and
                 model.origin_count == snapshot.origin_count, "MODEL_PREFIX_BINDING")
        expected_refs = sorted((r.task.task_id, r.revision_id, r.content_digest)
                               for r in snapshot.revisions)
        _require(sorted(model.revision_references) == expected_refs, "MODEL_HISTORY_BINDING")
        expected_rows = sorted((r.task_id, r.revision_id, r.candidate_evaluation_id, r.origin_weight)
                               for r in snapshot.training_rows)
        _require(sorted(model.fit_row_references) == expected_rows, "MODEL_FIT_MASK_BINDING")
    else:
        _require(decision.model_id is None and decision.status != "META_MODEL_PROPOSAL",
                 "MISSING_SERVED_MODEL")
    return snapshot, decision, model


def _shared(corpus, task):
    ranges = corpus.schema.space.portable_ranges()
    for spec in corpus.schema.space.specs:
        if spec.active_if:
            ranges[spec.name]["active_if"] = dict(spec.active_if)
    context = DiagnosticContext(
        alpha_id=task.family.strategy_id, market_id=task.family.instrument_id,
        economics_id=task.family.economics_id, route_id=task.family.scorer_contract_id,
        metric_units=(("raw_is_sharpe", task.family.metric_contract_id),),
        primary_metric="raw_is_sharpe", direction="maximize",
        generation_method=task.family.sampler_policy_id, outcome_blind_roster=False,
        activity_definition="retained_metric_contract:" + task.family.metric_contract_id)
    access = AccessPolicy("mlr06-monthly-prefix-v1", ("diagnostic_development",),
                          (task.corpus_id,), int(task.data_cutoff.value), "diagnostic")
    diagnostics = AlphaDiagnostics(ranges, context=context, access=access)
    observations = []
    for candidate in task.candidates:
        m = candidate.observation
        _require(m.verification != "unverified", "UNVERIFIED_IS")
        # This witness dates INPUT availability, not computation completion.
        # Search/fit may finish after data_cutoff, but must precede sealing.
        witness = AccessWitness(task.corpus_id, "diagnostic_development",
            int(m.window_start.value), int(m.window_end.value),
            int(max(m.window_end, m.input_frontier).value))
        _require(candidate.resolved_at <= task.decision_sealed_at, "IS_COMPLETION_CLOCK")
        observations.append(DiagnosticObservation.from_params(
            geometry=diagnostics.geometry, params=candidate.effective_params,
            metrics={"raw_is_sharpe": m.raw_sharpe if m.status == OutcomeStatus.VALID else None},
            evaluation_id=candidate.evaluation_id, context_id=context.identity,
            source_ref=digest(m), witness=witness, activity_count=m.activity_count))
    shared = diagnostics.analyze(observations)
    report = dict(shared.to_dict(), report_id=shared.identity)
    return diagnostics.geometry, observations, report


def _coverage(task, observations, report):
    axes = []
    aliases = {s["name"]: f"axis_{i:03d}" for i, s in enumerate(report["geometry"]["axes"])}
    for axis in report["geometry"]["axes"]:
        axes.append(dict(axis, name=aliases[axis["name"]]))
    # Branch membership uses the shared effective resolution and activity mask.
    branch_counts = Counter()
    specs = {s["name"]: s for s in report["geometry"]["axes"]}
    for row in observations:
        branch = dict(active=row.point.active_names,
            categories={n: v for n, v in row.point.params.items()
                        if specs[n]["kind"] in {"categorical", "boolean"}})
        branch_counts[digest(branch)] += 1
    counts = task.sampling_provenance.get("trial_counts", {})
    _require(isinstance(counts, Mapping), "TRIAL_COUNTS_FORMAT")
    trials = {}
    for name in ("attempted", "completed", "pruned", "failed"):
        value = counts.get(name)
        if value is None:
            trials[name] = _unavailable("No actual trial ledger count in retained sampling provenance.")
        else:
            _require(type(value) is int and value >= 0, "TRIAL_COUNT")
            trials[name] = dict(status="SOURCE_BOUND", value=value,
                pointer="/task/sampling_provenance/trial_counts/" + name)
    if all(trials[n]["value"] is not None for n in trials):
        _require(counts["attempted"] == sum(counts[n] for n in ("completed", "pruned", "failed")),
                 "TRIAL_COUNT_TOTAL")
    budget = task.sampling_provenance.get("budget")
    _require(budget is None or (type(budget) is int and budget >= 0), "TRIAL_BUDGET_FORMAT")
    return dict(report["coverage"], trials=trials,
        requested_trial_budget=budget,
        metric_status_counts=dict(Counter(c.observation.status.value for c in task.candidates)),
        pool_scope="retained_eligible_IS_evaluations_not_all_optimizer_attempts",
        axes=axes, nominal_dimensions=sum(a["variable"] for a in axes),
        observed_varying_dimensions=sum(a["variable"] and a["observed_values"] > 1 for a in axes),
        conditional_dimensions=sum(a["conditional"] for a in axes),
        active_dimensions=dict(minimum=min(len(r.point.active_names) for r in observations),
                               maximum=max(len(r.point.active_names) for r in observations)),
        branches=[dict(branch=f"branch_{i:03d}", evaluations=count)
                  for i, count in enumerate(branch_counts.values())],
        effective_dimension_estimate=_unavailable("No qualified dimension estimator/design retained."))


def _native(record):
    source = record.get("native_selection_reason")
    if not isinstance(source, Mapping):
        return _unavailable("Native cluster/selector metadata not retained.")
    counts = {k: source[k] for k in ("cluster_size", "neighbor_count", "seed_consensus_count",
                                    "top_trials", "feasible_trials") if k in source}
    reasons = source.get("fallback_reasons")
    for value in counts.values():
        _require(type(value) is int and value >= 0, "NATIVE_CLUSTER_COUNT")
    _require(reasons is None or isinstance(reasons, (tuple, list)), "NATIVE_FALLBACK_FORMAT")
    selector, reason = source.get("selector"), source.get("reason")
    _require(selector is None or isinstance(selector, str), "NATIVE_SELECTOR_FORMAT")
    _require(reason is None or isinstance(reason, str), "NATIVE_REASON_FORMAT")
    known_selector = selector if selector in {"medoid", "fallback_best_is_temporal"} else None
    known_reason_codes = {"no_dense_train_plateau", "no_candidate_met_neighbor_or_seed_consensus"}
    known_reason = reason if reason in known_reason_codes else None
    retained_reasons = list(reasons or ())
    if reason is not None and reason not in retained_reasons:
        retained_reasons.append(reason)
    if known_selector == "medoid":
        _require(not reasons and known_reason is None, "NATIVE_FALLBACK_CONFLICT")
        occurred = False
    elif known_selector == "fallback_best_is_temporal" or known_reason is not None:
        occurred = True
    else:
        occurred = bool(reasons) if reasons is not None else None
    fallback = (_unavailable("No recognized native fallback disposition retained.") if occurred is None else
        dict(status="SOURCE_BOUND", occurred=occurred, count=len(retained_reasons),
             reasons_digest=digest(retained_reasons),
             known_reasons=[r for r in retained_reasons if isinstance(r, str) and r in known_reason_codes],
             other_reason_count=sum(not isinstance(r, str) or r not in known_reason_codes for r in retained_reasons)))
    return dict(status="SOURCE_BOUND", pointer="/record/native_selection_reason",
        metadata_digest=digest(source), cluster_counts=counts, selector=known_selector, reason=known_reason,
        cluster_status="RETAINED" if {"cluster_size", "neighbor_count"} & counts.keys() else "UNAVAILABLE",
        fallback=fallback,
        interpretation="Observed native support, not independent plateau volume or local fragility.")


def _position(task, schema, geometry, observations, selected):
    candidates = {c.evaluation_id: c for c in task.candidates}
    points = {r.evaluation_id: r.point for r in observations}
    anchor = task.anchor_candidate_evaluation_id
    pair = (candidates[anchor], candidates[selected])
    coords = schema.parameter_geometry(pair)
    positions = {}
    measured = [c.observation.raw_sharpe for c in task.candidates
                if c.observation.status == OutcomeStatus.VALID and c.observation.raw_sharpe is not None]
    for name, eid in (("anchor", anchor), ("selected", selected)):
        observation = candidates[eid].observation
        value = observation.raw_sharpe if observation.status == OutcomeStatus.VALID else None
        positions[name] = dict(measured_pool=len(measured),
            strictly_higher_is=sum(x > value for x in measured) if value is not None else None,
            equal_is=sum(x == value for x in measured) if value is not None else None,
            active_dimensions=len(points[eid].active_names))
    return dict(same_evaluation_id=anchor == selected,
        same_effective_params=points[anchor].identity == points[selected].identity,
        selector_anchor_distance=float(np.linalg.norm(coords[1] - coords[0])),
        shared_gower_distance=geometry.distance(points[anchor], points[selected]),
        positions=positions, coordinates="REDACTED")


def _ridge(task, schema, decision, model, previous):
    if model is None:
        return dict(status="NO_RETAINED_MODEL", reason=decision.status), None
    batch = schema.encode(task.candidates)
    scaler = OriginBalancedStandardizer(**dict(model.scaler))
    scaled, unsupported = scaler.transform(batch)
    beta = np.asarray(model.coefficients)
    names = [name if name in {"raw_is_sharpe", "log1p_is_activity"} else f"feature_{i:03d}"
             for i, name in enumerate(schema.feature_names)]
    valid = batch.valid & np.array([c.observation.verification != "unverified" for c in task.candidates])
    index = {c.evaluation_id: i for i, c in enumerate(task.candidates)}
    ai = index[task.anchor_candidate_evaluation_id]
    ood = unsupported & valid
    features = []
    for j, name in enumerate(names):
        mask = batch.active[:, j] & valid
        violation = mask & scaler.constant[j] & (
            ~scaler.observed[j] | (np.abs(batch.values[:, j] - scaler.mean[j]) > scaler.constant_tolerance))
        features.append(dict(feature=name, historically_constant=bool(scaler.constant[j]),
            historical_numeric_observed=bool(scaler.observed[j]) if j in schema.numeric_columns else None,
            current_active_valid=int(mask.sum()), constant_support_violations=int(violation.sum())))
    predictions = {p["evaluation_id"]: p for p in decision.predictions}
    _require(set(predictions) <= set(index), "PREDICTION_ROSTER")
    if decision.status == "META_MODEL_PROPOSAL":
        _require(set(predictions) == set(index) and not ood.any() and valid[ai], "SERVED_SUPPORT")
    served = []
    for eid, p in predictions.items():
        i = index[eid]
        _require(p["raw_is"] == task.candidates[i].observation.raw_sharpe, "PREDICTION_IS")
        if p["yhat"] is None:
            _require(decision.status != "META_MODEL_PROPOSAL" or not valid[i], "MISSING_VALID_SCORE")
            continue
        _require(decision.status == "META_MODEL_PROPOSAL" and valid[i] and not ood[i], "UNSERVED_SCORE")
        y = float(np.dot(scaled[i] - scaled[ai], beta))
        delta = task.candidates[i].observation.raw_sharpe - task.anchor.observation.raw_sharpe
        q = delta - y
        coords = schema.parameter_geometry((task.anchor, task.candidates[i]))
        tolerance = dict(rtol=model.numeric_limits.parity_rtol, atol=model.numeric_limits.parity_atol)
        _require(np.isclose(y, p["yhat"], **tolerance) and
                 np.isclose(q, p["qhat"], **tolerance) and
                 np.isclose(np.linalg.norm(coords[1] - coords[0]), p["distance"], **tolerance),
                 "SERVED_PREDICTION_MISMATCH")
        _require(p["candidate_id"] == task.candidates[i].candidate_id and
                 p["eligible"] == (p["qhat"] >= -model.settings.epsilon), "SERVED_GUARD")
        served.append(p)
    targets = {}
    actual = decision.actual_evaluation_id or decision.proposed_evaluation_id
    for role, eid in (("anchor", task.anchor_candidate_evaluation_id), ("selected", actual)):
        p = predictions.get(eid)
        if p is None or p["yhat"] is None:
            targets[role] = dict(status="NOT_SERVED", reason=decision.status, contributions=None)
            continue
        i = index[eid]
        terms = (scaled[i] - scaled[ai]) * beta
        is_j = schema.feature_names.index("raw_is_sharpe")
        activity = schema.feature_names.index("log1p_is_activity") if schema.include_activity else None
        delta = task.candidates[i].observation.raw_sharpe - task.anchor.observation.raw_sharpe
        targets[role] = dict(status="EXACT_SERVED_STANDARDIZED_CONTRAST", yhat=p["yhat"], qhat=p["qhat"],
            contributions=[dict(feature=n, yhat_contribution=float(v)) for n, v in zip(names, terms)],
            contribution_sum=float(terms.sum()), delta_is=float(delta),
            served_yhat_minus_contribution_sum=float(p["yhat"] - terms.sum()),
            raw_is_yhat_contribution=float(terms[is_j]),
            raw_is_qhat_contribution=float(delta - terms[is_j]),
            activity_yhat_contribution=float(terms[activity]) if activity is not None else None,
            other_qhat_contribution=float(-(terms.sum() - terms[is_j])),
            raw_is_absolute_contribution_share=(float(abs(terms[is_j]) / np.abs(terms).sum())
                                                if np.abs(terms).sum() else None))
    stability = (_unavailable("No earlier retained model at this prefix.") if previous is None else
        dict(status="DESCRIPTIVE_STANDARDIZED_BASIS", previous_fold=previous[0],
             l2_change=float(np.linalg.norm(beta - previous[1])),
             sign_changes=int(np.count_nonzero(np.sign(beta) != np.sign(previous[1]))),
             interpretation="Vintage scaler changes preclude a causal importance interpretation."))
    result = dict(status="RETAINED_MODEL", model_id=model.model_id,
        origin_count=model.origin_count, features=features, descriptor_valid=int(valid.sum()),
        descriptor_invalid=int((~valid).sum()), ood_valid_candidates=int(ood.sum()),
        whole_pool_ood_fallback=bool(ood.any()), selection_status=decision.status,
        served_candidates=len(served), targets=targets, coefficient_stability=stability,
        score_distributions={k: (dict(minimum=min(p[k] for p in served), maximum=max(p[k] for p in served),
                                    median=float(np.median([p[k] for p in served]))) if served else None)
                             for k in ("yhat", "qhat")},
        interpretation="Exact served arithmetic, not causal importance or a leakage test; IS is in the target.")
    return result, beta


def monthly_diagnostics(corpus):
    """Return all 57 prefix rows and chronology-fixed deep checks, JSON ready.

    No corpus discovery, fitting, optimizer, financial execution or evidence
    writes occur here. Hash-bound files already admitted by Corpus are rechecked.
    Optional paths/probes cannot be inferred from aggregate Sharpe observations.
    """
    _require(isinstance(corpus, Corpus) and len(corpus.revisions) == len(corpus.selections) == 57,
             "MONTHLY_57_ROSTER_REQUIRED")
    rows, deep, first_mature, previous = [], [], None, None
    for fold, revision in enumerate(corpus.revisions):
        task = revision.task
        _require(task.family.descriptor_schema_id == corpus.schema.schema_id, "DESCRIPTOR_SCHEMA")
        if fold:
            _require(corpus.revisions[fold - 1].task.origin < task.origin, "ORIGIN_ORDER")
            _require(task.family == corpus.revisions[0].task.family, "MIXED_FAMILY")
        saved, source = _source(corpus, fold)
        snapshot, decision, model = _retained(corpus, fold, saved)
        geometry, observations, report = _shared(corpus, task)
        ridge, beta = _ridge(task, corpus.schema, decision, model, previous)
        if model is not None and first_mature is None:
            first_mature = fold
        selected = saved["record"]["selected_evaluation_id"]
        row = dict(fold=fold, origin=task.origin.isoformat(), cutoff=task.data_cutoff.isoformat(),
            role="acquisition" if fold < 13 else "development" if fold < 25 else "evaluation",
            source=source, snapshot_id=snapshot.snapshot_id, matured_origins=snapshot.origin_count,
            coverage=_coverage(task, observations, report), activity=report["activity"],
            associations=report["associations"], native=_native(saved["record"]),
            sampler_compatibility=[dict(recipe_id=item["recipe_id"], compatible=item["compatible"],
                reason=("Shared schema preflight passed; performance is unmeasured." if item["compatible"] else
                        "Shared schema preflight rejected; private geometry details redacted."),
                dependency_checked=item["dependency_checked"], empirical_superiority=item["empirical_superiority"])
                for item in report["sampler_compatibility"]],
            position=_position(task, corpus.schema, geometry, observations, selected),
            ridge=ridge, shared_report_id=report["report_id"],
            access=dict(policy_id=report["access_policy_id"], cutoff_ns=report["cutoff_ns"],
                        witnesses=report["source_witnesses"],
                        readiness="IS input frontier; computation/sealing checked separately"))
        # Shared exports include caller-owned identifiers; retain only opaque refs.
        row["activity"] = dict(row["activity"], definition="retained_metric_contract:" + digest(task.family.metric_contract_id))
        row["access"]["witnesses"] = [dict(w, manifest_id=digest(w["manifest_id"]))
                                         for w in row["access"]["witnesses"]]
        rows.append(row)
        if fold in {first_mature, 40, 56}:
            deep.append(dict(fold=fold, checkpoint="first_actually_mature" if fold == first_mature else f"fold_{fold}",
                source=source, snapshot_id=snapshot.snapshot_id, ridge=ridge,
                coverage=row["coverage"], activity=row["activity"], native=row["native"],
                position=row["position"], associations=row["associations"],
                sampler_compatibility=row["sampler_compatibility"],
                local_probes=_unavailable("No prefix-authorized structured local probe catalog supplied by Corpus."),
                continuous_is_environment=_unavailable("No authorized continuous-IS return path/attribution supplied by Corpus."),
                episodes=_unavailable("No source-bound prefix episode evidence supplied by Corpus."),
                x2=_unavailable("Corpus retains Ridge only; existing X2 diagnostics belong to the parent analysis.")))
        if beta is not None:
            previous = (fold, beta)
    result = dict(schema=VERSION, group=corpus.group, stratum="original_monthly_730D",
        folds=57, rows=rows, deep_checks=deep, first_actually_mature_fold=first_mature,
        maturity_status="OBSERVED_RETAINED_MATURE_MODEL" if first_mature is not None else "NO_RETAINED_MATURE_MODEL",
        interpretation="Prefix-authorized observed associations/hypotheses, not causal explanations or new model features.",
        limitations=["Adaptive TPE coverage is not a neutral-design sensitivity or independent plateau-volume estimate.",
                     "No current forward observations or later full-development report supply earlier inputs.",
                     "Trial budget and eligible pool size do not certify actual optimizer dispositions.",
                     "Optional local/environment paths are unavailable, not neutral scores."],
        model_fits=0, optimizer_proposals=0, financial_calls=0, new_features=0)
    # Validate strict JSON, including any producer-supplied numeric metadata.
    canonical(result)
    return result
