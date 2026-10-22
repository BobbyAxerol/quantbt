"""Cold source-bound auxiliary evidence and sanitized decision report."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import resource
import time

import numpy as np

from .admission import PUBLIC, pin, read, save_new, load_corpus
from .decision_diagnostics import monthly_diagnostics
from .decision_inventory import search_inventory
from .decision_value import verify_inputs
from .protocol import GROUPS


def auxiliary(output):
    verify_inputs(output)
    cpu, wall = time.process_time(), time.perf_counter()
    sources = [
        pin(Path(__file__)),
        pin(Path(__file__).with_name("decision_diagnostics.py")),
        pin(Path(__file__).with_name("decision_inventory.py")),
    ]
    save_new(
        output / "diagnostics-02-registration.json",
        dict(
            schema="m4.ml06.diagnostics-registration.v1",
            source_pins=sources,
            scope="all57 IS prefixes; source-bound saved models; no new financial/fitting work",
        ),
    )
    inventory = search_inventory()
    save_new(output / "search-inventory.json", inventory)
    rows = {}
    for group in GROUPS:
        rows[group] = monthly_diagnostics(load_corpus(group))
    if any(pin(p["path"]) != p for p in sources):
        raise ValueError("diagnostic source changed")
    return save_new(
        output / "diagnostics.json",
        dict(
            schema="m4.ml06.diagnostics.v1",
            groups=rows,
            inventory=pin(output / "search-inventory.json"),
            source_pins=sources,
            cpu_seconds=time.process_time() - cpu,
            wall_seconds=time.perf_counter() - wall,
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            new_fits=0,
            new_financial_calls=0,
            new_optimizer_proposals=0,
        ),
    )


def number(value):
    return "N/A" if value is None else f"{value:+.4f}"


def card(group, analysis, diagnostics, inventory, quarterly):
    policies = analysis["policies"]
    r = policies["R"]["all_observed"]
    contrasts = analysis["contrasts"]
    if r is None or policies["R"]["observed"] < 12:
        leading = "INCONCLUSIVE_WITH_EXACT_GAP"
        rationale = "Too few defined paired monthly outcomes for a broad effect; inspect inactivity/support first."
        next_test = "A fixed prefix activity/opportunity study; retain valid flat episodes and no-trade uncertainty."
    elif r["mean_Q"] < 0:
        leading = "ANCHOR_RETENTION_OR_GUARD_STUDY"
        rationale = "Positive decay can coexist with worse forward; inspect changed decisions and guard calibration."
        next_test = "Compare one preregistered retention/guard or Q-ranking procedure on a genuinely reserved period."
    else:
        leading = "KEEP_RIDGE_RESEARCH"
        rationale = "Observed mean forward Q is nonnegative; distinguish point benefit from supported uncertainty."
        next_test = "Retain frozen Ridge as comparator; seek reserved chronology before any global policy change."
    points = [
        row["ridge"]["targets"]["selected"]
        for row in diagnostics["rows"]
        if row["fold"] >= 25
        and row["ridge"].get("targets", {}).get("selected", {}).get("status")
        == "EXACT_SERVED_STANDARDIZED_CONTRAST"
    ]
    shares = [
        p["raw_is_absolute_contribution_share"]
        for p in points
        if p["raw_is_absolute_contribution_share"] is not None
    ]
    return dict(
        group=group,
        leading_next_action=leading,
        rationale=rationale,
        mean_R=None if r is None else r["mean_R"],
        mean_Q=None if r is None else r["mean_Q"],
        observed_R_N=policies["R"]["observed"],
        eligible=32,
        G_minus_R=contrasts["G-R"]["mean_deltaQ"],
        F_minus_R=contrasts["F-R"]["mean_deltaQ"],
        X_minus_R=contrasts["X-R"]["mean_deltaQ"],
        raw_IS_absolute_contribution_share_median=float(np.median(shares))
        if shares
        else None,
        native_selector_counts=inventory["native_selector_counts"],
        sampler_compatibility=diagnostics["deep_checks"][-1].get(
            "sampler_compatibility"
        ),
        sampler_observed_response=quarterly["advisory"]["measured_response"],
        competing_explanation="Shared market, acquired-label selection, changing scaler/support and outcome missingness; contributions are not causal importance.",
        exact_next_test=next_test,
        incremental_cost="No new run approved; quote targeted witness count and pilot cost before a new study.",
        deployment_change=False,
    )


def build_summary(output):
    a, d, q, s = [
        read(output / n)
        for n in (
            "analysis.json",
            "diagnostics.json",
            "quarterly.json",
            "search-inventory.json",
        )
    ]
    seal, controls = read(output / "sealed.json"), read(output / "controls.json")
    pilot, remaining = [
        read(output / f"queries-{stage}-result.json")
        for stage in ("pilot", "remaining")
    ]
    ledger = read(output / "measured-decisions.json.gz")
    groups = {}
    for group in GROUPS:
        g = a["groups"][group]
        examples = [
            r
            for r in ledger
            if r["group"] == group
            and r["fold"] >= 25
            and r["policy"] == "R"
            and r["measurement_status"] == "VALID"
            and r["changed_effective"]
        ]
        worst = sorted(examples, key=lambda r: r["effect"]["Q"])[:3]
        opportunities = {}
        for policy in ("R", "X", "G", "F"):
            supported = [
                r
                for r in ledger
                if r["group"] == group
                and r["fold"] >= 25
                and r["policy"] == policy
                and r["measurement_status"] == "VALID"
                and r.get("opportunity", {}).get("status")
                == "OBSERVED_FIXED_BASE_PANEL"
            ]
            gaps = [
                r["opportunity"]["best_forward"] - r["effect"]["selected_forward"]
                for r in supported
            ]
            opportunities[policy] = dict(
                supported=len(supported),
                eligible=32,
                observed_better_base_candidate=sum(v > 0 for v in gaps),
                mean_positive_headroom=float(np.mean([max(0.0, v) for v in gaps]))
                if gaps
                else None,
                best_excluded_by_guard=sum(
                    v > 0 and r["opportunity"]["best_excluded_by_Q"]
                    for r, v in zip(supported, gaps)
                ),
                ranking_miss_within_guard=sum(
                    r["opportunity"]["best_passing_forward"] is not None
                    and r["opportunity"]["best_passing_forward"]
                    > r["effect"]["selected_forward"]
                    for r in supported
                ),
                interpretation="positive witnessed base-panel headroom over selected; includes zero gaps; not full-pool regret",
            )
        groups[group] = dict(
            policies=g["policies"],
            contrasts=g["contrasts"],
            worst_R_changed_decisions=[
                {k: r[k] for k in ("month", "effect", "selected_prediction")}
                for r in worst
            ],
            checkpoints=d["groups"][group]["deep_checks"],
            search=s["groups"][group],
            quarterly=q["groups"][group],
            observed_opportunity=opportunities,
            decision=card(
                group, g, d["groups"][group], s["groups"][group], q["groups"][group]
            ),
        )
    requests = read(output / "query-roster.json")
    quotes = [read(p) for p in (output / "queries").glob("*.json")]
    # Family numeric charge already includes the shared runtime qualification.
    work = dict(
        logical_fits=seal["new_learner_fits"] + controls["logical_fits"],
        numeric_reference_qualification_charge=seal["regression_numeric_charge"]
        + controls["family_bill"]["numeric_charge"]
        + controls["ridge_bill"]["regression_fit_charge"],
        new_optimizer_proposals=0,
        financial_calls=len(quotes),
        financial_query_cpu_seconds=sum(r["cpu_seconds"] for r in quotes),
        financial_stage_cpu_seconds=pilot["cpu_seconds"] + remaining["cpu_seconds"],
        financial_stage_wall_seconds=pilot["wall_seconds"] + remaining["wall_seconds"],
        cold_measured_cpu_seconds=sum(
            r.get("cpu_seconds", 0) for r in (seal, controls, a, d, q)
        ),
        query_peak_process_rss_mib=max(r["peak_rss_mib"] for r in quotes),
        setup_failed_before_finance=1,
        failed_setup_cpu_seconds=None,
        timing_limitation="First native-path setup error was not timed; source-binary correction precedes all finance. Measured work excludes this failed startup.",
        queries_queued=requests["queued"],
        queries_admitted=len(requests["admitted"]),
        missing_outside_budget=len(requests["not_admitted"]),
        outside_budget_by_policy=dict(
            Counter(r["policy"] for r in requests["not_admitted"])
        ),
        query_observation_statuses=dict(
            Counter(r["observation"]["status"] for r in quotes)
        ),
    )
    return dict(
        schema="m4.ml06.public-decision-value.v1",
        technical_status="PASS_BOUNDED_REGISTERED_SCOPE",
        economic_status="EXPLORATORY_HETEROGENEOUS_NO_DEFAULT_PROMOTION",
        groups=groups,
        intervals=a["intervals"],
        common_calendar_macro=a["common_calendar_macro"],
        work=work,
        baseline_retention=dict(
            native=seal["counts"]["saved_native"],
            ridge=seal["counts"]["saved_ridge"],
            zero_scored_checks=sum(
                r["status"] == "CHECKED" for r in seal["zero_controls"]
            ),
            zero_nonanchor_effective=sum(
                r.get("same_effective_params") is False for r in seal["zero_controls"]
            ),
        ),
        prior_acquisition_sensitivity=read(PUBLIC / "ml05_zero_summary.json")["panels"],
        input_hashes={
            n: {k: pin(output / n)[k] for k in ("sha256", "bytes")}
            for n in (
                "registration.json",
                "sealed.json",
                "controls.json",
                "analysis.json",
                "diagnostics.json",
                "quarterly.json",
            )
        },
        methodology="Fixed original monthly/730D, logged union history, unchanged accounts; all new comparisons reviewed/exploratory.",
        common_next_action="Keep V1 available; prioritize selection/guard and prefix support explanations before a larger model search.",
        limitations=[
            "No replacement-policy label-acquisition rollout or continuous X/G/F account was executed.",
            "No independent untouched OOS or universal model/sampler superiority is claimed.",
            "G/F are fixed research ablations; no production default or feature profile changed.",
            "No-variance outcomes remain undefined; finite-panel headroom is not full-pool regret.",
            "Quarterly fast variants remain separate; prefix advice is not a qualified automatic router.",
        ],
    )


def markdown(summary):
    summary = json.loads(json.dumps(summary, sort_keys=True, allow_nan=False))
    lines = [
        "# M4-ML-06 - Decision Value And Prefix Diagnostics",
        "",
        "**Local technical gate: PASS, bounded registered scope.** Economics are exploratory,",
        "heterogeneous and do not activate a production policy. Frozen Ridge V1 remains available.",
        "",
        "## What Was Compared",
        "",
        "Original ETHUSDT 1h SC/HMA/HASH/VWAP; rolling730D; 128 attempts/origin already executed.",
        "All 228 native/Ridge decisions are retained. Primary evaluation is 32 monthly origins/alpha,",
        "February2024--September2026. Existing 13 acquisition and12 development origins stay separate.",
        "",
        "N=native anchor; R=Ridge V1; X=frozen X2 with the same history and guard;",
        "G=Ridge with Qhat>=0; F=Ridge ranked by maximum Qhat under the old guard.",
        "G/F are component ablations. Constant Yhat=0 is an incumbent/tie control, not random search.",
        "",
        "## Decision Value Against Native",
        "",
        "| Alpha | Policy | Changed/32 | Observed/32 | Help/Harm/Tie | Mean R | IS contribution | Mean Q |",
        "|---|---|---:|---:|---|---:|---:|---:|",
    ]
    for group, g in summary["groups"].items():
        for policy in ("R", "X", "G", "F"):
            r = g["policies"][policy]
            v = r["all_observed"] or {}
            lines.append(
                f"| {group} | {policy} | {r['changed_effective']} | {r['observed']} | {r['helped']}/{r['hurt']}/{r['tied']} | {number(v.get('mean_R'))} | {number(v.get('mean_IS'))} | {number(v.get('mean_Q'))} |"
            )
    lines += [
        "",
        "Raw-Sharpe differences from reset diagnostic accounts; the count conditions each mean.",
        "Unknown/undefined months are not zero. Different masks must not be compared as identical cohorts.",
        "R=(IS_anchor-IS_selected)+Q. Positive R alone does not establish improved forward quality.",
        "",
        "## Matched Incremental Decisions",
        "",
        "| Alpha | Contrast | Valid/32 | Changed/32 | Help/Harm/Tie | Delta R | Delta Q |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for group, g in summary["groups"].items():
        for name, c in g["contrasts"].items():
            lines.append(
                f"| {group} | {name} | {c['observed']} | {c['changed']} | {c['helped']}/{c['hurt']}/{c['tied']} | {number(c['mean_deltaR'])} | {number(c['mean_deltaQ'])} |"
            )
    lines += [
        "",
        "## Prediction Versus Decision Error",
        "",
        "| Alpha | Model | Acquired-origin MSE | Origins | Changed-winner MSE | Winner observations |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for group, g in summary["groups"].items():
        for policy in ("R", "X"):
            p = g["policies"][policy]["prediction_loss"]
            lines.append(
                f"| {group} | {policy} | {number(p['acquired_origin_macro_mse'])} | {p['acquired_supported_origins']} | {number(p['changed_selected_mse'])} | {p['changed_selected_observed']} |"
            )
    lines += [
        "",
        "The acquired and winner masks differ; these columns diagnose selection concentration,",
        "not two independent tests or a fair winner-versus-randomized-sample experiment.",
        "",
        "## Existing Acquisition Sensitivity",
        "",
        "| Reviewed development panel | Zero MSE | Ridge MSE | X2 MSE |",
        "|---|---:|---:|---:|",
    ]
    for panel, data in summary["prior_acquisition_sensitivity"].items():
        v = data["macro_mse"]
        lines.append(
            f"| {panel} | {number(v['ZERO'])} | {number(v['P0'])} | {number(v['X2'])} |"
        )
    lines += [
        "",
        "These are reused development results, not new evaluation losses. Base and union are related",
        "acquisition panels; the old policy's winner union can alter training support. Primary ML06",
        "decision comparisons all use the same logged union, keeping model effects matched.",
        "",
        "## Witnessed Candidate Opportunity",
        "",
        "| Alpha | Policy | Supported/32 | Better base candidate | Mean positive headroom | Best excluded by guard | Ranking misses within guard |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for group, g in summary["groups"].items():
        for policy, v in g["observed_opportunity"].items():
            lines.append(
                f"| {group} | {policy} | {v['supported']} | {v['observed_better_base_candidate']} | {number(v['mean_positive_headroom'])} | {v['best_excluded_by_guard']} | {v['ranking_miss_within_guard']} |"
            )
    lines += [
        "",
        "Opportunity uses only the preexisting base panel plus anchor. New winner queries are excluded",
        "from that benchmark. Feature-dependent acquisition and missing labels prevent full-pool or",
        "global-parameter-space regret claims. Guard and ranking misses need not be disjoint.",
        "",
        "## Downside And Guard Reliability",
        "",
        "| Alpha | Policy | Observed predictions | Q<0 | Q<-0.10 | Qhat-Q bias | Worst Q | Mean worst20% Q |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group, g in summary["groups"].items():
        for policy in ("R", "X", "G", "F"):
            r = g["policies"][policy]
            v = r["all_observed"] or {}
            p = r["guard"]
            lines.append(
                f"| {group} | {policy} | {p['observed_predictions']} | {p['accepted_realized_Q_negative']} | {p['accepted_realized_Q_below_minus_0_1']} | {number(p['prediction_bias_Q'])} | {number(v.get('worst_Q'))} | {number(v.get('mean_worst_20pct_Q'))} |"
            )
    lines += [
        "",
        "A stricter predicted guard is not a realized outcome guarantee. Worst20% uses fractional",
        "empirical mass and requires ten observed folds; these are Sharpe-difference units, not money.",
        "",
        "## Prefix Diagnostics And Next Actions",
        "",
        "| Alpha | Native selectors, all57 | Median absolute IS feature share | Leading next action |",
        "|---|---|---:|---|",
    ]
    for group, g in summary["groups"].items():
        c = g["decision"]
        lines.append(
            f"| {group} | {c['native_selector_counts']} | {number(c['raw_IS_absolute_contribution_share_median'])} | {c['leading_next_action']} |"
        )
    lines += [
        "",
        "IS feature contribution is exact served standardized arithmetic, not causal importance.",
        "Adaptive TPE coverage is not neutral-design sensitivity. Missing local probes and environment",
        "paths remain explicit. Compatibility, measured sampler response and original-alpha proof differ.",
        "",
        "## Uncertainty",
        "",
        "Exploratory R-N and X-R intervals reserve16 coordinates, use shared3-month moving blocks,",
        "16,384 draws/seed731/family95%. Each numerical coordinate requires the complete32-month",
        "metric calendar; unsupported coordinates get no interval. G/F remain descriptive.",
        "",
        "| Coordinate | Status | R interval | Q interval |",
        "|---|---|---|---|",
    ]
    for name, r in summary["intervals"].items():

        def interval(field):
            return (
                "N/A"
                if field not in r
                else f"[{number(r[field]['lower'])}, {number(r[field]['upper'])}]"
            )

        lines.append(
            f"| {name} | {r['status']} | {interval('deltaR')} | {interval('deltaQ')} |"
        )
    lines += [
        "",
        "These conditional intervals do not restore independent OOS or include uncertainty from",
        "choosing models after reviewed development. Earlier family receipts are not rewritten.",
        "",
        "## Existing Quarterly Sampler And Selector Evidence",
        "",
        "| Alpha | Contrast | Valid/19 | R | Q |",
        "|---|---|---:|---:|---:|",
    ]
    for group, g in summary["groups"].items():
        for name, c in g["quarterly"]["contrasts"].items():
            v = c["available_pair_means_descriptive"]
            lines.append(
                f"| {group} | {name} | {c['paired_quarters']} | {number(v['R'])} | {number(v['Q'])} |"
            )
    lines += [
        "",
        "Quarterly/365D fast variants remain a separate experiment; no new optimizer was run.",
        "Prefix input eligibility does not prove advice was sealed before each study. No automatic",
        "sampler/selector router or universal winner is certified.",
        "",
        "## Work, Safety And Handoff",
        "",
    ]
    w = summary["work"]
    lines += [
        f"New learner fits: {w['logical_fits']}; numeric/reference/qualification charges: {w['numeric_reference_qualification_charge']}.",
        f"Financial calls: {w['financial_calls']}; measured stage CPU {w['financial_stage_cpu_seconds']:.2f}s, wall {w['financial_stage_wall_seconds']:.2f}s.",
        f"Cold measured CPU {w['cold_measured_cpu_seconds']:.2f}s; query process peak {w['query_peak_process_rss_mib']:.2f}MiB.",
        f"Queries outside the fixed budget: {w['missing_outside_budget']} {w['outside_budget_by_policy']}.",
        w["timing_limitation"],
        "",
        "All four original-route controls match complete metric/account witnesses exactly.",
        "Fresh causal controls, permitted-past positives and unchanged source-bound earlier market",
        "proofs are recorded separately. Queried labels never enter the fitted histories.",
        "The historical union was acquired by the old policy; alternative decisions condition on",
        "that logged history and do not constitute a replacement-policy acquisition rollout.",
        "",
        summary["common_next_action"],
        "",
        "Per-alpha cards, coverage, exact contrasts, tails and source hashes are in",
        "[the machine summary](../../benchmarks/optimization/meta_selection/model_research_v1/ml06_summary.json).",
        "M5-11.7/M5-12, public activation, CI, builds, push and release await separate approval.",
    ]
    return "\n".join(lines) + "\n"
