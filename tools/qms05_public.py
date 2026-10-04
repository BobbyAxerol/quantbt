"""QMS-05 executed public integration, causal lineage and added-work receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from time import perf_counter
import xml.etree.ElementTree as ET

import pandas as pd

from examples.wfo_meta_selection import run_demo
from quantbt.optimization.meta_selection.common import canonical, digest, wire
from tools.build_qms04_candidate import load_candidate

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
ENTRY = "0be25c7"


def source_manifest():
    names = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "src/quantbt",
            "rust",
            "pyproject.toml",
            "uv.lock",
            "tools/qms05_public.py",
            "tools/qms01_baseline.py",
            "tools/build_qms04_candidate.py",
            "examples/wfo_meta_selection.py",
            "tests/meta_selection",
            "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(names))
    }


def scientific_signature(result):
    wf = result.metadata["walk_forward"]
    return digest(
        {
            "params": {str(k): v for k, v in wf["params_by_fold"].items()},
            "trials": wf["trial_table"].to_json(orient="split", date_format="iso"),
            "candidates": wf["candidate_table"].to_json(
                orient="split", date_format="iso"
            ),
            "equity": result.equity.tolist(),
            "returns": result.returns.tolist(),
            "positions": result.positions.to_numpy().tolist(),
        }
    )


def execute(mode, *, observer=False, module=None):
    started = perf_counter()
    endpoint, result, ctx = run_demo(
        mode,
        observer=observer,
        min_origins=1,
        native_module=module,
    )
    seconds = perf_counter() - started
    wf = result.metadata["walk_forward"]
    meta = wf.get("meta_selection")
    records = meta["records"] if meta else ()
    retained = (
        "fold_id",
        "family_id",
        "native_selected_evaluation_id",
        "selected_evaluation_id",
        "native_selected_params",
        "selected_params",
        "information_as_of",
        "search_completed_at",
        "fit_completed_at",
        "decision_sealed_at",
        "ready_at",
        "effective_at",
        "clock_mode",
        "live_equivalence_claim",
        "matured_origins",
        "eligible_is_pool_size",
        "training_revision_ids",
        "final_selection_reason",
        "current_outer_oos_used_for_selection",
        "past_matured_forward_used_for_selection",
        "meta_proposal_uses_past_matured_forward",
        "numeric_backend",
    )
    evidence = {
        "mode": mode,
        "observer": observer,
        "bars": len(result.equity),
        "trials_per_study": 6,
        "seed": 731,
        "workers": 1,
        "support_override": 1,
        "support_override_scope": "engineering only; product default is 12",
        "public_seconds_including_observer_and_fit": seconds,
        "scientific_signature": scientific_signature(result),
        "selected_params_by_fold": {str(k): v for k, v in wf["params_by_fold"].items()},
        "final_equity": float(result.equity.iloc[-1]),
        "validation_claim": wf["validation_claim"],
        "records": [{k: r[k] for k in retained} for r in records],
        "elapsed_seconds": meta["elapsed_seconds"] if meta else {},
        "observer_attempts": meta["observer_attempts"] if meta else 0,
        "observer_failures": meta["observer_failures"] if meta else 0,
        "fitted_models": len(meta["models"]) if meta else 0,
        "meta_learned_decisions": sum(
            r["meta_proposal_uses_past_matured_forward"] for r in records
        ),
        "switches": sum(
            r["selected_evaluation_id"] != r["native_selected_evaluation_id"]
            for r in records
        ),
        "account_authority": meta["account_authority"]
        if meta
        else "existing continuous account",
        "original_result_labels_only": True,
        "financial_backend": "existing numba scalar endpoint",
        "meta_numeric_backend": "require candidate"
        if module
        else "auto baseline missing -> reference",
    }
    for r in records:
        if r["current_outer_oos_used_for_selection"] or r["live_equivalence_claim"]:
            raise AssertionError("false forward/live claim")
        if r["selected_params"] != wf["params_by_fold"][r["fold_id"]]:
            raise AssertionError("actual params lineage mismatch")
        if not (
            r["information_as_of"]
            <= r["search_completed_at"]
            <= r["decision_sealed_at"]
            < r["effective_at"]
        ):
            raise AssertionError("selection computation clocks mismatch")
    if meta and meta["observer_failures"]:
        raise AssertionError("original endpoint observer failure")
    return wire(evidence)


def report(extension):
    import _quantbt_native as baseline

    if baseline.version() != "0.4.2" or hasattr(baseline, "qms_numeric_descriptor_v1"):
        raise AssertionError("installed published native baseline changed")
    module = load_candidate(extension)
    # Explicit JIT/import warm-up. Costs below are single full-public samples,
    # not kernel medians or a statistical speed-promotion gate.
    run_demo("off", observer=False)
    runs = {
        "off": execute("off"),
        "shadow": execute("shadow"),
        "shadow_observer": execute("shadow", observer=True),
        "active_reference": execute("active", observer=True),
        "active_native": execute("active", observer=True, module=module),
    }
    if not (
        runs["off"]["scientific_signature"]
        == runs["shadow"]["scientific_signature"]
        == runs["shadow_observer"]["scientific_signature"]
    ):
        raise AssertionError("off/shadow search/account parity failed")
    if (
        runs["active_reference"]["scientific_signature"]
        != runs["active_native"]["scientific_signature"]
    ):
        raise AssertionError(
            "whole-public native/reference decision/account parity failed"
        )
    native = runs["active_native"]
    if not native["fitted_models"] or not native["observer_attempts"]:
        raise AssertionError("actual learned/observer integration not exercised")
    if not any(
        r["numeric_backend"]["selected_backend_by_block"].get("gram_solve") == "rust"
        for r in native["records"]
    ):
        raise AssertionError("actual native numeric block was not called")
    return {
        "schema": "qms05-public-evidence-v1",
        "entry_commit": ENTRY,
        "source_hashes": source_manifest(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "thread_environment": {
            k: os.environ.get(k)
            for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
        "installed_native_version": baseline.version(),
        "candidate_build": json.loads(
            (Path(extension).parent / "build_receipt.json").read_text()
        ),
        "runs": runs,
        "off_shadow_parity": True,
        "active_native_reference_parity": True,
        "forced_lower_is_switch_proof": "actual public fitted-Ridge fixtures in Q5-T03/T04; no fabricated market-edge result",
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / 1024,
        "rss_scope": "cumulative same-process imports/JIT/all five public runs; not isolated savings or plateau",
        "empirical": "NOT_ASSESSED",
        "performance": "MEASURED_COST_ONLY",
        "promotion": "no whole-WFO speed, alpha edge, public native numeric or release promotion",
    }


def receipt(evidence, junit):
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    groups = {
        f"Q5-T{i:02d}": sum(f"q5_t{i:02d}" in c.attrib.get("name", "") for c in cases)
        for i in range(1, 9)
    }
    if not all(groups.values()) or any(
        any(c.find(x) is not None for x in ("failure", "error", "skipped"))
        for c in cases
    ):
        raise AssertionError(
            "all Q5 groups/affected tests must execute without failure/error/skip"
        )
    if (
        not evidence["off_shadow_parity"]
        or not evidence["active_native_reference_parity"]
    ):
        raise AssertionError("public account/decision proof missing")
    return {
        "schema": "qms05-gate-receipt-v1",
        "entry_commit": ENTRY,
        "tests": len(cases),
        "failures": 0,
        "skips": 0,
        "executed_test_groups": groups,
        "evidence_sha256": hashlib.sha256(canonical(evidence).encode()).hexdigest(),
        "junit_sha256": hashlib.sha256(Path(junit).read_bytes()).hexdigest(),
        "technical": {
            g: "PASS"
            for g in (
                "G5-ENDPOINT",
                "G5-MODE4_CAUSAL",
                "G5-LEGACY",
                "G5-ACTUAL_SELECTION",
                "G5-OBSERVATION",
            )
        },
        "G5-OWNER": "PENDING",
        "empirical": "NOT_ASSESSED",
        "performance": "MEASURED_COST_ONLY",
        "advancement": "QMS-06 and push/merge/release require separate owner approval",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    evidence_path = DIRECTORY / "qms05_public_evidence.json"
    receipt_path = DIRECTORY / "qms05_gate_receipt.json"
    if args.check:
        evidence = json.loads(evidence_path.read_text())
        if json.loads(receipt_path.read_text()) != receipt(evidence, args.junit):
            raise SystemExit("QMS-05 executed receipt mismatch")
        if source_manifest() != evidence["source_hashes"]:
            raise SystemExit("QMS-05 source mismatch")
        if (
            hashlib.sha256(args.extension.read_bytes()).hexdigest()
            != evidence["candidate_build"]["extension_sha256"]
        ):
            raise SystemExit("QMS-05 native candidate hash mismatch")
        print("QMS-05 public evidence, tests and source/candidate hashes PASS")
        return
    evidence = report(args.extension)
    evidence_path.write_text(canonical(evidence) + "\n")
    record = receipt(evidence, args.junit)
    receipt_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "tests": record["tests"],
                "technical": record["technical"],
                "cost_seconds": {
                    k: v["public_seconds_including_observer_and_fit"]
                    for k, v in evidence["runs"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
