"""Executed QMS-06 prepared/handoff qualification, not economic promotion."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
import optuna
import pandas as pd

from examples.wfo_meta_selection import PARAM_RANGES, make_endpoint, market
from examples.wfo_meta_handoff import consume_reviewed
from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.common import canonical, wire
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.handoff import (
    dumps_handoff,
    export_fold_handoff,
)
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.preparation.cache import CachePolicy
from quantbt.preparation.native_execution import NativeExecutionPreparationCache
from tools.build_qms06_candidate import load

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
ENTRY = "3c69cb8"
RTOL, ATOL = 1e-10, 1e-10


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
            "tools/qms06_prepared.py",
            "tools/qms06_source_guard.py",
            "tools/build_qms06_candidate.py",
            "tools/build_qms04_candidate.py",
            "examples/wfo_meta_selection.py",
            "examples/wfo_meta_handoff.py",
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


@contextmanager
def isolated_financial_candidate(module):
    # Test/evidence-only injection through the existing cache constructor. The
    # installed distribution/global backend and public config stay unchanged.
    original = NativeExecutionPreparationCache.__init__

    def init(self, policy=CachePolicy(), *, module=None):
        original(self, policy, module=module or candidate)

    candidate = module
    with patch.object(NativeExecutionPreparationCache, "__init__", init):
        yield


def execute(runtime, prepared, meta_module=None):
    bt = make_endpoint(
        "active",
        observer=True,
        min_origins=1,
        policy="require" if meta_module else "reference",
    )
    wf = replace(
        bt.config.walkforward_config,
        metadata={
            **bt.config.walkforward_config.metadata,
            "native_prepared_wfo": prepared,
        },
    )
    bt = QuantBTEndpoint(
        replace(bt.config, target_runtime=runtime, walkforward_config=wf)
    )
    ctx = MetaHistoryContext(
        MetaHistory(),
        "public-sma-demo",
        "SYNTHETICUSD-linear",
        "1D",
        "qms06-evidence",
        native_module=meta_module,
        clock=lambda fold, stage, elapsed: fold.train_index[-1]
        + pd.Timedelta(seconds={"search": 10, "fit": 20, "seal": 30}[stage]),
    )
    started = perf_counter()
    result = bt.backtest(data=market(), param_ranges=PARAM_RANGES, meta_history=ctx)
    seconds = perf_counter() - started
    wf = result.metadata["walk_forward"]
    meta = wf["meta_selection"]
    rows = []
    for task, record in zip(meta["tasks"], meta["records"], strict=True):
        rows.append(
            {
                "fold_id": record["fold_id"],
                "family_id": task.family.family_id,
                "anchor": task.anchor.candidate_id,
                "selected": record["selected_candidate_id"],
                "params": record["selected_params"],
                "native_params": record["native_selected_params"],
                "native_selection_reason": record["native_selection_reason"],
                "reason": record["final_selection_reason"],
                "origins": record["matured_origins"],
                "clocks": {
                    k: record[k]
                    for k in (
                        "information_as_of",
                        "search_completed_at",
                        "fit_completed_at",
                        "decision_sealed_at",
                        "ready_at",
                        "effective_at",
                    )
                },
                "pool": [
                    {
                        "candidate_id": c.candidate_id,
                        "status": c.observation.status.value,
                        "raw_sharpe": c.observation.raw_sharpe,
                        "std": c.observation.sample_std,
                        "count": c.observation.sample_count,
                        "first_mark": c.observation.initial_mark_equity,
                        "activity": c.observation.activity_count,
                        "objective": c.objective,
                        "input_signature": c.observation.input_signature,
                        "economics_id": c.observation.economics_id,
                        "witness": c.observation.output_ref,
                        "verification": c.observation.verification,
                    }
                    for c in task.candidates
                ],
                "predictions": [
                    {
                        k: p[k]
                        for k in (
                            "candidate_id",
                            "eligible",
                            "yhat",
                            "qhat",
                            "distance",
                        )
                    }
                    for p in record["proposal"].predictions
                ],
            }
        )
    if meta["observer_failures"] or any(
        r["current_outer_oos_used_for_selection"] for r in meta["records"]
    ):
        raise AssertionError("observer/causal boundary failure")
    return result, wire(
        {
            "public_seconds": seconds,
            "rows": rows,
            "financial_runtime": runtime,
            "prepared_policy": prepared,
            "meta_policy": "require" if meta_module else "reference",
            "observer_attempts": meta["observer_attempts"],
            "observer_failures": meta["observer_failures"],
            "elapsed_seconds": meta["elapsed_seconds"],
            "models": len(meta["models"]),
            "numeric_backend": meta["records"][-1]["numeric_backend"],
            "scoring_cache": wf["prepared_scoring_cache"],
            "final_equity": float(result.equity.iloc[-1]),
        }
    )


def compare(a, b, evidence_a, evidence_b):
    for x, y in zip(evidence_a["rows"], evidence_b["rows"], strict=True):
        for key in (
            "fold_id",
            "family_id",
            "anchor",
            "selected",
            "params",
            "native_params",
            "reason",
            "origins",
            "clocks",
        ):
            if x[key] != y[key]:
                raise AssertionError(f"reference/prepared logical parity: {key}")
        for cx, cy in zip(x["pool"], y["pool"], strict=True):
            for key in (
                "candidate_id",
                "status",
                "count",
                "activity",
                "input_signature",
                "economics_id",
            ):
                if cx[key] != cy[key]:
                    raise AssertionError(f"candidate pool mismatch: {key}")
            np.testing.assert_allclose(
                [cx[k] for k in ("raw_sharpe", "std", "first_mark", "objective")],
                [cy[k] for k in ("raw_sharpe", "std", "first_mark", "objective")],
                rtol=RTOL,
                atol=ATOL,
            )
        for px, py in zip(x["predictions"], y["predictions"], strict=True):
            if (
                px["candidate_id"] != py["candidate_id"]
                or px["eligible"] != py["eligible"]
            ):
                raise AssertionError("inference identity/eligibility mismatch")
            if px["yhat"] is not None:
                np.testing.assert_allclose(
                    [px[k] for k in ("yhat", "qhat", "distance")],
                    [py[k] for k in ("yhat", "qhat", "distance")],
                    rtol=RTOL,
                    atol=ATOL,
                )
    np.testing.assert_allclose(a.equity, b.equity, rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(a.positions, b.positions, rtol=RTOL, atol=ATOL)
    for name in ("returns", "fees", "funding"):
        np.testing.assert_allclose(
            getattr(a, name), getattr(b, name), rtol=RTOL, atol=ATOL
        )


def report(extension):
    import _quantbt_native as baseline

    if baseline.version() != "0.4.2" or hasattr(
        baseline, "QMS_PREPARED_METRIC_SUPPORT_V1"
    ):
        raise AssertionError("installed baseline changed")
    module = load(extension)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    # Explicit import/JIT warm-up. Subsequent samples are full public runs,
    # including observer/fit/report costs, not paired speed-promotion medians.
    execute("numba", "off")
    reference_numba, numba_evidence = execute("numba", "off")
    reference_rust, rust_evidence = execute("rust", "off")
    with isolated_financial_candidate(module):
        prepared_rust, prepared_evidence = execute("rust", "require")
        native_meta, meta_evidence = execute("rust", "require", module)
    for result, evidence in (
        (reference_rust, rust_evidence),
        (prepared_rust, prepared_evidence),
        (native_meta, meta_evidence),
    ):
        compare(reference_numba, result, numba_evidence, evidence)
    handoffs = []
    for row in meta_evidence["rows"]:
        bundle = export_fold_handoff(native_meta, fold_id=row["fold_id"])
        before = dumps_handoff(bundle)
        params = consume_reviewed(bundle, now=bundle.decision.ready_at)
        if (
            params != row["params"]
            or before != dumps_handoff(bundle)
            or bundle.effective_at is not None
        ):
            raise AssertionError("host handoff changed actual params/state/activation")
        handoffs.append(
            {
                "fold_id": row["fold_id"],
                "handoff_id": bundle.handoff_id,
                "model_id": bundle.decision.model_id,
                "bytes": len(before.encode()),
                "restored": True,
                "host_state_mutations": 0,
                "effective_at": None,
            }
        )
    cache = prepared_evidence["scoring_cache"]["native_prepared_wfo"]
    if cache["metric_witness_rows"] != cache["native_rows"] or not cache["native_rows"]:
        raise AssertionError("same-pass native witness missing")
    if not meta_evidence["models"] or not meta_evidence["numeric_backend"]["ffi_calls"]:
        raise AssertionError("executed Rust numeric path missing")
    if baseline.version() != "0.4.2":
        raise AssertionError("private build replaced published native")
    return {
        "schema": "qms06-prepared-evidence-v1",
        "entry_commit": ENTRY,
        "source_hashes": source_manifest(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "thread_environment": {
            k: os.environ.get(k)
            for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
        "candidate_build": json.loads(
            (Path(extension).parent / "build_receipt.json").read_text()
        ),
        "installed_native_version": baseline.version(),
        "fixture": {
            "bars": 850,
            "folds": 6,
            "trials_per_study": 6,
            "seed": 731,
            "workers": 1,
            "clock": "declared historical budget: search/fit/seal=10/20/30s from IS cutoff",
            "support_override": "1 engineering only; product default=12",
            "rtol": RTOL,
            "atol": ATOL,
        },
        "runs": {
            "reference_numba": numba_evidence,
            "reference_rust": rust_evidence,
            "prepared_rust": prepared_evidence,
            "prepared_rust_meta_rust": meta_evidence,
        },
        "prepared_reference_parity": True,
        "handoffs": handoffs,
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / 1024,
        "rss_scope": "cumulative same-process imports/JIT/five runs; not isolated RSS savings/plateau",
        "w3": "META_ROUTE_UNSUPPORTED: separate reset-flat loop lacks full-pool/original-metric seam; optional scope acceptance PENDING",
        "empirical": "NOT_ASSESSED",
        "performance": "MEASURED_COST_ONLY",
        "promotion": "no release, speed/edge, live-equivalence or generic reactive certification",
    }


def receipt(evidence, junit):
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    groups = {
        f"Q6-T{i:02d}": sum(f"q6_t{i:02d}" in c.attrib.get("name", "") for c in cases)
        for i in range(1, 9)
    }
    if not all(groups.values()) or any(
        any(c.find(x) is not None for x in ("failure", "error", "skipped"))
        for c in cases
    ):
        raise AssertionError(
            "Q6 groups/affected regressions must all execute without failure/error/skip"
        )
    if not evidence["prepared_reference_parity"] or not all(
        h["restored"] for h in evidence["handoffs"]
    ):
        raise AssertionError("prepared/handoff execution proof missing")
    return {
        "schema": "qms06-gate-receipt-v1",
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
                "G6-ADAPTER",
                "G6-PREPARED_PARITY",
                "G6-CAPABILITY",
                "G6-HANDOFF",
                "G6-NO_SCOPE_CREEP",
            )
        },
        "G6-OWNER": "PENDING",
        "W3-OPTIONAL-SCOPE-OWNER": "PENDING",
        "empirical": "NOT_ASSESSED",
        "performance": "MEASURED_COST_ONLY",
        "advancement": "QMS-07/08, push/merge/publication require separate owner approval",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    evidence_path = DIRECTORY / "qms06_prepared_evidence.json"
    receipt_path = DIRECTORY / "qms06_gate_receipt.json"
    if args.check:
        evidence = json.loads(evidence_path.read_text())
        if json.loads(receipt_path.read_text()) != receipt(evidence, args.junit):
            raise SystemExit("QMS-06 receipt mismatch")
        if source_manifest() != evidence["source_hashes"]:
            raise SystemExit("QMS-06 source mismatch")
        if (
            hashlib.sha256(args.extension.read_bytes()).hexdigest()
            != evidence["candidate_build"]["extension_sha256"]
        ):
            raise SystemExit("QMS-06 extension hash mismatch")
        print("QMS-06 executed parity/handoff tests and source/candidate hashes PASS")
        return
    evidence = report(args.extension)
    record = receipt(evidence, args.junit)
    evidence_path.write_text(canonical(evidence) + "\n")
    receipt_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "tests": record["tests"],
                "technical": record["technical"],
                "public_seconds": {
                    k: v["public_seconds"] for k, v in evidence["runs"].items()
                },
                "peak_process_rss_mib": evidence["peak_process_rss_mib"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
