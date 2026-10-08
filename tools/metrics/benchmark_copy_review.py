"""Alternating same-process full-report comparison, with separate legacy controls."""

import argparse
import ast
import cProfile
from dataclasses import replace
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import pstats
import resource
import subprocess
import sys
import tarfile
import tempfile
from time import perf_counter
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BASELINES = ("dc12427", "24ad469")
WARMUPS, REPEATS = 2, 30


def load_reporting(source, name):
    package = ModuleType(name)
    package.__path__ = [str(source)]
    sys.modules[name] = package
    return SimpleNamespace(**{part: importlib.import_module(f"{name}.{module}")
        for part, module in (("contract", "report_contracts"), ("public", "reporting.public"),
                             ("request", "reporting.request"), ("ledger", "reporting.ledger_inputs"))})


def fixture(api, kind, count, backend):
    import numpy as np
    import pandas as pd
    index = pd.date_range("2020-01-01", periods=count, freq="h", tz="UTC")
    equity = 100 + np.arange(count) * .000001 + 2 * np.sin(np.arange(count) / 20)
    result = SimpleNamespace(equity=pd.Series(equity, index=index))
    contract = api.contract.ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=100., baseline_time_ns=int(index[0].value), scope_end_ns=int(index[-1].value),
        sampling="observed_bar", annual_periods=8760., equity_clock="bar_close")
    request = api.request.ReportingRequest(account=contract, result_identity="benchmark-completed", backend=backend,
        partial_mask=(False,) * count, return_witness="complete hourly synthetic observations",
        retain_episodes=kind == "account")
    if kind != "account":
        coverage = api.contract.ReportingCoverageV1(result_identity=request.result_identity,
            producer="recorded synthetic outcomes", profile="audit", ledger="complete",
            retained_rows=count, dropped_rows=0)
        rows = tuple(api.ledger.RecordedOutcome(trade_id=str(i), action_id=str(i//2),
            symbol="A" if i % 2 == 0 else "B", side="long" if i % 2 == 0 else "short",
            currency="USDT", closed_at_ns=int(index[i].value), close_sequence=i,
            net_pnl=100. if i % 2 == 0 else -80.) for i in range(count))
        rosters = tuple(api.ledger.ActionRoster(action_id=str(i//2), outcome_ids=(str(i), str(i+1)),
            shared_net_adjustment=0., allocation_witness="complete paired net outcomes")
            for i in range(0, count-1, 2))
        obs = api.ledger.LedgerObservations(records=rows, coverage=coverage,
            matching="position_episode", rosters=rosters)
        ledger_contract = replace(contract, unit="closed_action" if kind == "actions" else "closed_trade",
            matching="position_episode", grouping="authoritative_action_id" if kind == "actions" else "none",
            ledger_scope="closed_in_scope_lifetime")
        request = replace(request, ledger=obs, ledger_contracts=(ledger_contract,))
    return lambda: api.public.reporting_metadata(result, request)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def paired(before, after):
    import numpy as np
    for _ in range(WARMUPS):
        before()
        after()
    samples = {"before": [], "after": []}
    for repeat in range(REPEATS):
        ordered = (("before", before), ("after", after))
        for name, call in ordered if repeat % 2 == 0 else reversed(ordered):
            start = perf_counter()
            call()
            samples[name].append((perf_counter() - start) * 1000)
    return {name: dict(p50_ms=float(np.median(values)), p95_ms=float(np.percentile(values, 95)),
                       samples_ms=values) for name, values in samples.items()}


def profile(call):
    profiler = cProfile.Profile()
    profiler.runcall(call)
    output = io.StringIO()
    pstats.Stats(profiler, stream=output).sort_stats("cumulative").print_stats(20)
    return output.getvalue()


def legacy_control(count):
    from quantbt.core.results import BacktestResultV2
    from tools.metrics.benchmark_reporting_performance import fixture as completed_fixture
    frame, _ = completed_fixture(count, "python")
    text = subprocess.check_output(["git", "show", "864b38a:src/quantbt/core/results.py"], cwd=ROOT, text=True)
    cls = next(node for node in ast.parse(text).body if isinstance(node, ast.ClassDef)
               and node.name == "BacktestResultV2")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "full_report")
    namespace = {"__package__": "quantbt.core", "Dict": dict}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<sealed-legacy-body>", "exec"), namespace)
    before = lambda: namespace["full_report"](frame, scope="full")
    after = lambda: BacktestResultV2.full_report(frame, scope="full")
    assert before() == after()
    return dict(**paired(before, after), exact_outputs=True, source_parent="864b38a",
                interpretation="same-process unchanged scientific body, separate smaller output contract")


def worker(parent_source, baseline, kind, count, backend):
    if hasattr(os, "sched_getaffinity"):
        cpu = min(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {cpu})
    else:
        cpu = None
    parent = load_reporting(parent_source, "_met03_before")
    current = load_reporting(ROOT / "src/quantbt/metrics", "_met03_after")
    before, after = fixture(parent, kind, count, backend), fixture(current, kind, count, backend)
    hashes = {name: digest(call()) for name, call in (("before", before), ("after", after))}
    assert hashes["before"] == hashes["after"], "complete report/episode/identity parity"
    timing = paired(before, after)
    assert digest(before()) == digest(after()) == hashes["before"]
    row = dict(baseline=baseline, kind=kind, count=count, backend=backend, **timing,
        report_sha256=hashes["after"], exact_outputs=True, cpu_affinity=cpu,
        measurement="production public cold adapter/reducers/metadata; endpoint forwarding body unchanged",
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    if count == 2000:
        row["profiles"] = dict(before=profile(before), after=profile(after))
    if kind == "account" and baseline == BASELINES[0]:
        row["legacy_control"] = legacy_control(count)
    from threadpoolctl import threadpool_info
    row["thread_pools"] = threadpool_info()
    assert all(pool["num_threads"] == 1 for pool in row["thread_pools"])
    assert row["peak_rss_mib"] < 2048
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", nargs=5)
    args = parser.parse_args()
    if args.worker:
        source, baseline, kind, count, backend = args.worker
        print(json.dumps(worker(Path(source), baseline, kind, int(count), backend)))
        return
    if args.output is None or args.output.exists():
        raise ValueError("fresh evidence output required")
    rows = []
    with tempfile.TemporaryDirectory(prefix="quantbt-met03-performance-") as temporary:
        scratch = Path(temporary)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1",
            MPLBACKEND="Agg", MPLCONFIGDIR=str(scratch / "mpl"))
        env["PYTHONPATH"] = str(ROOT / "src") + ":" + str(ROOT)
        for baseline in BASELINES:
            directory = scratch / baseline
            directory.mkdir()
            archive = subprocess.check_output(["git", "archive", baseline, "src/quantbt/metrics"], cwd=ROOT)
            with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                bundle.extractall(directory, filter="data")
            for backend in ("python", "numba"):
                for kind, count in (("account", 2000), ("account", 100000), ("account", 1000000),
                                    ("trades", 32), ("trades", 2000), ("actions", 2000)):
                    print(f"paired {baseline} {kind}/{count}/{backend}", flush=True)
                    process = subprocess.run([sys.executable, __file__, "--worker",
                        str(directory / "src/quantbt/metrics"), baseline, kind, str(count), backend],
                        cwd=ROOT, env=env, capture_output=True, text=True)
                    if process.returncode:
                        args.output.with_suffix(".failure.log").write_text(process.stdout + process.stderr)
                        raise RuntimeError("paired worker failed; original failure preserved")
                    rows.append(json.loads(process.stdout))
    args.output.write_text(json.dumps(dict(baselines=BASELINES, rows=rows, warmups=WARMUPS, repeats=REPEATS,
        alternating_order=True, one_cpu=True, threads=1, exact_outputs=True,
        rss_policy="paired worker peak includes both implementations; isolated RSS is in the standard benchmark",
        limitations="host not exclusive; finite samples do not prove universal non-regression",
        scratch_removed=not Path(temporary).exists(), publication=False), indent=2) + "\n")


if __name__ == "__main__":
    main()
