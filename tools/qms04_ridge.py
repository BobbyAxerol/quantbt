"""Executed QMS-04 receipt: actual Rust batches, original-result fit and costs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
from time import perf_counter
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from quantbt.optimization.meta_selection.artifacts import dumps_model, loads_model
from quantbt.optimization.meta_selection.common import canonical, wire
from quantbt.optimization.meta_selection.descriptors import DescriptorSchema
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import RidgeLearner, RidgeSettings
from quantbt.optimization.meta_selection.numerics import (
    NumericRuntime,
    reference_fit,
    solution_diagnostics,
)
from tools.build_qms04_candidate import load_candidate
from tools.qms03_history import financial_fixture

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
ENTRY = "ac3bd15"


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
            "poetry.lock",
            "tools/qms04_ridge.py",
            "tools/build_qms04_candidate.py",
            "tools/qms03_history.py",
            "tools/qms01_baseline.py",
            "examples/wfo_meta_ridge.py",
            "tests/meta_selection",
            "tests/meta_selection/test_qms04_ridge.py",
            "tests/meta_selection/test_qms03_engine.py",
            "tests/meta_selection/test_qms02_samplers.py",
            "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(names))
    }


def timed(call, repeats=15):
    call()  # Explicit warm-up, no ignored measured iteration.
    times = []
    for _ in range(repeats):
        started = perf_counter()
        call()
        times.append((perf_counter() - started) * 1000)
    return {
        "samples": repeats,
        "median_ms": statistics.median(times),
        "p95_ms": float(np.quantile(times, 0.95)),
    }


def matrix_costs(module):
    cases = []
    for n, d, p in ((180, 8, 64), (4096, 8, 600), (4096, 24, 600), (16384, 8, 2000)):
        rng = np.random.default_rng(704 + n + d + p)
        v, y, w = (
            rng.normal(size=(n, d)),
            rng.normal(size=n),
            rng.uniform(0.1, 1, size=n),
        )
        current, delta = rng.normal(size=(p, d)), rng.normal(size=p)
        before = perf_counter()
        native = NumericRuntime(native_policy="require", native_module=module)
        qualification_ms = (perf_counter() - before) * 1000
        reference = NumericRuntime(native_policy="reference")
        result = native.fit(v, y, w, 10.0)
        expected = reference.fit(v, y, w, 10.0)
        for a, e in zip(result, expected):
            if not np.allclose(a, e, rtol=1e-9, atol=1e-10):
                raise AssertionError("fixed-matrix fit parity failed")
        primary = native.rank(current, result[2], delta)
        secondary = reference.rank(current, expected[2], delta)
        if any(
            not np.allclose(a, e, rtol=1e-9, atol=1e-10)
            for a, e in zip(primary, secondary)
        ):
            raise AssertionError("fixed-matrix prediction parity failed")
        native_fit = timed(lambda: native.fit(v, y, w, 10.0))
        reference_fit_t = timed(lambda: reference.fit(v, y, w, 10.0))
        native_rank = timed(lambda: native.rank(current, result[2], delta))
        reference_rank = timed(lambda: reference.rank(current, expected[2], delta))

        def certified_fit():
            g, b, beta = native.fit(v, y, w, 10.0)
            solution_diagnostics(g, b, beta, native.limits)
            rg, rb, rbeta = reference_fit(v, y, w, 10.0, native.limits)
            if not np.allclose(beta, rbeta, rtol=1e-9, atol=1e-10):
                raise AssertionError("certified fit parity")

        def certified_reference():
            g, b, beta = reference.fit(v, y, w, 10.0)
            solution_diagnostics(g, b, beta, reference.limits)

        full_native = timed(certified_fit)
        full_reference = timed(certified_reference)
        cases.append(
            {
                "N": n,
                "d": d,
                "P": p,
                "data_seed": 704 + n + d + p,
                "input_digest": hashlib.sha256(
                    v.tobytes()
                    + y.tobytes()
                    + w.tobytes()
                    + current.tobytes()
                    + delta.tobytes()
                ).hexdigest(),
                "qualification_ms": qualification_ms,
                "native_primary_fit": native_fit,
                "numpy_reference_fit": reference_fit_t,
                "native_primary_rank": native_rank,
                "numpy_reference_rank": reference_rank,
                "native_certified_fit_including_reference": full_native,
                "numpy_certified_fit": full_reference,
                "fit_input_owned_bytes_per_call": v.nbytes + y.nbytes + w.nbytes,
                "rank_input_owned_bytes_per_call": current.nbytes
                + result[2].nbytes
                + delta.nbytes,
                "dense_weight_matrix_bytes": 0,
                "fit_numeric_output_bytes": d * d * 8 + 2 * d * 8,
                "native_blocks": wire(native.metadata),
                "parity": True,
                "disposition": "candidate_numeric_measurement_only; no public auto promotion",
                "numba": "not_used; no duplicated implementation/JIT dependency introduced",
            }
        )
    return cases


def engine_fit(module, centroid):
    evidence, revisions, result = financial_fixture(centroid=centroid)
    history = MetaHistory()
    for revision in revisions:
        history.append(revision)
    cutoff = max(r.revision_available_at for r in revisions) + pd.Timedelta(seconds=1)
    view = history.snapshot(
        family_id=revisions[0].task.family.family_id,
        authorized_corpora=(revisions[0].task.corpus_id,),
        outcome_origins=("synthetic_counterfactual",),
        research_exposures=("research_only",),
        information_as_of=cutoff,
    )
    schema = DescriptorSchema({"window": (3, 31, 2)})
    settings = RidgeSettings(min_matured_origins=2)
    runtime = NumericRuntime(native_policy="require", native_module=module)
    before = perf_counter()
    fitted = RidgeLearner(settings=settings, runtime=runtime).fit(
        schema, view, fit_completed_at=cutoff + pd.Timedelta(seconds=1)
    )
    elapsed = (perf_counter() - before) * 1000
    expected = RidgeLearner(
        settings=settings, runtime=NumericRuntime(native_policy="reference")
    ).fit(schema, view, fit_completed_at=fitted.model.fit_completed_at)
    if not np.allclose(
        fitted.model.coefficients, expected.model.coefficients, rtol=1e-9, atol=1e-10
    ):
        raise AssertionError("original-engine native fit parity")
    restored = loads_model(
        dumps_model(fitted.model),
        expected_model_id=fitted.model.model_id,
        available_as_of=fitted.model.fit_completed_at,
    )
    if restored.model_id != fitted.model.model_id:
        raise AssertionError("original-engine artifact restore parity")
    return {
        "centroid": centroid,
        "origin_count": view.origin_count,
        "rows": len(view.training_rows),
        "model_id": fitted.model.model_id,
        "training_snapshot_id": view.snapshot_id,
        "revision_references": wire(fitted.model.revision_references),
        "fit_ms_including_whole_reference_verification": elapsed,
        "fit_backend": wire(runtime.metadata),
        "coefficients": wire(fitted.model.coefficients),
        "raw_unit_coefficients": wire(fitted.model.raw_unit_coefficients),
        "diagnostics": wire(fitted.model.diagnostics),
        "native_reference_parity": True,
        "bundle_restore": True,
        "selection_clock": "fit only after both original forward revisions mature; no retrospective earlier decision using them",
        "market": "original QuantBT engine on synthetic OHLCV, not real-market edge",
        "financial_observer_attempts": evidence["observer_attempts"],
        "financial_observer_failures": evidence["observer_failures"],
        "fitter_extra_financial_calls": 0,
        "public_selector_activated": False,
        "final_native_params": wire(result.best_trial["params"]),
    }


def report(extension):
    module = load_candidate(extension)
    import _quantbt_native as baseline

    if baseline.version() != "0.4.2" or hasattr(baseline, "qms_numeric_descriptor_v1"):
        raise AssertionError("published financial baseline must remain unchanged")
    return {
        "schema": "qms04-ridge-evidence-v1",
        "phase": "QMS-04",
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
        "installed_baseline": baseline.version(),
        "matrices": matrix_costs(module),
        "original_engine_medoid": engine_fit(module, False),
        "original_engine_centroid": engine_fit(module, True),
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / 1024,
        "rss_scope": "absolute same-process peak including financial imports/JIT; not native delta/plateau gate",
        "empirical": "NOT_ASSESSED",
        "public_wfo_integration": "QMS-05 not authorized",
        "version_policy": "private feature-gated 0.4.3.dev1 candidate; no overwrite/publish/core compatibility change",
    }


def receipt(evidence, junit):
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    groups = {
        f"Q4-T{i:02d}": sum(f"q4_t{i:02d}" in c.attrib.get("name", "") for c in cases)
        for i in range(1, 9)
    }
    if not all(groups.values()) or any(
        any(c.find(x) is not None for x in ("failure", "error", "skipped"))
        for c in cases
    ):
        raise AssertionError(
            "QMS-04 test groups must execute without failure/error/skip"
        )
    if any(not c["parity"] for c in evidence["matrices"]) or any(
        not evidence[k]["native_reference_parity"]
        or not evidence[k]["bundle_restore"]
        or evidence[k]["financial_observer_failures"]
        for k in ("original_engine_medoid", "original_engine_centroid")
    ):
        raise AssertionError("QMS-04 native/original-engine evidence missing or failed")
    return {
        "schema": "qms04-gate-receipt-v1",
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
                "G4-MATH",
                "G4-POLICY",
                "G4-SERIALIZATION",
                "G4-SUPPORT",
                "G4-RESOURCE",
            )
        },
        "G4-OWNER": "PENDING",
        "empirical": "NOT_ASSESSED",
        "performance": "MEASURED_BLOCKS_NO_PUBLIC_PROMOTION",
        "advancement": "QMS-05 requires separate owner approval",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    evidence_path = DIRECTORY / "qms04_ridge_evidence.json"
    receipt_path = DIRECTORY / "qms04_gate_receipt.json"
    if args.check:
        evidence = json.loads(evidence_path.read_text())
        record = json.loads(receipt_path.read_text())
        if (
            record != receipt(evidence, args.junit)
            or evidence["source_hashes"] != source_manifest()
        ):
            raise SystemExit("QMS-04 evidence/test/source mismatch")
        if (
            args.extension
            and hashlib.sha256(args.extension.read_bytes()).hexdigest()
            != evidence["candidate_build"]["extension_sha256"]
        ):
            raise SystemExit("candidate extension hash mismatch")
        print("QMS-04 executed receipt, source hashes and candidate PASS")
        return
    if args.extension is None:
        raise SystemExit(
            "--extension is required for actual native evidence; no missing-capability success"
        )
    evidence = report(args.extension)
    evidence_path.write_text(canonical(evidence) + "\n")
    receipt_path.write_text(
        json.dumps(receipt(evidence, args.junit), indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "technical": receipt(evidence, args.junit)["technical"],
                "matrices": len(evidence["matrices"]),
                "medoid_rows": evidence["original_engine_medoid"]["rows"],
                "centroid_rows": evidence["original_engine_centroid"]["rows"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
