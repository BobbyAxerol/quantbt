"""Paired fresh-process evidence; baseline source is pinned, not a proxy score."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
BASE = "ac69e76"
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def child(lane):
    import numpy as np
    import pandas as pd
    import optuna
    import quantbt.walkforward as wf
    from quantbt import QuantBTEndpoint
    from quantbt.optimization.objectives import ReportMetricObjective
    from benchmarks.native_event import benchmark_next02_fresh_wfo as fixture
    from tools.measurement_contract import capture_measurement_identity

    optuna.logging.set_verbosity(optuna.logging.ERROR)
    source = subprocess.check_output(
        ["git", "show", f"{BASE}:src/quantbt/optimization/objectives.py"], cwd=ROOT, text=True
    )
    module_name = "quantbt.optimization._followup_reference"
    spec = importlib.util.spec_from_loader(module_name, loader=None)
    old = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = old
    exec(compile(source, f"{BASE}:objectives.py", "exec"), old.__dict__)

    original_indices = wf._stationary_bootstrap_indices
    if lane == "before":
        def reference_indices(n_obs, n_samples, block_length, seed, **kwargs):
            return original_indices(n_obs, n_samples, block_length, seed, use_numba=False)
        wf._stationary_bootstrap_indices = reference_indices
    values = np.random.default_rng(731).normal(.001, .01, 2000)
    start = perf_counter()
    wf.stationary_bootstrap_sharpes(values, 2, 20, 731)
    cold_bootstrap = perf_counter() - start
    start = perf_counter()
    draws = wf.stationary_bootstrap_sharpes(values, 200, 20, 731)
    bootstrap_seconds = perf_counter() - start

    market = fixture._market(2000, frequency="1h")
    account = QuantBTEndpoint.signal_notional(initial_capital=20_000., alloc_per_trade=1000., fee_rate=.0002)
    result = account.backtest(data=market, signal=pd.Series(np.where(np.sin(np.arange(2000) / 31) > 0, 1., -1.), index=market.index))

    class ReportProxy:
        def __init__(self, result):
            self.result, self.calls = result, 0

        def full_report(self, **kwargs):
            self.calls += 1
            return self.result.full_report(**kwargs)

        def __getattr__(self, name):
            return getattr(self.result, name)

    proxy = ReportProxy(result)
    objective = (old.ReportMetricObjective if lane == "before" else ReportMetricObjective)()
    expected, actual = old.ReportMetricObjective()(result, {}), ReportMetricObjective()(result, {})
    assert actual == expected
    objective(proxy, {})  # Report/import warmup is outside the measured work.
    proxy.calls = 0
    start = perf_counter()
    for _ in range(5):
        objective(proxy, {})
    report_seconds = (perf_counter() - start) / 5

    settings = dict(fixture.PROFILE_SPECS["smoke"])
    data = fixture._market(settings["bars"], frequency=settings["frequency"])
    mode = next(spec for spec in fixture.MODE_SPECS if spec.mode == "mode_2_sbb")
    result, wfo_seconds = fixture._run_lane(
        data, spec=mode, profile=settings, native_policy="off", prepared_strategy=False
    )
    metadata = result.metadata["walk_forward"]
    columns = [name for name in ("objective", "mean_is_sharpe", "mean_oos_sharpe", "mean_decay", "std_decay")
               if name in metadata["trial_table"]]
    digest = hashlib.sha256()
    for array in (result.equity, result.returns, result.positions, metadata["trial_table"][columns]):
        digest.update(np.asarray(array, dtype="<f8").tobytes())
    digest.update(json.dumps(metadata["params"], sort_keys=True).encode())
    print(json.dumps({
        "lane": lane, "bootstrap_seconds": bootstrap_seconds,
        "bootstrap_first_call_seconds": cold_bootstrap,
        "bootstrap_sha256": hashlib.sha256(draws.tobytes()).hexdigest(),
        "report_objective_seconds": report_seconds, "report_calls_per_objective": proxy.calls / 5,
        "mode2_fresh_study_seconds": wfo_seconds, "mode2_selected_params": metadata["params"],
        "mode2_selection_accounting_sha256": digest.hexdigest(),
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.,
        "baseline_objective_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "measurement_identity": capture_measurement_identity(
            root=ROOT, warmup_procedure="two bootstrap replicates and one report objective before timing; fresh WFO study",
            data_sha256=hashlib.sha256(data.to_numpy(dtype="<f8").tobytes()).hexdigest(),
            intent_sha256="mode2-global-four-trials-stationary-32-seed731",
        ),
    }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=("before", "after"))
    parser.add_argument("--pairs", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("/tmp/quantbt-followup-statistical.json"))
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    if args.pairs < 1:
        parser.error("pairs must be positive")
    rows = []
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "NUMBA_NUM_THREADS": "1"}
    for pair in range(args.pairs):
        result = {}
        for lane in (("before", "after") if pair % 2 == 0 else ("after", "before")):
            process = subprocess.run(
                [sys.executable, __file__, "--child", lane], cwd=ROOT, env=env,
                text=True, capture_output=True, check=True,
            )
            result[lane] = json.loads(process.stdout.splitlines()[-1])
        for field in ("bootstrap_sha256", "mode2_selection_accounting_sha256", "mode2_selected_params"):
            assert result["before"][field] == result["after"][field], field
        rows.append(result)
        print(f"pair {pair + 1}: parity passed", flush=True)
    metrics = ("bootstrap_seconds", "report_objective_seconds", "mode2_fresh_study_seconds", "peak_rss_mib")
    payload = {
        "schema": "quantbt-followup-statistical-work-v1", "baseline": BASE,
        "scope": "same-process warm kernels/objective; fresh Mode 2 study; one fresh process per lane",
        "fixture": {"bars": 2000, "wfo_frequency": "1D", "trials": 4, "sbb_samples": 32,
                    "bootstrap_observations": 2000, "bootstrap_samples": 200, "threads": 1},
        "candidate_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "candidate_sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (ROOT / "src/quantbt/walkforward.py", ROOT / "src/quantbt/optimization/bootstrap.py",
                                           ROOT / "src/quantbt/optimization/objectives.py")},
        "parity": "exact", "pairs": rows,
        "medians": {metric: {lane: statistics.median(row[lane][metric] for row in rows)
                             for lane in ("before", "after")} for metric in metrics},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["medians"], indent=2))


if __name__ == "__main__":
    main()
