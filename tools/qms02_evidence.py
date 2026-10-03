#!/usr/bin/env python3
"""Small QMS-02 matched-cost evidence; not a sampler economic comparison."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter, process_time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.wfo_samplers import run  # noqa: E402
from tools.qms01_baseline import (  # noqa: E402
    GUIDE,
    MANIFEST,
    RELEASE_SHA,
    digest,
    git,
    resource_snapshot,
    safe,
)


GATES = ("G2-SAMPLER4", "G2-SPACE", "G2-LEGACY", "G2-REPRODUCIBILITY", "G2-COST")
RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")
EVIDENCE = ROOT / "benchmarks/optimization/meta_selection/qms02_sampler_evidence.json"


def tests(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(
        case.find(status) is not None
        for case in cases
        for status in ("failure", "error", "skipped")
    ):
        raise ValueError("QMS-02 requires actual successful tests without skips")
    groups = {
        f"Q2-T{i:02d}": [
            c.attrib["name"]
            for c in cases
            if c.attrib["name"].startswith(f"test_q2_t{i:02d}_")
        ]
        for i in range(1, 9)
    }
    if any(not members for members in groups.values()):
        raise ValueError("missing required Q2 test groups")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest(path.read_bytes()),
        "passed": len(cases),
        "groups": groups,
    }


def measure():
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    output = []
    for recipe in RECIPES:
        repetitions = []
        for repeat in range(4):
            before = resource_snapshot()
            wall, cpu = perf_counter(), process_time()
            _endpoint, result = run(recipe)
            repetitions.append(
                {
                    "repeat": repeat,
                    "warmup": repeat == 0,
                    "wall_seconds": perf_counter() - wall,
                    "cpu_seconds": process_time() - cpu,
                    "before": before,
                    "after": resource_snapshot(),
                    "equity_sha256": hashlib.sha256(
                        result.equity.to_numpy().tobytes()
                    ).hexdigest(),
                }
            )
        wf = result.metadata["walk_forward"]
        output.append(
            {
                "recipe": recipe,
                "repetitions": repetitions,
                "median_warm_ms": statistics.median(
                    r["wall_seconds"] for r in repetitions[1:]
                )
                * 1000,
                "studies": safe(wf["sampler_studies"]),
                "profile": safe(wf["performance_profile"]),
                "params_by_fold": safe(wf["params_by_fold"]),
                "bars": len(result.equity),
            }
        )
    return output


def verify(data):
    if data["budget"] != {
        "recipes": list(RECIPES),
        "bars": 547,
        "attempts_per_study": 12,
        "outer_folds": 2,
        "warmup_repetitions": 1,
        "measured_repetitions": 3,
        "seed": 731,
        "workers": 1,
        "economic_study": False,
    }:
        raise ValueError("evidence budget changed")
    if [row["recipe"] for row in data["measurements"]] != list(RECIPES):
        raise ValueError("missing recipe measurements")
    for row in data["measurements"]:
        if len(row["studies"]) != 2 or len(row["repetitions"]) != 4:
            raise ValueError("missing study/repetitions")
        if len({r["equity_sha256"] for r in row["repetitions"]}) != 1:
            raise ValueError("seeded reruns differ")
        for study in row["studies"]:
            if (
                study["attempts"] != 12
                or len(study["rows"]) != 12
                or study["sampler_wall_seconds"] <= 0
                or study["recipe"] != row["recipe"]
                or study["sampler_class"]
                != {
                    "tpe_legacy": "TPESampler",
                    "tpe_multivariate_group": "TPESampler",
                    "cmaes": "CmaEsSampler",
                    "sobol": "QMCSampler",
                }[row["recipe"]]
                or sum(study["states"].values()) != 12
                or not study["ask_tell_digest"]
            ):
                raise ValueError("unqualified sampler counters")
    if data["baseline_manifest_sha256"] != digest(MANIFEST.read_bytes()) or data[
        "guide_sha256"
    ] != digest((ROOT / GUIDE).read_bytes()):
        raise ValueError("baseline/guide changed after measurement")
    for name, expected in data["source_hashes"].items():
        if digest((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"source changed after measurement: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EVIDENCE)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.verify:
        data = json.loads(args.output.read_text())
    else:
        tracked = (
            git(
                "diff",
                "--name-only",
                "5f8a732",
                "--",
                "src",
                "pyproject.toml",
                "uv.lock",
            )
            .decode()
            .splitlines()
        )
        tracked += [
            "src/quantbt/optimization/parameter_space.py",
            "src/quantbt/optimization/wfo_study.py",
            "examples/wfo_samplers.py",
            "tools/qms02_evidence.py",
            "tests/meta_selection/test_qms02_samplers.py",
            GUIDE,
        ]
        data = {
            "schema": "quantbt-qms02-sampler-evidence-v1",
            "phase_entry_sha": "5f8a732",
            "release_baseline_sha": RELEASE_SHA,
            "baseline_manifest_sha256": digest(MANIFEST.read_bytes()),
            "guide_sha256": digest((ROOT / GUIDE).read_bytes()),
            "branch": git("branch", "--show-current").decode().strip(),
            "versions": {
                name: importlib.metadata.version(name)
                for name in ("quantbt-engine", "quantbt-native", "optuna", "cmaes")
            },
            "source_hashes": {
                name: digest((ROOT / name).read_bytes())
                for name in sorted(set(tracked))
            },
            "budget": {
                "recipes": list(RECIPES),
                "bars": 547,
                "attempts_per_study": 12,
                "outer_folds": 2,
                "warmup_repetitions": 1,
                "measured_repetitions": 3,
                "seed": 731,
                "workers": 1,
                "economic_study": False,
            },
            "measurements": measure(),
            "performance_claim": "MEASURED_COST_ONLY; different recipes have different proposal pools",
            "memory_method": "same-process Linux peak RSS/PSS; cumulative imports/JIT, not isolated recipe RSS or plateau",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, indent=2) + "\n")
    verify(data)
    if args.receipt:
        executed = tests(args.receipt.resolve())
        receipt = {
            "phase": "QMS-02",
            "implementation_status": "COMPLETE",
            "technical_gate": "PASS",
            "required_gates": list(GATES),
            "gates": {**{g: "PASS" for g in GATES}, "G2-OWNER": "PENDING"},
            "tests": executed,
            "evidence_path": str(args.output.resolve().relative_to(ROOT)),
            "evidence_sha256": digest(args.output.read_bytes()),
            "empirical_status": "NOT_ASSESSED",
            "owner_review": {"status": "PENDING", "decision_ref": None},
            "can_start_next_phase": False,
            "scope_limits": [
                "Sobol conditional space fails preflight",
                "categorical/conditional/constrained centroid fails preflight",
                "exact resume only with the same owned in-process study; no new persistent sampler checkpoint",
            ],
            "open_phase_blockers": [],
        }
        path = ROOT / "benchmarks/optimization/meta_selection/qms02_gate_receipt.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("QMS-02 evidence verification: PASS")


if __name__ == "__main__":
    main()
