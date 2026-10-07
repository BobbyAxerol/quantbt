"""Source/installed local MET-03 proof with preregistered, narrowly owned scratch."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.qms08_package import build_tool, stage_source
from tools.qms_pre06_contract import artifact_source, core_inventory, native_reuse
from tools.qms_pre06_package import NATIVE, PINNED

BUDGET = 3*1024**3
EXTRAS = ("matplotlib==3.10.9", "seaborn==0.13.2", "quantstats==0.0.81")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("source", "package"), required=True)
    parser.add_argument("--allow-download", action="store_true", help="Populate missing public dependency wheels; no package upload")
    parser.add_argument("--performance", action="store_true", help="Also compare completed reporting against owner recheck baseline")
    args = parser.parse_args()
    before = shutil.disk_usage(ROOT).free
    inodes = os.statvfs(ROOT).f_favail
    if before < BUDGET+5*1024**3 or inodes < 20000:
        raise RuntimeError("registered disk/inode reserve unavailable")
    lane = ROOT / "docs/metrics/evidence/met03" / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
    lane.mkdir(parents=True)
    registration = dict(phase="MET-03", stage=args.stage, checkout=str(ROOT), core_inventory=core_inventory(ROOT/"src/quantbt"),
        native_reuse=native_reuse(NATIVE), budget_bytes=BUDGET, inode_budget=20000, worker_rss_mib=2048,
        threads=1, warmup=1, repeats=5, sizes=[2000, 100000, 1000000], source_parent="864b38a",
        benchmark_cells=12, financial_or_scientific_changes=False, native_rebuilt=False, publication=False)
    if args.performance:
        registration["performance_baseline"] = "24ad469"
        registration["matched_public_cells"] = 6
    (lane/"registration.json").write_text(json.dumps(registration, indent=2, sort_keys=True)+"\n")
    steps, artifacts, scratch_inventory = [], {}, []
    peak_files, peak_bytes = 0, 0
    uv = build_tool("uv")
    offline = [] if args.allow_download else ["--offline"]
    with tempfile.TemporaryDirectory(prefix="quantbt-met03-") as temporary:
        scratch = Path(temporary)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
            NUMBA_NUM_THREADS="1", MPLBACKEND="Agg", MPLCONFIGDIR=str(scratch/"mpl"), NUMBA_CACHE_DIR=str(scratch/"numba"),
            UV_CACHE_DIR="/tmp/quantbt-uv-cache", UV_LINK_MODE="hardlink")
        env.pop("PYTHONPATH", None)
        def run(command, *, cwd=ROOT, source=False):
            print(f"[{len(steps)+1}] {' '.join(map(str, command))}", flush=True)
            started = time.perf_counter()
            local = {**env, **({"PYTHONPATH": str(ROOT/"src")+":"+str(ROOT)} if source else {})}
            process = subprocess.run(list(map(str, command)), cwd=cwd, env=local, capture_output=True, text=True)
            log = lane/f"step-{len(steps)+1}.log"
            log.write_text(process.stdout+process.stderr)
            steps.append(dict(command=list(map(str, command)), exit_code=process.returncode,
                seconds=time.perf_counter()-started, log=log.relative_to(ROOT).as_posix(), sha256=digest(log)))
            print((process.stdout+process.stderr)[-3000:], flush=True)
            if process.returncode:
                raise RuntimeError(f"step failed; preserved {log}")
            return process.stdout
        error = None
        try:
            if args.stage == "source":
                target = scratch/"source-env"
                run([uv, "venv", "--python", sys.executable, target])
                python = target/"bin/python"
                run([uv, "pip", "install", *offline, "--python", python, NATIVE, *PINNED, *EXTRAS])
                run([uv, "pip", "check", "--python", python])
                run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/metrics", "tests/test_metrics_intraday_scope.py",
                    "tests/test_phase49a_walkforward_schedules.py", "tests/test_phase48c_event_driven_facade.py",
                    "tests/test_phase60_execution_metrics_native_result.py", f"--basetemp={scratch/'pytest'}",
                    f"--junitxml={lane/'pytest.xml'}"], source=True)
                run([python, "tools/metrics/benchmark_met03.py", "--output", lane/"benchmark.json"], source=True)
                if args.performance:
                    run([python, "tools/metrics/benchmark_reporting_performance.py", "--output", lane/"performance.json"], source=True)
                run([python, "-m", "examples.reporting_metrics_v1"], source=True)
            else:
                build_env = scratch/"build-env"
                run([uv, "venv", "--python", sys.executable, build_env])
                build_python = build_env/"bin/python"
                run([uv, "pip", "install", *offline, "--python", build_python, "build", "setuptools>=82,<83", "wheel>=0.46,<0.47"])
                stage = scratch/"stage"
                stage_source(stage, release_pair=True)
                dist = ROOT/".maturin/met03"/lane.name/"dist"
                dist.mkdir(parents=True)
                run([build_python, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", dist], cwd=stage)
                for kind, artifact in (("wheel", next(dist.glob("*.whl"))), ("sdist", next(dist.glob("*.tar.gz")))):
                    artifacts[kind] = dict(path=artifact.relative_to(ROOT).as_posix(), **artifact_source(artifact, registration["core_inventory"]))
                    target = scratch/kind
                    run([uv, "venv", "--python", sys.executable, target])
                    python = target/"bin/python"
                    run([uv, "pip", "install", *offline, "--python", python, str(artifact)+"[optimization]", NATIVE, *PINNED, *EXTRAS])
                    run([uv, "pip", "check", "--python", python])
                    stdout = run([python, "-I", ROOT/"tools/metrics/met03_consumer.py", lane/"registration.json",
                        ROOT/"examples/reporting_metrics_v1.py"], cwd=scratch)
                    artifacts[kind]["consumer"] = json.loads(stdout)
                    current = [p for p in scratch.rglob("*") if p.is_file() and not p.is_symlink()]
                    peak_files = max(peak_files, len(current))
                    peak_bytes = max(peak_bytes, sum(p.stat().st_size for p in current))
                    scratch_inventory.extend(dict(path=str(p.relative_to(scratch)), bytes=p.stat().st_size)
                        for p in target.rglob("*") if p.is_file() and not p.is_symlink())
                    if target.is_symlink() or target.parent != scratch:
                        raise RuntimeError("refuse redirected consumer cleanup")
                    shutil.rmtree(target)
            run(["git", "diff", "--check"])
            if core_inventory(ROOT/"src/quantbt") != registration["core_inventory"] or native_reuse(NATIVE) != registration["native_reuse"]:
                raise RuntimeError("source/native drift")
        except Exception as exc:
            error = str(exc)
        current = [p for p in scratch.rglob("*") if p.is_file() and not p.is_symlink()]
        peak_files = max(peak_files, len(current))
        peak_bytes = max(peak_bytes, sum(p.stat().st_size for p in current))
        scratch_inventory.extend(dict(path=str(p.relative_to(scratch)), bytes=p.stat().st_size) for p in current)
        scratch_bytes = sum(p["bytes"] for p in scratch_inventory)
        if peak_bytes > BUDGET or peak_files > 20000:
            error = error or "registered resource budget exceeded"
        cleanup_free_before = shutil.disk_usage(ROOT).free
    counts = dict(passed=0, failed=0, skipped=0)
    if (lane/"pytest.xml").exists():
        for case in ET.parse(lane/"pytest.xml").iter("testcase"):
            status = "failed" if case.find("failure") is not None or case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
            counts[status] += 1
    if args.stage == "source" and (not counts["passed"] or counts["failed"] or counts["skipped"]):
        error = error or "source tests incomplete"
    inputs = {p.relative_to(ROOT).as_posix(): digest(p) for directory in ("src/quantbt", "tests/metrics", "tools/metrics")
        for p in (ROOT/directory).rglob("*.py")}
    receipt = dict(phase="MET-03", stage=args.stage, technical_gate="FAIL" if error else "PASS", error=error,
        registration_sha256=digest(lane/"registration.json"), inputs=inputs, steps=steps, artifacts=artifacts,
        test_counts=counts, publication=False, native_rebuilt=False, source_unchanged=core_inventory(ROOT/"src/quantbt")==registration["core_inventory"],
        cleanup=dict(path=temporary, scratch_removed=not Path(temporary).exists(), apparent_bytes=scratch_bytes,
            files=len(scratch_inventory), peak_files=peak_files, peak_bytes=peak_bytes,
            free_bytes_before_final_cleanup=cleanup_free_before,
            inventory_sha256=sha256(json.dumps(scratch_inventory, sort_keys=True).encode()).hexdigest(),
            free_bytes_before=before, free_bytes_after=shutil.disk_usage(ROOT).free, free_inodes_before=inodes,
            free_inodes_after=os.statvfs(ROOT).f_favail, budget_bytes=BUDGET, retained_artifacts=True))
    (lane/"scratch-inventory.json").write_text(json.dumps(scratch_inventory, indent=2)+"\n")
    (lane/"receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2)+"\n")
    print(json.dumps(dict(lane=lane.relative_to(ROOT).as_posix(), status=receipt["technical_gate"], tests=counts)))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
