"""Matched complete reporting cost against a committed source, without execution."""

import argparse
from dataclasses import replace
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tarfile
from time import perf_counter

from tools.metrics.benchmark_copy_review import load_reporting


ROOT = Path(__file__).resolve().parents[2]
CASES = (("account", 2000), ("account", 100000), ("account", 1000000),
         ("trades", 32), ("trades", 2000), ("actions", 2000), ("unique_reasons", 2000))
WARMUPS, REPEATS = 2, 30


def fixture(api, kind, count, backend):
    import numpy as np
    import pandas as pd
    index = pd.date_range("2020-01-01", periods=count, freq="h", tz="UTC")
    equity = 100 + np.arange(count)*.000001 + 2*np.sin(np.arange(count)/20)
    from types import SimpleNamespace
    completed = SimpleNamespace(equity=pd.Series(equity, index=index))
    contract = api.contract.ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=100., baseline_time_ns=int(index[0].value), scope_end_ns=int(index[-1].value),
        sampling="observed_bar", annual_periods=8760., equity_clock="bar_close")
    request = api.request.ReportingRequest(account=contract, result_identity="benchmark-completed", backend=backend,
        partial_mask=(False,)*count, return_witness="complete hourly synthetic observations",
        retain_episodes=kind == "account")
    if kind != "account":
        coverage = api.contract.ReportingCoverageV1(result_identity=request.result_identity,
            producer="recorded synthetic outcomes", profile="audit", ledger="complete", retained_rows=count, dropped_rows=0)
        rows = tuple(api.ledger.RecordedOutcome(trade_id=str(i), action_id=str(i//2),
            symbol="A" if i%2 == 0 else "B", side="long" if i%2 == 0 else "short", currency="USDT",
            opened_at_ns=int(index[max(0, i-1)].value), closed_at_ns=int(index[i].value), close_sequence=i,
            close_reason=f"reason-{i:05d}" if kind == "unique_reasons" else "tp" if i%2 else "sl",
            net_pnl=100. if i%2 == 0 else -80.) for i in range(count))
        rosters = tuple(api.ledger.ActionRoster(action_id=str(i//2), outcome_ids=(str(i),str(i+1)),
            shared_net_adjustment=0., allocation_witness="complete paired net outcomes") for i in range(0,count-1,2))
        ledger = api.ledger.LedgerObservations(records=rows, coverage=coverage, matching="position_episode",
            rosters=rosters, valuation_time_ns=contract.scope_end_ns)
        ledger_contract = replace(contract, unit="closed_action" if kind == "actions" else "closed_trade",
            matching="position_episode", grouping="authoritative_action_id" if kind == "actions" else "none",
            ledger_scope="closed_in_scope_lifetime")
        request = replace(request, ledger=ledger, ledger_contracts=(ledger_contract,))
    return lambda: api.public.reporting_metadata(completed, request)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def run(output, baseline):
    import numpy as np
    from threadpoolctl import threadpool_info
    if output.exists():
        raise ValueError("append-only fresh output required")
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    scratch = output.parent/"scratch/parent"
    scratch.mkdir(parents=True, exist_ok=False)
    archive = subprocess.check_output(["git", "archive", baseline, "src/quantbt/metrics"], cwd=ROOT)
    with (output.parent/"baseline-metrics.tar").open("xb") as stream:
        stream.write(archive)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(scratch, filter="data")
    before_api = load_reporting(scratch/"src/quantbt/metrics", "_report120_before")
    after_api = load_reporting(ROOT/"src/quantbt/metrics", "_report120_after")
    paths = sorted((ROOT/"src/quantbt/metrics").rglob("*.py"))
    sources = {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in paths}
    rows = []
    for backend in ("python", "numba"):
        for kind, count in CASES:
            available = os.statvfs(ROOT)
            assert available.f_bavail*available.f_frsize >= 5*1024**3 + 32*1024**2
            before = fixture(before_api, kind, count, backend)
            after = fixture(after_api, kind, count, backend)
            initial = {}
            outputs = {}
            for name, call in (("before",before), ("after",after)):
                start = perf_counter(); outputs[name] = call(); initial[name] = perf_counter()-start
            assert digest(outputs["before"]) == digest(outputs["after"]), (kind, count, backend)
            if kind != "account":
                unit = "closed_action" if kind == "actions" else "closed_trade"
                for value in outputs.values():
                    group = value["groups"][unit]
                    closed = next(metric for metric in group["metrics"] if metric["metric_id"].endswith(".closed_count"))
                    assert group["status"] == "available" and closed["value"] == (count//2 if kind == "actions" else count)
            for _ in range(WARMUPS):
                before(); after()
            samples = dict(before=[], after=[])
            for repeat in range(REPEATS):
                calls = (("before",before), ("after",after))
                for name, call in calls if repeat%2 == 0 else reversed(calls):
                    start = perf_counter(); call(); samples[name].append((perf_counter()-start)*1000)
            assert digest(before()) == digest(after()) == digest(outputs["before"])
            assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024 < 768
            rows.append(dict(kind=kind, count=count, backend=backend, exact_full_report_sha256=digest(outputs["before"]),
                initial_call_seconds=initial,
                **{name: dict(p50_ms=float(np.median(values)), p95_ms=float(np.percentile(values,95)), samples_ms=values)
                   for name, values in samples.items()}))
            print(f"complete {kind}/{count}/{backend}", flush=True)
    assert all(pool["num_threads"] == 1 for pool in threadpool_info())
    assert sources == {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in paths}
    result = dict(schema="quantbt.reporting.performance_120.v1", baseline_commit=baseline, sources=sources,
        repeats=REPEATS, warmups=WARMUPS, cpu_affinity=cpu, thread_pools=threadpool_info(), rows=rows,
        exact_outputs=True, new_optimizer_trials=0, new_financial_executions=0,
        baseline_archive_sha256=sha256(archive).hexdigest(),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        measurement="Complete public reporting with immutable request reused; includes snapshot, reduction, episodes and metadata; no backtest/WFO",
        limitations=["Host not exclusive; finite-sample p95 descriptive", "Paired peak RSS includes both implementations",
                     "First call includes compilation but is not a cold OS/pagecache measurement", "High-cardinality reasons are a stress control, not a usual ledger claim"],
        publication=False)
    with output.open("x") as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False); stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.output.resolve(), args.baseline)


if __name__ == "__main__":
    main()
