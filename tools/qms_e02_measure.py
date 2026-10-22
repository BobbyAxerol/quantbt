"""Matched fresh-process E02 resource/call measurement, not a speed-promotion gate."""

import argparse
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import resource
from statistics import median
import subprocess
import sys
import tarfile
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "82c1421"


def worker(lane):
    import optuna
    from examples.wfo_meta_selection import run_demo
    from tools.qms05_public import scientific_signature
    from tools.qms_e02_audit import array_signature
    from quantbt.optimization.meta_selection.common import digest, wire

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    # Identical imports/JIT warm-up in each new process; peak includes that work.
    run_demo("off", observer=False)
    wall, cpu = perf_counter(), process_time()
    if lane.startswith("scalar"):
        mode = "off" if lane == "scalar-off" else "active"
        _, result, _ = run_demo(mode, observer=mode != "off", min_origins=1)
        elapsed, cpu_seconds = perf_counter()-wall, process_time()-cpu
        wf = result.metadata["walk_forward"]
        meta = wf.get("meta_selection") or {}
        signature = scientific_signature(result)
        trials = len(wf["trial_table"])
        bars = len(result.equity)
    else:
        from tests.meta_selection.test_local_reactive import execute
        result, _, runtime = execute("active")
        try:
            elapsed, cpu_seconds = perf_counter()-wall, process_time()-cpu
            meta = result.metadata["meta_selection"]
            signature = digest(dict(params=wire({str(k): v for k, v in result.params_by_fold.items()}),
                objectives=array_signature(result.trial_table.objective),
                accounts=[{key: array_signature(getattr(row.result, key)) for key in
                    ("equity", "returns", "positions", "fees", "funding", "margin")}
                    for row in result.fold_results]))
            trials, bars = len(result.trial_table), sum(len(row.result.equity) for row in result.fold_results)
        finally:
            runtime.close()
    return dict(lane=lane, seconds=elapsed, cpu_seconds=cpu_seconds,
        fresh_process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        scientific_signature=signature, logical_trials=trials, retained_bars=bars,
        observer_attempts=meta.get("observer_attempts", 0), observer_failures=meta.get("observer_failures", 0),
        adapter=meta.get("domain_adapter"), peak_scope="process lifetime including imports/JIT warm-up")


def measure(output, repeats):
    if output.exists() or repeats < 1:
        raise ValueError("fresh output and positive repeats required")
    output.mkdir(parents=True)
    baseline = output / "baseline"
    baseline.mkdir()
    archive = subprocess.check_output(["git", "archive", ENTRY, "src"], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        # Git-produced tracked regular files only, never an untrusted archive.
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith("src/"):
                continue
            path = baseline / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tar.extractfile(member).read())
    raw = []
    for repeat in range(repeats):
        for lane in ("scalar-off", "scalar-active", "reactive-active"):
            for label in (("baseline", "current") if repeat % 2 == 0 else ("current", "baseline")):
                source = baseline / "src" if label == "baseline" else ROOT / "src"
                env = dict(os.environ, PYTHONPATH=str(source)+os.pathsep+str(ROOT),
                    OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", MPLCONFIGDIR="/tmp")
                cmd = [sys.executable, "-m", "tools.qms_e02_measure", "--worker", lane]
                done = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True,
                    timeout=240, check=False)
                log = output / f"{repeat}-{lane}-{label}.log"
                log.write_text("$ "+" ".join(cmd)+"\n"+done.stdout+done.stderr)
                if done.returncode:
                    raise ValueError(f"E02 matched worker failed; see {log}")
                row = json.loads(done.stdout.splitlines()[-1])
                raw.append(dict(source=label, repeat=repeat, log=str(log.relative_to(ROOT)),
                    log_sha256=sha256(log.read_bytes()).hexdigest(), **row))
    for repeat in range(repeats):
        for lane in ("scalar-off", "scalar-active", "reactive-active"):
            a, b = [r for r in raw if r["repeat"] == repeat and r["lane"] == lane]
            for key in ("scientific_signature", "logical_trials", "retained_bars",
                        "observer_attempts", "observer_failures"):
                if a[key] != b[key]:
                    raise AssertionError(f"E02 same-work mismatch {lane}: {key}")
            current = next(r for r in (a, b) if r["source"] == "current")
            telemetry = current["adapter"]
            if lane == "scalar-off":
                assert telemetry is None
            else:
                assert telemetry["financial_delegate_calls"] == telemetry["original_observations"] == current["observer_attempts"]
                assert all(telemetry[k] == 0 for k in ("financial_replays", "adapter_owned_market_bytes",
                    "adapter_market_array_copies", "adapter_pyo3_calls"))
    summary = []
    for lane in ("scalar-off", "scalar-active", "reactive-active"):
        row = dict(lane=lane)
        for source in ("baseline", "current"):
            runs = [r for r in raw if r["lane"] == lane and r["source"] == source]
            row[source] = {key: median(r[key] for r in runs) for key in ("seconds", "cpu_seconds", "fresh_process_peak_rss_mib")}
        summary.append(row)
    receipt = dict(schema="qms-e02-matched-resources-v1", baseline=ENTRY, repeats=repeats,
        trials_and_account_exact=True, rows=raw, summary=summary,
        claim="engineering resource/call counters; small fixture, no speed-promotion or p95 claim",
        financial_ffi_scope="unchanged native owner; adapter introduces zero crossings",
        alpha="public synthetic SMA and existing synthetic W3 numeric fixture; no real-alpha study",
        publication=False)
    (output / "measurement.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("scalar-off", "scalar-active", "reactive-active"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.worker:
        result = worker(args.worker)
    elif args.output:
        result = measure(args.output.resolve(), args.repeats)
    else:
        parser.error("--worker or --output required")
    print(json.dumps(result, sort_keys=True))
