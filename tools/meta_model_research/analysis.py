"""Cold, support-explicit reduction of registered replay; never fills outcomes."""

from __future__ import annotations

import math

import numpy as np

from .protocol import GROUPS, StudyProtocol


def moments(values):
    values = [float(v) for v in values if v is not None]
    return dict(n=len(values), mean=math.fsum(values)/len(values) if values else None,
                median=float(np.median(values)) if values else None)


def paired_coordinates(rows, panel, protocol=StudyProtocol()):
    indexed = {(r["group"], r["fold"], r["policy"]): r for r in rows if r["panel"] == panel}
    if len(indexed) != sum(r["panel"] == panel for r in rows):
        raise ValueError("duplicate origin/policy reduction contribution")
    paired = []
    for group in GROUPS:
        for fold in protocol.evaluation_folds:
            base = indexed[group, fold, "P0"]
            for policy in ("P1", "P2"):
                current = indexed[group, fold, policy]
                loss = (current["loss"] - base["loss"]
                        if base["loss"] is not None and current["loss"] is not None else None)
                a, b = current["economics"], base["economics"]
                Q = a["Q"] - b["Q"] if a["Q"] is not None and b["Q"] is not None else None
                R = a["R"] - b["R"] if a["R"] is not None and b["R"] is not None else None
                effect = (a["IS_effect"] - b["IS_effect"] if Q is not None else None)
                if R is not None and not math.isclose(R, Q+effect, abs_tol=1e-12, rel_tol=1e-12):
                    raise ValueError("policy contrast IS/Q/R identity mismatch")
                paired.append(dict(group=group, fold=fold, policy=policy, delta_loss=loss,
                                   delta_Q=Q, delta_R=R, delta_IS_effect=effect,
                                   changed=base["winner"] != current["winner"],
                                   missing_new_winner=not a["winner_witness_exists"]))
    return paired


def family_inference(paired, protocol=StudyProtocol()):
    lookup = {(r["group"], r["fold"], r["policy"]): r for r in paired}
    coordinates = [(p, metric) for p in ("P1", "P2")
                   for metric in ("delta_loss", "delta_Q", "delta_R")]
    missing = []
    matrix = []
    for fold in protocol.evaluation_folds:
        values = []
        for policy, metric in coordinates:
            rows = [lookup[g, fold, policy][metric] for g in GROUPS]
            if any(v is None for v in rows):
                missing.append(dict(fold=fold, policy=policy, metric=metric))
                values.append(None)
            else:
                values.append(math.fsum(rows)/len(GROUPS))
        matrix.append(values)
    if missing:
        return dict(status="INCONCLUSIVE_INCOMPLETE_REGISTERED_CALENDAR", intervals=None,
                    numerical_bootstrap_executed=False, missing_coordinate_months=missing,
                    groups=GROUPS, coordinates=coordinates, registered_draws=protocol.draws)
    from arch.bootstrap import MovingBlockBootstrap
    array = np.asarray(matrix, dtype=float)
    bs = MovingBlockBootstrap(protocol.block_months, array, seed=protocol.seed)
    size = 1 - (1 - protocol.family_confidence) / len(coordinates)
    ci = bs.conf_int(lambda x: x.mean(axis=0), reps=protocol.draws,
                     method="percentile", size=size)
    return dict(status="CONDITIONAL_COMPLETE_CALENDAR_INTERVALS", numerical_bootstrap_executed=True,
                intervals={f"{p}:{m}": list(map(float, ci[:, i]))
                           for i, (p, m) in enumerate(coordinates)},
                family_confidence=protocol.family_confidence, coordinate_confidence=size,
                scope="fixed_reviewed_panel_process_not_full_pipeline_or_independent_oos")


