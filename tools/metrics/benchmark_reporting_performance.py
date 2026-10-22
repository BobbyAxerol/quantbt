"""Same-host reporting comparison against the owner's immutable review baseline."""

import argparse
import cProfile
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import pstats
import resource
import shutil
import subprocess
import sys
import tarfile
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "24ad469"


def fixture(count, backend):
    import numpy as np
    import pandas as pd
    from quantbt import ReportingContractV1, ReportingRequest
    from quantbt.core.results import BacktestResultV2

    index = pd.date_range("2020-01-01", periods=count, freq="h", tz="UTC")
    equity = 100 + np.arange(count) * .000001 + 2 * np.sin(np.arange(count) / 20)
    result = BacktestResultV2(equity=pd.Series(equity, index=index),
        returns=pd.Series(np.r_[0., equity[1:]/equity[:-1]-1], index=index),
        positions=pd.DataFrame({"Position_X": np.ones(count)}, index=index),
        closes=pd.DataFrame({"Close_X": equity}, index=index), symbols=["X"], initial_capital=100.)
    contract = ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=100., baseline_time_ns=int(index[0].value), scope_end_ns=int(index[-1].value),
        sampling="observed_bar", annual_periods=8760., equity_clock="bar_close")
    request = ReportingRequest(account=contract, result_identity="benchmark-completed", backend=backend,
        partial_mask=(False,) * count, return_witness="complete hourly synthetic observations", retain_episodes=True)
    return result, request


def worker(count, backend):
    from dataclasses import replace
    from quantbt import ReportingCache
    from quantbt.metrics.reporting.adapters import account_from_completed
    from quantbt.metrics.reporting.account import reduce_account
    from tools.metrics.benchmark_met03 import measure

    result, request = fixture(count, backend)
    prepare = lambda: account_from_completed(result, request.account, result_identity=request.result_identity,
        partial_mask=request.partial_mask, return_witness=request.return_witness)
    observations = prepare()
    start = perf_counter()
    reduced = reduce_account(observations, request.account, backend=backend, retain_episodes=True)
    first_reduce_ms = (perf_counter()-start)*1000
    report = result.full_report(reporting=request)
    # Full JSON (metrics, coverage, identities, provenance and episode rows).
    report_hash = sha256(json.dumps(report, sort_keys=True, allow_nan=False).encode()).hexdigest()
    row = dict(count=count, backend=backend, input_identity=observations.identity,
        report_sha256=report_hash, first_reduce_ms=first_reduce_ms,
        snapshot=measure(prepare), reduction=measure(lambda: reduce_account(observations, request.account,
            backend=backend, retain_episodes=True)),
        public=measure(lambda: result.full_report(reporting=request)),
        request_preparation=measure(lambda: replace(request)),
        request_and_public=measure(lambda: result.full_report(reporting=replace(request))),
        legacy=measure(lambda: result.full_report(scope="full")))
    with ReportingCache(max_bytes=8*1024**2) as cache:
        cached = replace(request, cache=cache)
        row["cache"] = measure(lambda: result.full_report(reporting=cached))
    row["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    assert row["peak_rss_mib"] < 2048
    return row


def profile():
    from quantbt.metrics.reporting.adapters import account_from_completed
    result, request = fixture(1000000, "numba")
    profiler = cProfile.Profile()
    profiler.runcall(account_from_completed, result, request.account, result_identity=request.result_identity,
        partial_mask=request.partial_mask, return_witness=request.return_witness)
    output = io.StringIO()
    pstats.Stats(profiler, stream=output).sort_stats("cumulative").print_stats(30)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--worker", nargs=2)
    parser.add_argument("--ledger-worker", nargs=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.profile:
        print(profile())
        return
    if args.worker:
        print(json.dumps(worker(int(args.worker[0]), args.worker[1])))
        return
    if args.ledger_worker:
        from tools.metrics.benchmark_met03 import worker as ledger_worker
        kind, count, backend = args.ledger_worker
        print(json.dumps(ledger_worker(kind, int(count), backend)))
        return
    if shutil.disk_usage(ROOT).free < 8*1024**3 or os.statvfs(ROOT).f_favail < 20000:
        raise RuntimeError("registered disk/inode reserve unavailable")
    with tempfile.TemporaryDirectory(prefix="quantbt-met03-performance-") as temporary:
        scratch = Path(temporary)
        archive = subprocess.check_output(["git", "archive", BASELINE, "src/quantbt"], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(scratch, filter="data")
        env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", NUMBA_NUM_THREADS="1",
            PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg", MPLCONFIGDIR=str(scratch/"mpl"))
        profiles = {}
        for name, source in (("before", scratch/"src"), ("after", ROOT/"src")):
            profiles[name] = subprocess.check_output([sys.executable, __file__, "--profile"],
                cwd=ROOT, env={**env, "PYTHONPATH": str(source)+":"+str(ROOT)}, text=True)
        rows = []
        for backend in ("python", "numba"):
            for count in (2000, 100000, 1000000):
                cell = dict(count=count, backend=backend)
                for name, source in (("before", scratch/"src"), ("after", ROOT/"src")):
                    print(f"{name} {count}/{backend}", flush=True)
                    process = subprocess.run([sys.executable, __file__, "--worker", str(count), backend],
                        cwd=ROOT, env={**env, "PYTHONPATH": str(source)+":"+str(ROOT)}, capture_output=True, text=True)
                    if process.returncode:
                        raise RuntimeError(process.stdout+process.stderr)
                    cell[name] = json.loads(process.stdout)
                assert cell["before"]["report_sha256"] == cell["after"]["report_sha256"]
                assert cell["before"]["input_identity"] == cell["after"]["input_identity"]
                rows.append(cell)
        ledgers = []
        for backend in ("python", "numba"):
            for kind, count in (("trades", 32), ("trades", 2000), ("actions", 2000)):
                cell = dict(kind=kind, count=count, backend=backend)
                for name, source in (("before", scratch/"src"), ("after", ROOT/"src")):
                    print(f"{name} {kind}/{count}/{backend}", flush=True)
                    process = subprocess.run([sys.executable, __file__, "--ledger-worker", kind, str(count), backend],
                        cwd=ROOT, env={**env, "PYTHONPATH": str(source)+":"+str(ROOT)}, capture_output=True, text=True)
                    if process.returncode:
                        raise RuntimeError(process.stdout+process.stderr)
                    cell[name] = json.loads(process.stdout)
                assert cell["before"]["report_sha256"] == cell["after"]["report_sha256"]
                assert cell["before"]["input_identity"] == cell["after"]["input_identity"]
                ledgers.append(cell)
    args.output.write_text(json.dumps(dict(baseline=BASELINE, rows=rows, ledgers=ledgers, profiles=profiles, threads=1, warmup=1, repeats=5,
        parity="exact input identity and full report JSON SHA including episodes",
        limitations="sequential fresh workers; host not exclusive; five-sample p95 noisy",
        scratch_removed=not Path(temporary).exists(), publication=False), indent=2)+"\n")


if __name__ == "__main__":
    main()
