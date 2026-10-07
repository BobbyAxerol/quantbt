"""Matched cold-report costs. Five warm samples; no execution performance claim."""

import argparse
import ast
from dataclasses import replace
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]


def measure(call):
    import numpy as np
    call()
    samples = []
    for _ in range(5):
        start = perf_counter()
        call()
        samples.append((perf_counter() - start) * 1000)
    return dict(p50_ms=float(np.median(samples)), p95_ms=float(np.percentile(samples, 95)), samples_ms=samples)


def worker(kind, count, backend):
    import numpy as np
    import pandas as pd
    from quantbt import ReportingCache, ReportingContractV1, ReportingRequest
    from quantbt.core.results import BacktestResultV2
    from quantbt.metrics.reporting.adapters import account_from_completed
    from quantbt.metrics.reporting.account import reduce_account
    from quantbt.metrics.reporting.ledger import reduce_ledger
    from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome
    from quantbt.metrics.report_contracts import ReportingCoverageV1
    from quantbt.metrics.reporting.public import format_reporting_report, build_completed_report

    index = pd.date_range("2020-01-01", periods=count, freq="h", tz="UTC")
    close = 100 + np.arange(count) * .000001 + 2 * np.sin(np.arange(count) / 20)
    result = BacktestResultV2(equity=pd.Series(close, index=index),
        returns=pd.Series(np.r_[0., close[1:]/close[:-1]-1], index=index),
        positions=pd.DataFrame({"Position_X": np.ones(count)}, index=index),
        closes=pd.DataFrame({"Close_X": close}, index=index), symbols=["X"], initial_capital=100.)
    contract = ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=100., baseline_time_ns=int(index[0].value), scope_end_ns=int(index[-1].value),
        sampling="observed_bar", annual_periods=8760., equity_clock="bar_close")
    config = ReportingRequest(account=contract, result_identity="benchmark-completed", backend=backend,
        partial_mask=(False,) * count, return_witness="complete hourly synthetic observations", retain_episodes=True)
    data = dict(kind=kind, observations=count, backend=backend, warmup=1, repeats=5)
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    if kind == "account":
        parent = subprocess.check_output(["git", "show", "864b38a:src/quantbt/core/results.py"], cwd=ROOT, text=True)
        cls = next(n for n in ast.parse(parent).body if isinstance(n, ast.ClassDef) and n.name == "BacktestResultV2")
        old = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "full_report")
        namespace = {"__package__": "quantbt.core", "Dict": dict}
        exec(compile(ast.Module(body=[old], type_ignores=[]), "<immutable-parent-report>", "exec"), namespace)
        original = namespace["full_report"]
        assert original(result, scope="full") == result.full_report(scope="full")
        data["legacy_parent"] = measure(lambda: original(result, scope="full"))
        data["legacy_public_default"] = measure(lambda: result.full_report(scope="full"))
        prepare = lambda: account_from_completed(result, contract, result_identity=config.result_identity,
            partial_mask=config.partial_mask, return_witness=config.return_witness)
        data["snapshot_adaptation"] = measure(prepare)
        obs = prepare()
        start = perf_counter()
        reduced = reduce_account(obs, contract, backend=backend, retain_episodes=True)
        data["first_reduce_ms"] = (perf_counter() - start) * 1000
        data["reduce_with_episodes"] = measure(lambda: reduce_account(obs, contract, backend=backend, retain_episodes=True))
        data["fresh_public_with_episodes"] = measure(lambda: result.full_report(reporting=config))
        data["metadata_serialization"] = measure(reduced.to_metadata)
        data["episode_dataframe"] = measure(lambda: pd.DataFrame(reduced.episodes.to_rows()))
        metadata = result.full_report(reporting=config)
        data["text_formatting"] = measure(lambda: format_reporting_report(metadata))
        with ReportingCache(max_bytes=8*1024**2) as cache:
            cached = replace(config, cache=cache)
            data["public_cache_hit_rehash_and_serialize"] = measure(lambda: result.full_report(reporting=cached))
            data["cache_retained_bytes"] = cache.retained_bytes
            data["cache_hits"] = cache.hits
        if count == 2000:
            import matplotlib.pyplot as plt
            def plot():
                fig = result.quick_plot(reporting=config)
                fig.canvas.draw()
                plt.close(fig)
            data["plot_draw_2000_only"] = measure(plot)
    else:
        coverage = ReportingCoverageV1(result_identity=config.result_identity, producer="recorded synthetic outcomes",
            profile="audit", ledger="complete", retained_rows=count, dropped_rows=0)
        rows = tuple(RecordedOutcome(trade_id=str(i), action_id=str(i//2), symbol="A" if i%2==0 else "B",
            side="long" if i%2==0 else "short", currency="USDT", closed_at_ns=int(index[i].value),
            close_sequence=i, net_pnl=100. if i%2==0 else -80.) for i in range(count))
        roster = tuple(ActionRoster(action_id=str(i//2), outcome_ids=(str(i), str(i+1)), shared_net_adjustment=0.,
            allocation_witness="complete paired net outcomes") for i in range(0, count-1, 2))
        start = perf_counter()
        obs = LedgerObservations(records=rows, coverage=coverage, matching="position_episode", rosters=roster)
        data["ledger_snapshot_ms"] = (perf_counter()-start)*1000
        ledger_contract = replace(contract, unit="closed_action" if kind=="actions" else "closed_trade",
            matching="position_episode", grouping="authoritative_action_id" if kind=="actions" else "none",
            ledger_scope="closed_in_scope_lifetime")
        start = perf_counter()
        reduced = reduce_ledger(obs, ledger_contract, backend=backend)
        data["first_reduce_ms"] = (perf_counter()-start)*1000
        data["group_sort_reduce"] = measure(lambda: reduce_ledger(obs, ledger_contract, backend=backend))
        config = replace(config, ledger=obs, ledger_contracts=(ledger_contract,), retain_episodes=False)
        data["fresh_public_with_ledger"] = measure(lambda: build_completed_report(result, config).to_metadata())
        data["metadata_serialization"] = measure(reduced.to_metadata)
        metadata = build_completed_report(result, config).to_metadata()
        data["text_formatting"] = measure(lambda: format_reporting_report(metadata))
        data["closed_outcomes"] = count if kind != "actions" else count//2
    data["rss_before_mib"] = rss_start
    data["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    data["peak_delta_mib"] = data["peak_rss_mib"] - rss_start
    primary = data.get("fresh_public_with_episodes", data.get("fresh_public_with_ledger"))
    data["observations_per_second"] = count/(primary["p50_ms"]/1000)
    assert data["peak_rss_mib"] < 2048, "preregistered worker RSS budget"
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", nargs=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        kind, count, backend = args.worker
        print(json.dumps(worker(kind, int(count), backend)))
        return
    rows = []
    for backend in ("python", "numba"):
        for kind, count in (("account", 2000), ("account", 100000), ("account", 1000000),
                            ("trades", 32), ("trades", 2000), ("actions", 2000)):
            print(f"measure {kind}/{count}/{backend}", flush=True)
            process = subprocess.run([sys.executable, __file__, "--worker", kind, str(count), backend],
                cwd=ROOT, env=os.environ, capture_output=True, text=True)
            if process.returncode:
                raise RuntimeError(process.stdout + process.stderr)
            rows.append(json.loads(process.stdout))
    args.output.write_text(json.dumps(dict(rows=rows, threads=1, warmup=1, repeats=5,
        interpretation="cold reporting, not backtest execution; stage timings are independent matched calls",
        compatibility_speed_gate="measured only; no post-result threshold", publication=False), indent=2)+"\n")


if __name__ == "__main__":
    main()
