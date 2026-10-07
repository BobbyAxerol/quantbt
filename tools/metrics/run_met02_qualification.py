"""Local, source-bound reporting qualification; no native builds or publication."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
LANE = ROOT / "docs/metrics/evidence/met02"
BUDGET = 256 * 1024 ** 2


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_baseline():
    path = LANE / "baseline.json"
    if path.exists():
        return json.loads(path.read_text())
    prior = json.loads((ROOT / "docs/metrics/evidence/met01/baseline.json").read_text())
    hashes = dict(prior["protected_sources"])
    for name in ("src/quantbt/metrics/report_contracts.py", "tests/metrics/reference_oracle.py",
                 "tests/metrics/fixtures/manual.json"):
        hashes[name] = digest(ROOT / name)
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError("MET-01 protected sources changed before MET-02")
    baseline = dict(phase="MET-02", protected_sources=hashes,
        parent_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        met01_receipt_sha256=digest(ROOT / "docs/metrics/evidence/met01/run-20261007T183109306830Z/receipt.json"),
        disk_budget_bytes=BUDGET, inode_budget=1024, native_build=False,
        initial_account_test=dict(passed=62, failed=0, wall_seconds=12.73,
                                 reason="initial exploratory run; source-bound rerun retained below"))
    LANE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, sort_keys=True, indent=2) + "\n")
    return baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("account", "ledger", "full"), default="full")
    args = parser.parse_args()
    baseline = capture_baseline()
    before = shutil.disk_usage(ROOT)
    inode_before = os.statvfs(ROOT).f_favail
    if before.free < BUDGET + 5 * 1024 ** 3 or inode_before < 1024:
        raise RuntimeError("registered disk/inode budget unavailable")
    if any(digest(ROOT / p) != value for p, value in baseline["protected_sources"].items()):
        raise RuntimeError("protected source bytes changed")
    run = LANE / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
    run.mkdir()
    with tempfile.TemporaryDirectory(prefix="quantbt-met02-") as temporary:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"),
            MPLBACKEND="Agg", MPLCONFIGDIR=temporary, NUMBA_CACHE_DIR=temporary,
            OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
        tests = ["tests/metrics/test_account_reducers.py", "tests/metrics/test_boundaries.py"]
        if args.stage == "ledger":
            tests.append("tests/metrics/test_ledger_reducers.py")
        if args.stage == "full":
            tests = ["tests/metrics", "tests/test_metrics_intraday_scope.py",
                     "tests/test_phase49a_walkforward_schedules.py"]
        commands = [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests,
                     f"--basetemp={temporary}/pytest", f"--junitxml={run / 'pytest.xml'}"],
                    ["git", "diff", "--check"]]
        if args.stage == "full":
            commands += [[sys.executable, "tools/metrics/benchmark_met02.py", "--output", str(run / "benchmark.json")],
                         [sys.executable, "tools/check_docs_links.py", "--file", "upgrade/implement.md",
                          "--file", "docs/metrics/MET02_REPORT.md", "--check-anchors"]]
        steps = []
        for i, command in enumerate(commands, 1):
            print(f"[{i}] {' '.join(command)}", flush=True)
            start = time.perf_counter()
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            log = run / f"step-{i}.log"
            log.write_text(result.stdout + result.stderr)
            steps.append(dict(command=command, exit_code=result.returncode,
                seconds=time.perf_counter() - start, log=log.relative_to(ROOT).as_posix(), sha256=digest(log)))
            print(result.stdout + result.stderr, flush=True)
            if result.returncode:
                break
    unchanged = all(digest(ROOT / p) == value for p, value in baseline["protected_sources"].items())
    groups = {f"MET02-T{i:02}": dict(passed=0, failed=0, skipped=0) for i in range(1, 11)}
    counts = dict(passed=0, failed=0, skipped=0)
    if (run / "pytest.xml").exists():
        for case in ET.parse(run / "pytest.xml").iter("testcase"):
            status = "failed" if case.find("failure") is not None or case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
            counts[status] += 1
            for number in set(re.findall(r"_t(\d{2})(?=_|\b)", case.attrib["name"])):
                if f"MET02-T{number}" in groups:
                    groups[f"MET02-T{number}"][status] += 1
    required = range(1, 11) if args.stage == "full" else (1, 2, 3, 8, 10)
    retained = sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
    passed = len(steps) == len(commands) and all(s["exit_code"] == 0 for s in steps) and unchanged
    passed = passed and not counts["failed"] and not counts["skipped"]
    passed = passed and all(groups[f"MET02-T{i:02}"]["passed"] for i in required)
    passed = passed and retained <= BUDGET and not Path(temporary).exists()
    inputs = {}
    for directory in ("src/quantbt/metrics/reporting", "tests/metrics", "tools/metrics"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                inputs[path.relative_to(ROOT).as_posix()] = digest(path)
    versions = {name: metadata.version(name) for name in ("numpy", "pandas", "numba", "pytest", "quantstats", "quantbt-engine", "quantbt-native")}
    after = shutil.disk_usage(ROOT)
    receipt = dict(phase="MET-02", stage=args.stage, technical_gate="PASS" if passed else "FAIL",
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        baseline_sha256=digest(LANE / "baseline.json"), test_counts=counts, groups=groups,
        protected_files=len(baseline["protected_sources"]), protected_unchanged=unchanged,
        inputs=inputs, steps=steps, runtime=dict(python=sys.version, versions=versions,
            package_source="src/quantbt", native_reporting_v1="NOT_IMPLEMENTED; V2 is not V1",
            native_build=False, thread_budget=1), public_integration="MET-03 NOT_STARTED",
        cleanup=dict(scratch_path=temporary, scratch_removed=not Path(temporary).exists(),
            retained_run_bytes=retained, log_hashes_preserved=all(digest(ROOT / s["log"]) == s["sha256"] for s in steps),
            free_bytes_before=before.free, free_bytes_after=after.free,
            free_byte_change=after.free - before.free, free_inodes_before=inode_before,
            free_inodes_after=os.statvfs(ROOT).f_favail, budget_bytes=BUDGET, protected_preserved=unchanged))
    (run / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(dict(run=str(run.relative_to(ROOT)), technical_gate=receipt["technical_gate"], tests=counts)), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
