"""Publish-safe analysis of sealed helper diagnostics; never retune or run search."""

from hashlib import sha256
import json
from statistics import mean
from xml.etree.ElementTree import parse

from tools.qms_sampler_helper_diagnostic import LANE, ROOT, registration, write_once
from tools.qms_sampler_helper_package import LANE as PACKAGE


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def compare(cells, case, left_arm, right_arm):
    by = {(r["seed"], r["arm"]): r for r in cells if r["case"] == case}
    paired, seeds = [], []
    for seed in (731, 732, 733):
        left, right = by[seed, left_arm], by[seed, right_arm]
        seeds.append(dict(seed=seed, left_equity=left["final_equity"], right_equity=right["final_equity"]))
        for a, b in zip(left["fold_measurements"], right["fold_measurements"], strict=True):
            assert a["fold_id"] == b["fold_id"]
            if all(row[role]["status"] == "VALID" for row in (a, b) for role in ("is", "forward")):
                paired.append((a, b))
    values = []
    for position, arm in enumerate((left_arm, right_arm)):
        values.append(dict(arm=arm,
                           mean_is_sharpe=mean(p[position]["is"]["raw_sharpe"] for p in paired),
                           mean_forward_sharpe=mean(p[position]["forward"]["raw_sharpe"] for p in paired),
                           mean_decay=mean(p[position]["decay"] for p in paired)))
    return dict(case=case, left=left_arm, right=right_arm, common_valid_observations=len(paired),
                seed_final_equities=seeds, matched_metrics=values,
                exclusion="only common VALID raw IS/forward cells; all invalid cells retained in local raw receipts")


def export():
    registered = registration()
    summary_path = LANE / "summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["source"] == registered["source"]
    assert summary["registration_sha256"] == digest(LANE / "registration.json")
    assert len(summary["parity"]) == 6 and len(summary["cells"]) == 21
    package = json.loads((PACKAGE / "proof.json").read_text())
    assert package["status"] == "PASS" and package["source_exact_wheel_sdist"]
    tree = parse(LANE / "regression-v2.xml")
    cases = list(tree.iter("testcase"))
    assert len(cases) == 184 and not list(tree.iter("failure")) and not list(tree.iter("error"))
    cells = []
    for row in summary["cells"]:
        keys = ("case", "arm", "seed", "config_seconds", "wall_seconds", "sampler_seconds", "cpu_seconds",
                "peak_rss_mib", "attempts", "states", "relative_proposal_trials", "independent_calls",
                "final_equity", "total_return_pct", "sharpe", "max_drawdown_pct", "accounting_replay", "raw_receipt_sha256")
        valid = sum(m["is"]["status"] == m["forward"]["status"] == "VALID" for m in row["fold_measurements"])
        cells.append({**{k: row[k] for k in keys}, "valid_raw_fold_cells": valid,
                      "undefined_raw_fold_cells": 4 - valid})
    evidence = dict(
        schema="qms-sampler-helper-public-report-v1", status="COMPLETE_LOCAL",
        source=summary["source"], registration_sha256=digest(LANE / "registration.json"),
        summary_sha256=digest(summary_path), guide_unchanged=True, publication=False,
        protocol=dict(seeds=registered["seeds"], attempts_per_fold=128, unique_forward_folds=4,
                      total_runs=21, total_attempts=10752, schedule="Mode 4/per_fold_causal",
                      split="quarterly 2022; rolling 365D IS", meta="off",
                      raw_decay="selected-candidate raw IS Sharpe minus raw forward Sharpe",
                      paired_observations_not_independent_folds=True,
                      private_alpha_unchanged=True, private_code_data_ranges_winners_excluded=True),
        helper_manual_parity=summary["parity"], aggregates_per_arm=summary["aggregate"],
        common_valid_comparisons=[compare(summary["cells"], "delta_rsi", "helper_cma", "numeric_tpe"),
                                  compare(summary["cells"], "public_ma", "helper_cma", "numeric_tpe"),
                                  compare(summary["cells"], "public_ma", "helper_cma", "mixed_cma")],
        cells=cells, tests=dict(passed=184, failed=0, receipt_sha256=digest(LANE / "regression-v2.xml")),
        package=package, package_receipt_sha256=digest(PACKAGE / "proof.json"),
        limitations=["bounded four-period diagnostic, not twelve independent forward origins",
                     "meta disabled; not a new meta economic promotion",
                     "manual numeric CMA identical: no helper-driven profit or kernel speedup",
                     "public MA does not win uniformly against mixed-independent CMA",
                     "latency is observational full-study time, not isolated repeated performance qualification",
                     "same-process high-water RSS cannot establish per-arm memory superiority",
                     "CPython 3.12 local only; no remote/public artifact qualification"],
    )
    output = ROOT / "benchmarks/optimization/meta_selection/qms_sampler_helper_evidence.json"
    write_once(output, evidence)
    print(json.dumps(dict(status="COMPLETE_LOCAL", runs=21, trials=10752, tests=184,
                          output=str(output.relative_to(ROOT)), publication=False)))


if __name__ == "__main__":
    export()
