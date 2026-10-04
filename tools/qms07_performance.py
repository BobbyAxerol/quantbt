"""Reproducible QMS-07 paired measurements and strict evidence verification."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
import xml.etree.ElementTree as ET

import numpy as np

from quantbt.optimization.meta_selection.common import canonical
from quantbt.optimization.meta_selection.numerics import NumericRuntime
from tools.build_qms06_candidate import OUTPUT as OLD_OUTPUT, load as load_old
from tools.build_qms07_candidate import OUTPUT, load
from tools.qms04_ridge import timed
from tools.qms07_corpus import replay, compare_sequences

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "benchmarks/optimization/meta_selection"
ENTRY = "eb167a4"
GROUPS = tuple(f"q7_t0{i}" for i in range(1, 9))


def source_manifest():
    paths = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "src/quantbt",
            "rust",
            "tools/qms07*",
            "tools/build_qms07_candidate.py",
            "tests/meta_selection",
            "pyproject.toml",
            "uv.lock",
            "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(set(paths))}


def extension(directory):
    paths = list(directory.glob("_quantbt_native*.so"))
    if len(paths) != 1:
        raise ValueError(f"missing/ambiguous isolated extension: {directory}")
    return paths[0]


def run_worker(source, mode, candidate, *, profile=False, memory=False):
    args = [
        sys.executable,
        str(ROOT / "tools/qms07_worker.py"),
        "--source-tree",
        str(source),
        "--mode",
        mode,
    ]
    if mode == "prepared":
        directory = OLD_OUTPUT if candidate == "entry" else OUTPUT
        args += [
            "--extension",
            str(extension(directory)),
            "--version",
            "0.4.3.dev2" if candidate == "entry" else "0.4.3.dev3",
        ]
    if profile:
        args.append("--profile")
    if memory:
        args.append("--memory")
    if mode == "disabled" and not profile:
        args += ["--aggregate", "3"]
    env = dict(
        os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"
    )
    env.pop("PYTHONPATH", None)
    started = perf_counter()
    result = subprocess.run(args, cwd=source, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"worker failed: {args}\n{result.stdout}\n{result.stderr}")
    document = json.loads(result.stdout.splitlines()[-1])
    document["process_seconds"] = perf_counter() - started
    return document


def compare_public(a, b):
    assert a["history_membership"] == b["history_membership"], (
        "permitted origins/labels/weights changed"
    )
    assert a["trace"] == b["trace"], "sequential proposals/objectives/stopping changed"
    assert a["arrays_sha256"] == b["arrays_sha256"], "financial outputs changed"
    assert a["trial_rows"] == b["trial_rows"]
    assert a["candidate_rows"] == b["candidate_rows"]
    assert a["evidence"]["observer_attempts"] == b["evidence"]["observer_attempts"]
    for x, y in zip(
        a["evidence"].get("rows", ()), b["evidence"].get("rows", ()), strict=True
    ):
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
            assert x[key] == y[key], key
        for p, q in zip(x["pool"], y["pool"], strict=True):
            for key in (
                "candidate_id",
                "status",
                "count",
                "activity",
                "economics_id",
                "input_signature",
            ):
                assert p[key] == q[key], key
            for key in ("raw_sharpe", "std", "first_mark", "objective"):
                np.testing.assert_allclose(p[key], q[key], rtol=1e-10, atol=1e-10)
        for p, q in zip(x["predictions"], y["predictions"], strict=True):
            assert (
                p["candidate_id"] == q["candidate_id"]
                and p["eligible"] == q["eligible"]
            )
            for key in ("yhat", "qhat", "distance"):
                np.testing.assert_allclose(p[key], q[key], rtol=1e-9, atol=1e-10)


def matrix_measurements(old, new):
    cases = []
    for n, d, p in (
        (180, 8, 64),
        (4096, 8, 600),
        (4096, 24, 600),
        (512, 64, 600),
        (16384, 8, 2000),
    ):
        rng = np.random.default_rng(704 + n + d + p)
        v, y, w = (
            rng.normal(size=(n, d)),
            rng.normal(size=n),
            rng.uniform(0.1, 1, size=n),
        )
        current, delta = rng.normal(size=(p, d)), rng.normal(size=p)
        reference = NumericRuntime(native_policy="reference", work_cache=False)
        expected = reference.fit(v, y, w, 10)
        costs = {}
        for label, module in (
            ("entry_rust", old),
            ("current_rust", new),
            ("numpy", None),
        ):
            started = perf_counter()
            runtime = NumericRuntime(
                native_policy="require" if module else "reference",
                native_module=module,
                work_cache=False,
            )
            qualification = perf_counter() - started
            actual = runtime.fit(v, y, w, 10)
            for x, z in zip(actual, expected, strict=True):
                np.testing.assert_allclose(x, z, rtol=1e-9, atol=1e-10)
            rank = runtime.rank(current, actual[2], delta)
            wanted = reference.rank(current, expected[2], delta)
            for x, z in zip(rank, wanted, strict=True):
                np.testing.assert_allclose(x, z, rtol=1e-9, atol=1e-10)
            costs[label] = {
                "qualification_seconds": qualification,
                "fit": timed(lambda: runtime.fit(v, y, w, 10), repeats=15),
                "rank": timed(
                    lambda: runtime.rank(current, actual[2], delta), repeats=15
                ),
                "metadata": dict(runtime.metadata),
            }
        cases.append(
            {
                "N": n,
                "d": d,
                "P": p,
                "costs": costs,
                "parity": True,
                "input_sha256": sha256(
                    v.tobytes()
                    + y.tobytes()
                    + w.tobytes()
                    + current.tobytes()
                    + delta.tobytes()
                ).hexdigest(),
                "fit_owned_bytes_per_native_call": v.nbytes + y.nbytes + w.nbytes,
                "rank_owned_bytes_per_native_call": current.nbytes
                + expected[2].nbytes
                + delta.nbytes,
                "dense_weight_matrix_bytes": 0,
                "disposition": "qualified Rust when requested; NumPy remains measured BLAS reference, no universal speed claim",
            }
        )
    return cases


def measure(entry_tree):
    paths = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            ENTRY,
            "src",
            "tools",
            "examples",
            "tests/meta_selection",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    for path in paths:
        expected = subprocess.check_output(
            ["git", "show", ENTRY + ":" + path], cwd=ROOT
        )
        if (entry_tree / path).read_bytes() != expected:
            raise ValueError("entry archive does not match approved baseline: " + path)
    old, new = load_old(extension(OLD_OUTPUT)), load(extension(OUTPUT))
    arms = {}
    for mode, pairs in (("disabled", 8), ("meta", 4), ("prepared", 4)):
        samples = {"entry": [], "current": []}
        for pair in range(pairs):
            # Alternate paired fresh processes; no best-sample selection.
            order = ("entry", "current") if pair % 2 == 0 else ("current", "entry")
            for arm in order:
                samples[arm].append(
                    run_worker(entry_tree if arm == "entry" else ROOT, mode, arm)
                )
            compare_public(samples["entry"][-1], samples["current"][-1])
        summary = {}
        for arm, rows in samples.items():
            walls = [r["per_run_wall_seconds"] for r in rows]
            summary[arm] = {
                "p50_seconds": float(np.median(walls)),
                "p95_seconds": float(np.quantile(walls, 0.95)),
            }
        ratios = {
            q: summary["current"][q] / summary["entry"][q] - 1
            for q in ("p50_seconds", "p95_seconds")
        }
        arms[mode] = {
            "samples": samples,
            "summary": summary,
            "relative_change": ratios,
            "parity": True,
        }
    a = replay(NumericRuntime(native_policy="reference", work_cache=False))
    b = replay(NumericRuntime(native_policy="require", native_module=new), resume=True)
    compare_sequences(a, b)
    tie_reference = replay(
        NumericRuntime(native_policy="reference", work_cache=False), tie_boundary=True
    )
    tie_native = replay(
        NumericRuntime(native_policy="require", native_module=new),
        resume=True,
        tie_boundary=True,
    )
    compare_sequences(tie_reference, tie_native)
    return {
        "schema": "qms07-performance-evidence-v1",
        "entry_commit": ENTRY,
        "source_hashes": source_manifest(),
        "platform": platform.platform(),
        "python": sys.version,
        "threads": {
            k: os.environ.get(k)
            for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
        "fixture": {
            "bars": 850,
            "folds": 6,
            "attempted_trials_per_fold": 6,
            "seed": 731,
            "workers": 1,
            "support_override": 1,
            "default_min_origins": 12,
            "economic_acceptance": False,
        },
        "candidate_build": json.loads((OUTPUT / "build_receipt.json").read_text()),
        "arms": arms,
        "chronological": {"reference": a, "rust_resume": b, "parity": True},
        "chronological_tie": {
            "reference": tie_reference,
            "rust_resume": tie_native,
            "parity": True,
        },
        "matrices": matrix_measurements(old, new),
        "profiles": {
            arm: run_worker(
                entry_tree if arm == "entry" else ROOT, "prepared", arm, profile=True
            )
            for arm in ("entry", "current")
        },
        "memory_plateau": run_worker(ROOT, "prepared", "current", memory=True),
        "disabled_gate": {
            "working_p50_budget": 0.03,
            "working_p95_budget": 0.05,
            "owner_accepted": False,
            "status": "MEASURED_OWNER_BUDGET_PENDING",
            "working_targets_pass": arms["disabled"]["relative_change"]["p50_seconds"]
            <= 0.03
            and arms["disabled"]["relative_change"]["p95_seconds"] <= 0.05,
        },
        "empirical": "NOT_ASSESSED",
        "pilot": {
            "protocol": "exploratory single-run/process under concurrent local tests; not promotion evidence",
            "disabled_relative_p50": 0.064855836,
            "disposition": "registered final aggregate/no-competing-test protocol before final outcomes",
        },
        "owner_review": "PENDING",
        "publication": "none; isolated candidate only",
    }


def validate(evidence, junit):
    if evidence["source_hashes"] != source_manifest():
        raise ValueError("QMS07 source manifest changed")
    proof = evidence["candidate_build"]
    if sha256(extension(OUTPUT).read_bytes()).hexdigest() != proof["extension_sha256"]:
        raise ValueError("QMS07 extension changed")
    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if any(int(s.get(k, 0)) for s in suites for k in ("failures", "errors", "skipped")):
        raise ValueError("QMS07 regression contains failures/errors/skips")
    groups = {
        g: sum(g in c.get("name", "") for c in root.iter("testcase")) for g in GROUPS
    }
    if not all(groups.values()):
        raise ValueError("missing required Q7 groups")
    for arm in evidence["arms"].values():
        for a, b in zip(
            arm["samples"]["entry"], arm["samples"]["current"], strict=True
        ):
            compare_public(a, b)
    plateau = evidence["memory_plateau"]["plateau"]
    if len(plateau) != 20 or any(
        r["retained_cache_bytes"] > 8_000_000 for r in plateau
    ):
        raise ValueError("QMS07 memory retention budget violated")
    for field in ("rss_mib", "pss_mib"):
        if max(r[field] for r in plateau[5:]) - min(r[field] for r in plateau[5:]) > 8:
            raise ValueError("QMS07 fixed-workspace plateau failed")
    disabled = evidence["arms"]["disabled"]
    targets = (
        disabled["relative_change"]["p50_seconds"] <= 0.03
        and disabled["relative_change"]["p95_seconds"] <= 0.05
    )
    if targets != evidence["disabled_gate"]["working_targets_pass"]:
        raise ValueError("QMS07 disabled budget claim mismatch")
    if any(
        r["logical_runs"] != 3 or r["evidence"]["observer_attempts"]
        for rows in disabled["samples"].values()
        for r in rows
    ):
        raise ValueError("QMS07 disabled work changed")
    compare_sequences(
        evidence["chronological"]["reference"], evidence["chronological"]["rust_resume"]
    )
    compare_sequences(
        evidence["chronological_tie"]["reference"],
        evidence["chronological_tie"]["rust_resume"],
    )
    return {
        "schema": "qms07-gate-receipt-v1",
        "technical_gate": "PASS" if targets else "BLOCKED_DISABLED_WORKING_BUDGET",
        "evidence_sha256": sha256(canonical(evidence).encode()).hexdigest(),
        "junit_sha256": sha256(Path(junit).read_bytes()).hexdigest(),
        "tests": sum(int(s.get("tests", 0)) for s in suites),
        "groups": groups,
        "owner_review": "PENDING",
        "disabled_gate": evidence["disabled_gate"],
        "empirical": "NOT_ASSESSED",
        "release_promoted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-tree", type=Path)
    parser.add_argument("--junit", type=Path, default=DIRECTORY / "qms07_tests.xml")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = DIRECTORY / "qms07_performance_evidence.json"
    receipt = DIRECTORY / "qms07_gate_receipt.json"
    if args.check:
        evidence = json.loads(path.read_text())
        if validate(evidence, args.junit) != json.loads(receipt.read_text()):
            raise ValueError("QMS07 receipt mismatch")
        print("QMS07 evidence/source/binary/JUnit/chronological/public parity verified")
        return
    if args.entry_tree is None:
        raise ValueError("provide archived entry source tree eb167a4")
    evidence = measure(args.entry_tree)
    from quantbt.optimization.meta_selection.common import wire

    path.write_text(json.dumps(wire(evidence), sort_keys=True, indent=2) + "\n")
    print(f"wrote {path}")
    if args.junit.is_file():
        receipt.write_text(
            json.dumps(validate(evidence, args.junit), sort_keys=True, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