def summarize(result, protocol=StudyProtocol()):
    summaries = {}
    for panel in ("base", "union"):
        all_rows = result["rows"]
        rows = [r for r in all_rows if r["panel"] == panel and r["fold"] in protocol.evaluation_folds]
        paired = paired_coordinates(all_rows, panel, protocol)
        cells = {}
        for group in GROUPS:
            cells[group] = {}
            for policy in ("P0", "P1", "P2"):
                subset = [r for r in rows if r["group"] == group and r["policy"] == policy]
                loss = moments(r["loss"] for r in subset)
                cells[group][policy] = dict(
                    calendar_origins=len(subset), served_loss=loss,
                    origin_macro_rmse=math.sqrt(loss["mean"]) if loss["mean"] is not None else None,
                    mae=moments(r["served_metrics"].get("y_mae") for r in subset),
                    y_spearman=moments(r["served_metrics"].get("y_spearman") for r in subset),
                    q_spearman=moments(r["served_metrics"].get("q_spearman") for r in subset),
                    y_pair_accuracy=moments(r["served_metrics"].get("y_pair_accuracy") for r in subset),
                    q_pair_accuracy=moments(r["served_metrics"].get("q_pair_accuracy") for r in subset),
                    y_calibration_slope=moments(r["served_metrics"].get("y_calibration_slope") for r in subset),
                    q_calibration_slope=moments(r["served_metrics"].get("q_calibration_slope") for r in subset),
                    train_loss=moments(r["training"].get("train_origin_macro_mse") for r in subset),
                    effective_df=moments(r["training"].get("effective_degrees_of_freedom") for r in subset),
                    beta_l2=moments(r["training"].get("beta_l2") for r in subset),
                    R_vs_native=moments(r["economics"]["R"] for r in subset),
                    Q_vs_native=moments(r["economics"]["Q"] for r in subset),
                    missing_winner_witness=sum(not r["economics"]["winner_witness_exists"] for r in subset),
                    known_rows=sum(r["known_rows"] for r in subset),
                    scored_rows=sum(r["scored_rows"] for r in subset),
                )
                if policy != "P0":
                    contrasts = [r for r in paired if r["group"] == group and r["policy"] == policy]
                    cells[group][policy]["paired_vs_P0"] = dict(
                        delta_loss=moments(r["delta_loss"] for r in contrasts),
                        delta_R=moments(r["delta_R"] for r in contrasts),
                        delta_Q=moments(r["delta_Q"] for r in contrasts),
                        delta_IS_effect=moments(r["delta_IS_effect"] for r in contrasts),
                        changed=sum(r["changed"] for r in contrasts),
                    )
        macro = {}
        for policy in ("P0", "P1", "P2"):
            loss = [cells[g][policy]["served_loss"]["mean"] for g in GROUPS]
            macro[policy] = dict(origin_then_equal_group_mse=math.fsum(loss)/len(loss)
                                 if all(v is not None for v in loss) else None,
                                 supported_loss_origins={g: cells[g][policy]["served_loss"]["n"] for g in GROUPS})
        inference = family_inference(paired, protocol)
        shortlist = []
        if inference["intervals"] is not None:
            for policy in ("P1", "P2"):
                baseline, candidate = (macro[p]["origin_then_equal_group_mse"] for p in ("P0", policy))
                loss_gain = (baseline - candidate)/baseline if baseline and baseline > 0 else None
                ci = inference["intervals"]
                if (loss_gain is not None and loss_gain >= protocol.loss_relative_improvement
                        and ci[f"{policy}:delta_loss"][1] <= 0
                        and ci[f"{policy}:delta_Q"][0] >= -protocol.q_noninferiority
                        and ci[f"{policy}:delta_R"][0] >= -protocol.r_noninferiority):
                    shortlist.append(policy)
        summaries[panel] = dict(cells=cells, macro=macro, inference=inference,
                                disposition="RESEARCH_SHORTLIST" if shortlist else "KEEP_FROZEN_V1",
                                shortlist=shortlist)
    return dict(schema="m4.ml02.analysis.v1", summaries=summaries,
                empirical_status="INCONCLUSIVE" if not summaries["base"]["shortlist"] else "SCOPED_GAIN",
                public_activation=False, economic_guarantee=False,
                label_scope="known_registered_panel_and_available_winners_only")
