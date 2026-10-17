"""Cold decision-level R/Q, downside and witnessed-panel analysis."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd

from quantbt.optimization.meta_selection.common import digest, wire
from .admission import load_corpus, pin, read, save_new
from .decision_policy import POLICIES
from .decision_value import verify_inputs
from .protocol import GROUPS
from .replay import persist_gzip


def raw_effect(ia, iw, oa, ow):
    if not all(
        isinstance(v, (int, float)) and np.isfinite(v) for v in (ia, iw, oa, ow)
    ):
        raise ValueError("finite raw Sharpe required")
    r = (ia - oa) - (iw - ow)
    q = ow - oa
    effect = ia - iw
    if not np.isclose(r, effect + q, rtol=1e-12, atol=1e-12):
        raise ValueError("R/Q accounting identity")
    return dict(
        R=r,
        Q=q,
        IS_contribution=effect,
        anchor_is=ia,
        selected_is=iw,
        anchor_forward=oa,
        selected_forward=ow,
    )


def worst_fraction(values, fraction=0.2):
    if not 0 < fraction <= 1:
        raise ValueError("tail mass")
    ordered = np.sort(np.asarray(values, dtype=float))
    if not len(ordered) or not np.isfinite(ordered).all():
        raise ValueError("finite nonempty tail")
    mass = len(ordered) * fraction
    full = int(mass)
    return float(
        (ordered[:full].sum() + (mass - full) * ordered[min(full, len(ordered) - 1)])
        / mass
    )


def summarize(rows):
    """Missing metrics retain a count; their values never enter a mean as zero."""
    observed = [r for r in rows if r["measurement_status"] == "VALID"]
    changed = [r for r in rows if r["changed_effective"]]
    valid_changed = [r for r in observed if r["changed_effective"]]
    result = dict(
        origins=len(rows),
        model_ready=sum(r["model_status"] == "META_MODEL_PROPOSAL" for r in rows),
        changed_ids=sum(r["changed_id"] for r in rows),
        changed_effective=len(changed),
        observed=len(observed),
        missing_or_undefined=len(rows) - len(observed),
        missing_statuses=dict(
            Counter(
                r["measurement_status"]
                for r in rows
                if r["measurement_status"] != "VALID"
            )
        ),
        changed_observed=len(valid_changed),
        changed_unknown=len(changed) - len(valid_changed),
        helped=sum(r["effect"]["Q"] > 0 for r in observed),
        hurt=sum(r["effect"]["Q"] < 0 for r in observed),
        tied=sum(r["effect"]["Q"] == 0 for r in observed),
        effect_definition="help/harm by Q sign, not R sign; no economic threshold",
    )
    for name, data in (("all_observed", observed), ("changed_observed", valid_changed)):
        if not data:
            result[name] = None
            continue
        q = np.array([r["effect"]["Q"] for r in data])
        negative = q[q < 0]
        result[name] = dict(
            mean_R=float(np.mean([r["effect"]["R"] for r in data])),
            mean_Q=float(q.mean()),
            mean_IS=float(np.mean([r["effect"]["IS_contribution"] for r in data])),
            median_R=float(np.median([r["effect"]["R"] for r in data])),
            median_Q=float(np.median(q)),
            worst_Q=float(q.min()),
            mean_negative_Q=float(negative.mean()) if len(negative) else None,
            negative_Q_magnitude=float(-negative.sum()),
            positive_Q_magnitude=float(q[q > 0].sum()),
            mean_worst_20pct_Q=worst_fraction(q) if len(q) >= 10 else None,
            worst_20pct_status="DEFINED" if len(q) >= 10 else "INSUFFICIENT_FOLDS",
            n=len(data),
            month_list=[r["month"] for r in data],
        )
    predicted = [
        r
        for r in observed
        if r.get("selected_prediction") is not None
        and r["selected_prediction"].get("qhat") is not None
        and r["model_status"] == "META_MODEL_PROPOSAL"
    ]
    result["guard"] = dict(
        observed_predictions=len(predicted),
        accepted_realized_Q_negative=sum(r["effect"]["Q"] < 0 for r in predicted),
        accepted_realized_Q_below_minus_0_1=sum(
            r["effect"]["Q"] < -0.1 for r in predicted
        ),
        prediction_bias_Q=float(
            np.mean(
                [r["selected_prediction"]["qhat"] - r["effect"]["Q"] for r in predicted]
            )
        )
        if predicted
        else None,
        note="selected accepted candidates, conditional on observed defined Q; excludes missing values",
    )
    loss_rows = [
        r["acquired_label_loss"]
        for r in rows
        if r.get("acquired_label_loss", {}).get("mse") is not None
    ]
    errors = [
        r["selected_y_squared_error"]
        for r in valid_changed
        if "selected_y_squared_error" in r
    ]
    result["prediction_loss"] = dict(
        acquired_origin_macro_mse=float(np.mean([r["mse"] for r in loss_rows]))
        if loss_rows
        else None,
        acquired_supported_origins=len(loss_rows),
        acquired_labels=sum(r["n"] for r in loss_rows),
        changed_selected_mse=float(np.mean(errors)) if errors else None,
        changed_selected_observed=len(errors),
        interpretation="different acquired versus selected masks; no average-loss to policy-value equivalence",
    )
    return result


def paired(rows, treatment, comparator):
    lookup = {(r["fold"], r["policy"]): r for r in rows}
    data = []
    for fold in range(25, 57):
        a, b = lookup[fold, treatment], lookup[fold, comparator]
        valid = a["measurement_status"] == b["measurement_status"] == "VALID"
        data.append(
            dict(
                fold=fold,
                month=a["month"],
                valid=valid,
                deltaR=a["effect"]["R"] - b["effect"]["R"] if valid else None,
                deltaQ=a["effect"]["Q"] - b["effect"]["Q"] if valid else None,
                deltaIS=a["effect"]["IS_contribution"] - b["effect"]["IS_contribution"]
                if valid
                else None,
                changed=a["params_digest"] != b["params_digest"],
            )
        )
    usable = [r for r in data if r["valid"]]
    return dict(
        treatment=treatment,
        comparator=comparator,
        rows=data,
        observed=len(usable),
        mean_deltaR=float(np.mean([r["deltaR"] for r in usable])) if usable else None,
        mean_deltaQ=float(np.mean([r["deltaQ"] for r in usable])) if usable else None,
        mean_deltaIS=float(np.mean([r["deltaIS"] for r in usable])) if usable else None,
        helped=sum(r["deltaQ"] > 0 for r in usable),
        hurt=sum(r["deltaQ"] < 0 for r in usable),
        tied=sum(r["deltaQ"] == 0 for r in usable),
        changed=sum(r["changed"] for r in data),
    )


def block_intervals(contrasts):
    """One shared chronological block draw stream, fixed 16-coordinate divisor."""
    rng = np.random.default_rng(731)
    starts = rng.integers(0, 30, size=(16384, 11))
    indices = (starts[:, :, None] + np.arange(3)).reshape(16384, 33)[:, :32]
    outputs = {}
    for name, contrast in contrasts.items():
        if [r["month"] for r in contrast["rows"]] != [
            str(m) for m in pd.period_range("2024-02", "2026-09", freq="M")
        ]:
            raise ValueError("contrast calendar differs from sealed 32 months")
        complete = len(contrast["rows"]) == 32 and all(
            r["valid"] for r in contrast["rows"]
        )
        out = dict(
            status="DEFINED_EXPLORATORY"
            if complete
            else "INCONCLUSIVE_INCOMPLETE_CALENDAR",
            observed=contrast["observed"],
            calendar_months=32,
            coordinates=16,
        )
        if complete:
            for metric in ("deltaR", "deltaQ"):
                a = np.array([r[metric] for r in contrast["rows"]])
                draws = a[indices].mean(axis=1)
                lo, hi = np.quantile(draws, [0.05 / 32, 1 - 0.05 / 32])
                out[metric] = dict(
                    mean=float(a.mean()), lower=float(lo), upper=float(hi)
                )
        outputs[name] = out
    return outputs


def measure(revision, winner, extra):
    candidates = {c.evaluation_id: c for c in revision.task.candidates}
    anchor = revision.task.anchor_candidate_evaluation_id
    outcomes = {o.evaluation_id: wire(o.observation) for o in revision.outcomes}
    if winner not in outcomes and winner in extra:
        outcomes[winner] = extra[winner]["observation"]
    obs = [wire(candidates[e].observation) for e in (anchor, winner)]
    obs += [outcomes.get(e) for e in (anchor, winner)]
    statuses = ["MISSING_EXECUTION" if o is None else o["status"] for o in obs]
    if statuses != ["VALID"] * 4:
        return dict(
            measurement_status=";".join(
                f"{i}:{s}" for i, s in enumerate(statuses) if s != "VALID"
            ),
            effect=None,
        )
    return dict(
        measurement_status="VALID", effect=raw_effect(*(o["raw_sharpe"] for o in obs))
    )


def opportunity(revision, winner, predictions, *, floor=-0.1):
    task = revision.task
    anchor = task.anchor_candidate_evaluation_id
    outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
    fixed = set(revision.panel.base_members) | {anchor}
    valid = {
        eid: o.raw_sharpe
        for eid, o in outcomes.items()
        if eid in fixed and o.status.value == "VALID"
    }
    anchor_o = outcomes.get(anchor)
    if not valid or anchor_o is None or anchor_o.status.value != "VALID":
        return dict(
            status="UNDEFINED_FIXED_PANEL", valid=len(valid), members=len(fixed)
        )
    best = max(valid, key=lambda e: (valid[e], e))
    p = {p["evaluation_id"]: p for p in predictions}
    passed = [
        v
        for e, v in valid.items()
        if e in p and p[e].get("qhat") is not None and p[e]["qhat"] >= floor
    ]
    return dict(
        status="OBSERVED_FIXED_BASE_PANEL",
        valid=len(valid),
        members=len(fixed),
        best_forward=valid[best],
        anchor_forward=anchor_o.raw_sharpe,
        best_vs_anchor=valid[best] - anchor_o.raw_sharpe,
        best_id=best,
        winner_preexisting_forward=outcomes[winner].raw_sharpe
        if winner in outcomes and outcomes[winner].status.value == "VALID"
        else None,
        best_excluded_by_Q=best in p
        and p[best].get("qhat") is not None
        and p[best]["qhat"] < floor,
        best_passing_forward=max(passed) if passed else None,
        q_floor=floor,
        interpretation="finite preexisting acquisition panel; not full-pool oracle; new queried winners excluded",
    )


def analyze(output):
    verify_inputs(output)
    cpu, wall = time.process_time(), time.perf_counter()
    source = pin(Path(__file__))
    sources = [source, pin(Path(__file__).with_name("decision_policy.py"))]
    save_new(
        output / "analysis-registration.json",
        dict(
            schema="m4.ml06.analysis-registration.v1",
            source_pins=sources,
            seal=pin(output / "sealed.json"),
            inference="16 fixed R-N/X-R coordinates; complete32 months; shared moving blocks3; draws16384; seed731; Bonferroni family95",
            all_new_comparisons="exploratory_reviewed_data",
            runtime_only=False,
        ),
    )
    sealed = read(output / "sealed.json")
    queries = [read(p) for p in sorted((output / "queries").glob("*.json"))]
    inputs = [pin(output / "sealed.json")] + [
        pin(p) for p in sorted((output / "queries").glob("*.json"))
    ]
    groups = {}
    ledgers = []
    primary = {}
    for group in GROUPS:
        corpus = load_corpus(group)
        xpreds = {
            r["fold"]: r["predictions"]
            for r in read(output / f"{group}-x-predictions.json.gz")
        }
        query = {
            (r["request"]["fold"], r["request"]["winner"]): r
            for r in queries
            if r["request"]["group"] == group
        }
        rows = []
        for original in sealed["rows"]:
            if original["group"] != group:
                continue
            row = dict(original)
            fold = row["fold"]
            revision = corpus.revisions[fold]
            p = (
                xpreds[fold]
                if row["policy"] == "X"
                else (corpus.selections[fold]["record"]["proposal"] or {}).get(
                    "predictions", []
                )
            )
            selected = next((t for t in p if t["evaluation_id"] == row["winner"]), None)
            row["selected_prediction"] = (
                None
                if selected is None
                else {k: selected[k] for k in ("yhat", "qhat", "distance")}
            )
            extra = {eid: v for (f, eid), v in query.items() if f == fold}
            row.update(measure(revision, row["winner"], extra))
            if (
                row["measurement_status"] == "VALID"
                and selected is not None
                and selected["yhat"] is not None
            ):
                row["selected_y_squared_error"] = (
                    selected["yhat"] + row["effect"]["R"]
                ) ** 2
                row["selected_q_error"] = selected["qhat"] - row["effect"]["Q"]
            if row["policy"] in ("R", "X"):
                scores = {v["evaluation_id"]: v for v in p if v["yhat"] is not None}
                labels = {
                    r.candidate_evaluation_id: r.y
                    for r in revision.training_rows
                    if r.candidate_evaluation_id
                    != revision.task.anchor_candidate_evaluation_id
                }
                ids = sorted(set(scores) & set(labels))
                row["acquired_label_loss"] = dict(
                    n=len(ids),
                    mse=float(
                        np.mean([(scores[e]["yhat"] - labels[e]) ** 2 for e in ids])
                    )
                    if ids
                    else None,
                    scored_ids_digest=digest(ids),
                )
            if fold >= 25:
                row["opportunity"] = opportunity(
                    revision,
                    row["winner"],
                    p,
                    floor=0.0 if row["policy"] == "G" else -0.1,
                )
            rows.append(row)
        evaluation = [r for r in rows if r["fold"] >= 25]
        summaries = {
            p: summarize([r for r in evaluation if r["policy"] == p]) for p in POLICIES
        }
        contrasts = {
            f"{a}-{b}": paired(evaluation, a, b)
            for a, b in (("R", "N"), ("X", "R"), ("G", "R"), ("F", "R"))
        }
        for name in ("R-N", "X-R"):
            primary[f"{group}/{name}"] = contrasts[name]
        groups[group] = dict(
            policies=summaries,
            contrasts=contrasts,
            acquisition_development_statuses=dict(
                Counter(r["measurement_status"] for r in rows if r["fold"] < 25)
            ),
            original_N_R_custody="verified 57 per alpha; all new policy comparisons fixed logged history",
        )
        ledgers += rows
    intervals = block_intervals(primary)
    macro = {}
    for contrast_name in ("R-N", "X-R", "G-R", "F-R"):
        common = [
            i
            for i in range(32)
            if all(
                groups[g]["contrasts"][contrast_name]["rows"][i]["valid"]
                for g in GROUPS
            )
        ]
        macro[contrast_name] = dict(
            common_months=len(common),
            months=[
                groups[GROUPS[0]]["contrasts"][contrast_name]["rows"][i]["month"]
                for i in common
            ],
            mean_deltaR=float(
                np.mean(
                    [
                        groups[g]["contrasts"][contrast_name]["rows"][i]["deltaR"]
                        for g in GROUPS
                        for i in common
                    ]
                )
            )
            if common
            else None,
            mean_deltaQ=float(
                np.mean(
                    [
                        groups[g]["contrasts"][contrast_name]["rows"][i]["deltaQ"]
                        for g in GROUPS
                        for i in common
                    ]
                )
            )
            if common
            else None,
            interpretation="equal origin then equal alpha on explicit common valid calendar only; descriptive",
        )
    if any(pin(ref["path"]) != ref for ref in sources + inputs):
        raise ValueError("analysis inputs/source changed")
    persist_gzip(output / "measured-decisions.json.gz", ledgers)
    result = dict(
        schema="m4.ml06.decision-analysis.v1",
        status="COMPLETE_ANALYSIS_WITH_EXPLICIT_SUPPORT",
        groups=groups,
        intervals=intervals,
        common_calendar_macro=macro,
        inputs=inputs,
        source_pins=sources,
        ledger=pin(output / "measured-decisions.json.gz"),
        query_count=len(queries),
        evaluation_rows=sum(r["fold"] >= 25 for r in ledgers),
        cpu_seconds=time.process_time() - cpu,
        wall_seconds=time.perf_counter() - wall,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        new_optimizer_proposals=0,
        new_financial_calls=0,
        new_fits=0,
        scope="conditional_logged_history_exploratory_not_self_consistent_policy_rollout",
    )
    return save_new(output / "analysis.json", result)
