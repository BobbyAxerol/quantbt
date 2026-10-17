"""Independent cold completion audit; no fit, sampler or financial execution."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .admission import BASE, PUBLIC, ROOTS, load_corpus, pin, read, save_new, verify_freeze
from .analysis import summarize
from .protocol import GROUPS, StudyProtocol


def audit(output):
    output = Path(output)
    result = read(output / "result.json")
    start = read(output / "start.json")
    reg = read(start["registration"]["path"])
    if pin(start["registration"]["path"]) != start["registration"]:
        raise ValueError("source registration changed")
    for ref in (*reg["source_pins"], *reg.get("reuse_pins", ())):
        if pin(ref["path"]) != ref:
            raise ValueError("source/evidence custody changed")
    if result["status"] != "REPLAY_COMPLETE_ANALYSIS_PENDING":
        raise ValueError("terminal completed replay required")
    protocol = StudyProtocol()
    required = {(panel, g, fold, policy) for panel in ("base", "union") for g in GROUPS
                for fold in range(57) for policy in (("P0", "P1", "P2") if fold >= 25 else ("P0", "P1"))}
    keys = [(r["panel"], r["group"], r["fold"], r["policy"]) for r in result["rows"]]
    if len(keys) != len(set(keys)) or set(keys) != required:
        raise ValueError("registered calendar/policy coverage incomplete")
    if result["new_optimizer_proposals"] != 0 or result["new_financial_calls"] != 0:
        raise ValueError("research exceeded financial scope")
    max_coefficient_diff = 0.
    matched = 0
    corpus_pins = []
    for group in GROUPS:
        corpus = load_corpus(group)
        corpus_pins.extend(corpus.pins)
        rows = [r for r in result["rows"] if r["group"] == group
                and r["panel"] == "union" and r["policy"] == "P0"]
        for row in rows:
            saved = corpus.selections[row["fold"]]
            if (row["winner"] != saved["record"]["selected_evaluation_id"] or
                    row["status"] != saved["record"]["final_selection_reason"]):
                raise ValueError("P0 current applied dictionary identity differs")
            if saved["model"] is not None:
                a = np.asarray(row["training"]["coefficients"])
                b = np.asarray(saved["model"]["coefficients"])
                if not np.allclose(a, b, rtol=1e-9, atol=1e-10):
                    raise ValueError("P0 fitted coefficients differ")
                max_coefficient_diff = max(max_coefficient_diff, float(np.max(np.abs(a-b))))
            matched += 1
    for row in result["rows"]:
        metrics = row["served_metrics"]
        if (metrics.get("y_mse") != metrics.get("q_mse") or
                metrics.get("y_mae") != metrics.get("q_mae")):
            raise ValueError("Y/Q duplicate error identity failed")
        if "metric_null_reasons" not in row or "label_statuses" not in row:
            raise ValueError("required undefined/status evidence absent")
        for key, value in metrics.items():
            if value is None and key not in row["metric_null_reasons"]:
                raise ValueError("unexplained undefined reporting metric")
    readback = read(BASE / "four-alpha-closeout-v1/readback.json")
    account_refs = []
    for ref in readback["input_pins"]:
        path = ref["path"]
        if (path.endswith(("/paths.npz", "/fills.json.gz", "/metrics.json.gz"))
                and any(path.startswith(str(root)+"/") for root in ROOTS.values())):
            if pin(path) != ref:
                raise ValueError("original raw financial evidence changed")
            account_refs.append(ref)
    old = result.get("previous_failed_work")
    old_charge = old["fits"]["regression_fit_charge"] + 2 if old else 0
    charge = result["logical_fit_ledger"]["regression_fit_charge"] + 2 + old_charge
    cpu = result["cpu_seconds"] + (old["cpu_seconds"] if old else 0)
    if (charge > protocol.max_fits or cpu > protocol.max_cpu_seconds
            or result["peak_rss_mib"] * 1024**2 > protocol.max_rss_bytes):
        raise ValueError("cumulative study work exceeded budget")
    analysis = summarize(result, protocol)
    return dict(schema="m4.ml02.cold-completion-audit.v1", technical_gate="PASS",
                baseline=verify_freeze(), registered_decision_rows=len(keys),
                matched_unique_P0_decisions=matched,
                maximum_P0_coefficient_abs_diff=max_coefficient_diff,
                corpus_input_pins=len(corpus_pins), protected_account_files=len(account_refs),
                cumulative_regression_fits_including_failed_run_and_qualification=charge,
                cumulative_cpu_seconds=cpu, result=pin(output/"result.json"),
                analysis=analysis, financial_executions=0, model_fits_in_this_verifier=0,
                limitations="reviewed fixed-panel replay; no new winner labels or financial accounts")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.output)
    print(save_new(args.output / "cold-audit.json", result))
    print(save_new(PUBLIC / "ml02_results.json", dict(result["analysis"],
        schema="m4.ml02.public-comparison.v1",
        technical_gate=result["technical_gate"], registered_decision_rows=result["registered_decision_rows"],
        matched_P0_decisions=result["matched_unique_P0_decisions"],
        maximum_P0_coefficient_abs_diff=result["maximum_P0_coefficient_abs_diff"],
        cumulative_regression_fits=result["cumulative_regression_fits_including_failed_run_and_qualification"],
        cumulative_cpu_seconds=result["cumulative_cpu_seconds"])))


if __name__ == "__main__":
    main()
