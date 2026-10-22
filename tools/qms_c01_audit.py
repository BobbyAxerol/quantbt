"""Trace current public WFO contracts; no activation, research or publication."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import random
from unittest.mock import patch

import numpy as np
import optuna

from quantbt import QuantBTEndpoint
from tools import qms01_baseline as baseline
from tools.qms_c01_contracts import CASES, review_case

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "b5563de495263d4b5fb8a9953e727c25c90cc441"
SCHEMA = "qms-c01-methodology-contract-review-v1"


def digest(value):
    return sha256(json.dumps(baseline.safe(value), sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def rng_digest():
    return digest({"python": random.getstate(), "numpy": np.random.get_state()})


def run_trace(mode, schedule, *, explicit_off=False, data=None):
    original = baseline.endpoint

    def endpoint(*args, **kwargs):
        bt = original(*args, **kwargs)
        if explicit_off:
            config = replace(bt.config.walkforward_config,
                             meta_selection={"mode": "off"})
            bt = QuantBTEndpoint(replace(bt.config, walkforward_config=config))
        return bt

    random.seed(991)
    np.random.seed(991)
    with patch.object(baseline, "endpoint", endpoint):
        payload, result, engine = baseline.trace_run(data, mode=mode, schedule=schedule)
    return payload, result, engine, rng_digest()


def native_identity(payload):
    return digest({
        "pools": payload["pools"],
        "study_records": [{k: row[k] for k in (
            "study_id", "selected", "compact_trials", "compact_candidates")}
            for row in payload["studies"]],
        "positions": payload["positions"], "equity": payload["equity"],
        "signal": payload["stitched_signal"],
        "account": payload["account_contract"],
        "one_way_fee": payload["canonical_one_way_fee_rate"],
    })


def route_receipt(payload, result, engine, *, off_exact, rng_exact):
    case = review_case(payload["mode"], payload["schedule"])
    studies = payload["studies"]
    selection_windows = [
        {"study_id": row["study_id"], "train_end": fold["train_end"],
         "validation_or_test_end": fold["test_end"]}
        for row in studies for fold in row["selected"]["fold_metrics"]
    ]
    finalists = [row["selected"] for row in studies]
    selector = engine.config.candidate_selection_metric
    uses_forward_ranking = selector in {"robust_decay", "mean_oos_sharpe"}
    uses_outer_oos = (case.schedule == "per_fold_decay" or
        case.schedule == "global" and case.mode != "mode_5_full_robust"
        and uses_forward_ranking)
    legacy_flag = payload["summary"]["oos_used_for_selection"]
    records = [r for p in payload["pools"] for r in p["all_trials"]]
    return {
        "contract": asdict(case), "resolved_selector": selector,
        "studies": len(studies), "folds": payload["summary"]["n_folds"],
        "full_trial_rows": len(records),
        "full_eligible_rows": sum(len(p["eligible_ids"]) for p in payload["pools"]),
        "shortlist_rows": sum(len(p["filtered_candidate_ids"]) for p in payload["pools"]),
        "native_identity": native_identity(payload),
        "explicit_off_exact": off_exact, "rng_exact": rng_exact,
        "final_anchors": [
            {"study_id": row["study_id"], "trial_id": r["trial_id"],
             "params": r["params"], "objective": r["objective"],
             "mean_is_sharpe": r["mean_is_sharpe"],
             "mean_forward_or_synthetic_sharpe": r["mean_oos_sharpe"],
             "mean_decay": r["mean_decay"], "std_decay": r["std_decay"],
             "stage": r["selection_metadata"].get("stage"),
             "selected_by": r["selection_metadata"].get("selected_by")}
            for row, r in zip(studies, finalists, strict=True)],
        "selection_windows": selection_windows,
        "score_contexts": sorted({row["context"] for row in payload["score_tasks"]}),
        "optuna_observed_current_OOS": any(
            r["selection_metadata"].get("oos_seen_by_optuna", False) for r in records),
        "actual_current_outer_OOS_ranking": uses_outer_oos,
        "legacy_metadata_OOS_ranking": legacy_flag,
        "metadata_discrepancy": bool(legacy_flag) != uses_outer_oos,
        "raw_IS_fields_retained": all(
            "is_sharpe_raw" in f for r in records if not r["pruned"] for f in r["fold_metrics"]),
        "meta_metric_validity": "NOT_CREATED_BY_NATIVE_SCALAR_TRACE",
        "meta_sidecar": "meta_selection" in result.metadata["walk_forward"],
        "fee_rate_one_way": payload["canonical_one_way_fee_rate"],
        "equity_bars": len(result.equity),
    }


def verify_receipt(receipt):
    if receipt.get("schema") != SCHEMA or receipt.get("activation") is not False:
        raise ValueError("C01 review must not authorize activation")
    if receipt.get("protected_source_diff") != []:
        raise ValueError("C01 assessment modified protected source")
    lanes = receipt.get("lanes", [])
    if [(r["contract"]["mode"], r["contract"]["schedule"]) for r in lanes] != list(baseline.ROUTES):
        raise ValueError("C01 native route coverage mismatch")
    for lane in lanes:
        case = review_case(lane["contract"]["mode"], lane["contract"]["schedule"])
        if lane["contract"] != asdict(case):
            raise ValueError("C01 contract map changed")
        if not lane["explicit_off_exact"] or not lane["rng_exact"] or lane["meta_sidecar"]:
            raise ValueError("C01 off/account/RNG parity failed")
        if lane["fee_rate_one_way"] != 0.0005 or lane["equity_bars"] != baseline.BUDGET["bars"]:
            raise ValueError("C01 account contract mismatch")
        if lane["optuna_observed_current_OOS"] or not lane["raw_IS_fields_retained"]:
            raise ValueError("C01 adaptive objective/metric provenance mismatch")
    mismatches = [r["contract"]["mode"] for r in lanes if r["metadata_discrepancy"]]
    if receipt.get("metadata_discrepancies") != mismatches:
        raise ValueError("C01 metadata discrepancy was hidden")
    return receipt


def source_symbols():
    required = {
        "src/quantbt/optimization/meta_selection/capture.py": ("ISPoolCapture.validate", "ISPoolCapture.capture"),
        "src/quantbt/optimization/meta_selection/config.py": ("validate_meta_route",),
        "src/quantbt/optimization/meta_selection/runtime.py": (
            "PublicMetaRuntime.compatibility_family", "PublicMetaRuntime.select", "PublicMetaRuntime.observe"),
    }
    with patch.object(baseline, "SYMBOLS", {**baseline.SYMBOLS, **required}):
        return baseline.symbol_map()


def build_receipt():
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    lanes = []
    for case in CASES:
        base, result, engine, base_rng = run_trace(case.mode, case.schedule)
        off, off_result, _engine, off_rng = run_trace(case.mode, case.schedule, explicit_off=True)
        off_exact = native_identity(base) == native_identity(off)
        off_exact = off_exact and np.array_equal(result.returns, off_result.returns)
        lanes.append(route_receipt(base, result, engine, off_exact=off_exact,
                                   rng_exact=base_rng == off_rng))
    protected = baseline.git("diff", "--name-only", ENTRY, "--", "src", "rust",
                             "pyproject.toml", "uv.lock", baseline.GUIDE).decode().splitlines()
    receipt = {
        "schema": SCHEMA, "entry_sha": ENTRY,
        "source_sha": baseline.git("rev-parse", "HEAD").decode().strip(),
        "guide_sha256": baseline.digest((ROOT / baseline.GUIDE).read_bytes()),
        "source_symbols": source_symbols(),
        "protected_source_diff": protected,
        "fixture": {"source": "examples/walk_forward_train_test.py::strategy",
                    "market": "deterministic_synthetic_daily_v1",
                    "bars": baseline.BUDGET["bars"], "attempts_per_study": 6,
                    "seed": baseline.BUDGET["seed"], "economic_claim": False},
        "lanes": lanes,
        "metadata_discrepancies": [r["contract"]["mode"] for r in lanes if r["metadata_discrepancy"]],
        "activation": False, "new_meta_methods": [],
        "status": "ASSESSMENT_COMPLETE_ACTIVATION_REQUIRES_OWNER_CHOICE",
        "scientific_study": "UNCHANGED_NOT_RERUN",
        "publication": False,
    }
    return verify_receipt(receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("sealed C01 receipt exists; choose a fresh output")
    receipt = build_receipt()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": receipt["status"], "routes": len(receipt["lanes"]),
                      "metadata_discrepancies": receipt["metadata_discrepancies"],
                      "activation": False}))


if __name__ == "__main__":
    main()
