"""Retain source-bound MET-01 tests/links/resource proof without native builds."""

from __future__ import annotations

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
LANE = ROOT / "docs/metrics/evidence/met01"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = json.loads((LANE / "baseline.json").read_text())
    before = shutil.disk_usage(ROOT)
    inode_before = os.statvfs(ROOT).f_favail
    budget = baseline["incremental_disk_budget_bytes"]
    if before.free < budget + 5 * 1024 ** 3:
        raise RuntimeError("disk headroom below registered budget")
    if inode_before < 512:
        raise RuntimeError("inode budget unavailable")
    changed = [p for p, value in baseline["protected_sources"].items() if digest(ROOT / p) != value]
    if changed:
        raise RuntimeError(f"protected production changed: {changed}")
    run = LANE / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
    run.mkdir()
    census = {}
    expression = re.compile(r"\b(?:full_report|compute_performance_metrics|num_trades|trade_count|turnover|sharpe|sortino|profit_factor|drawdown|expectancy|MetricContractV2)\b")
    for path in baseline["protected_sources"]:
        if path.endswith((".py", ".rs")):
            references = sorted(set(expression.findall((ROOT / path).read_text())))
            if references:
                census[path] = references
    (run / "source-census.json").write_text(json.dumps(census, indent=2, sort_keys=True) + "\n")
    steps = []
    scratch_path = None
    with tempfile.TemporaryDirectory(prefix="quantbt-met01-") as temporary:
        scratch_path = temporary
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"),
                           MPLBACKEND="Agg", MPLCONFIGDIR=temporary,
                           OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                           NUMBA_NUM_THREADS="1", NUMBA_CACHE_DIR=temporary)
        commands = [
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/metrics",
             "tests/test_metrics_intraday_scope.py", f"--basetemp={temporary}/pytest", f"--junitxml={run / 'pytest.xml'}"],
            [sys.executable, "tools/check_docs_links.py", "--file", "upgrade/implement.md",
             "--file", "docs/metrics/REPORTING_CONTRACT_V1.md", "--file", "docs/metrics/INVENTORY.md", "--check-anchors"],
            ["git", "diff", "--check"],
        ]
        for i, command in enumerate(commands, 1):
            print(f"[{i}] {' '.join(command)}", flush=True)
            start = time.perf_counter()
            result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
            log = run / f"step-{i}.log"
            log.write_text(result.stdout + result.stderr)
            steps.append(dict(command=command, exit_code=result.returncode,
                              wall_seconds=time.perf_counter() - start, log=log.relative_to(ROOT).as_posix(), sha256=digest(log)))
            print(result.stdout + result.stderr, flush=True)
            if result.returncode:
                break
    after = shutil.disk_usage(ROOT)
    unchanged = all(digest(ROOT / p) == value for p, value in baseline["protected_sources"].items())
    groups = {f"MET01-T{i:02}": {"passed": 0, "failed": 0, "skipped": 0} for i in range(1, 9)}
    tests = []
    if (run / "pytest.xml").exists():
        for test in ET.parse(run / "pytest.xml").iter("testcase"):
            status = "failed" if test.find("failure") is not None or test.find("error") is not None else "skipped" if test.find("skipped") is not None else "passed"
            tests.append(dict(name=test.attrib["name"], status=status))
            for number in set(re.findall(r"_t(\d{2})(?=_|\b)", test.attrib["name"])):
                groups[f"MET01-T{number}"][status] += 1
    # T08 additionally requires the external links/whitespace and source gates.
    passed = len(steps) == len(commands) and all(s["exit_code"] == 0 for s in steps) and unchanged
    passed = passed and all(g["passed"] > 0 and not g["failed"] and not g["skipped"] for g in groups.values())
    retained_bytes = sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
    try:
        native_distribution = metadata.distribution("quantbt-native")
        native_files = {str(p): digest(Path(native_distribution.locate_file(p))) for p in native_distribution.files if str(p).endswith(".so")}
    except metadata.PackageNotFoundError:
        native_files = {}
    versions = {}
    for name in ("numpy", "pandas", "pytest", "quantstats", "quantbt-engine", "quantbt-native"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    logs_preserved = all(digest(ROOT / step["log"]) == step["sha256"] for step in steps)
    passed = passed and logs_preserved and retained_bytes <= budget and not Path(scratch_path).exists()
    receipt = dict(
        schema="quantbt.metrics.qualification.v1", phase="MET-01",
        baseline_sha256=digest(LANE / "baseline.json"),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        changed_paths=subprocess.check_output(["git", "status", "--short"], cwd=ROOT).decode().splitlines(),
        technical_gate="PASS" if passed else "FAIL", groups=groups,
        test_counts={status: sum(t["status"] == status for t in tests) for status in ("passed", "failed", "skipped")},
        steps=steps, protected_files=len(baseline["protected_sources"]), protected_unchanged=unchanged,
        source_census_sha256=digest(run / "source-census.json"),
        runtime=dict(python=sys.version, source_package="src/quantbt (tests/conftest.py precedence)",
                     installed_tooling_versions=versions,
                     native_extension_files=native_files, native_execution_invoked=False),
        inputs={str(p.relative_to(ROOT)): digest(p) for parent in (ROOT / "tests/metrics", ROOT / "tools/metrics") for p in parent.rglob("*") if p.is_file() and "__pycache__" not in str(p)},
        schema_sha256=digest(ROOT / "src/quantbt/metrics/report_contracts.py"),
        performance="NOT_MEASURED; no production reducer or execution changes",
        empirical_status="NOT_ASSESSED; public synthetic math fixtures only",
        owner_review="PENDING_DEFINITION_ACCEPTANCE", met02_authorized=False,
        cleanup=dict(scratch_path=scratch_path, scratch_removed=not Path(scratch_path).exists(),
                     protected_hashes_preserved=unchanged, retained_run_bytes=retained_bytes,
                     retained_log_hashes_preserved=logs_preserved,
                     disk_before_free=before.free, disk_after_free=after.free,
                     disk_free_change=after.free - before.free,
                     inode_before_free=inode_before, inode_after_free=os.statvfs(ROOT).f_favail,
                     budget_bytes=budget, native_build=False, environments_deleted=[]),
    )
    (run / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"run": str(run.relative_to(ROOT)), "technical_gate": receipt["technical_gate"], "tests": receipt["test_counts"], "protected_unchanged": unchanged}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
