"""Matched V1 reporting costs, not execution or economic speedup evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
REPEATS = 5
SIZES = (2000, 100000, 1000000)


def rss():
    with open("/proc/self/status") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024


def worker(n, backend, kind):
    import numpy as np
    from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
    from quantbt.metrics.reporting import AccountObservations, reduce_account
    from quantbt.metrics.reporting.cache import ReportingCache
    from quantbt.metrics.reporting.ledger import reduce_ledger
    from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome

    imported = rss()
    start = time.perf_counter()
    coverage = ReportingCoverageV1(result_identity="public-matched-benchmark", producer="synthetic-recorded",
        profile="compact" if kind == "account" else "audit", ledger="omitted" if kind == "account" else "complete",
        retained_rows=0 if kind == "account" else n, dropped_rows=0,
        reason="no ledger retained for account benchmark" if kind == "account" else None)
    times = np.arange(n, dtype=np.int64) * 60_000_000_000
    contract = ReportingContractV1(scope="full", unit="account_period" if kind == "account" else "closed_action" if kind == "action" else "closed_trade",
        currency="USDT", baseline_equity=100., baseline_time_ns=0, scope_end_ns=int(times[-1]),
        sampling="observed_bar", annual_periods=365.25 * 24 * 60, equity_clock="bar_close",
        matching="none" if kind == "account" else "position_episode",
        ledger_scope="none" if kind == "account" else "closed_in_scope_lifetime",
        grouping="authoritative_action_id" if kind == "action" else "none")
    if kind == "account":
        phase = np.arange(n, dtype=np.float64)
        equity = 100. * (1. + phase * 1e-6 + .01 * np.sin(phase / 31.))
        observations = AccountObservations(times_ns=times, equity=equity, coverage=coverage)
        observations = observations.with_derived_returns(contract, partial_mask=np.zeros(n, dtype=bool),
            witness="explicit synthetic full minute marks; first mark includes baseline return")
        reducer = reduce_account
        del phase, equity
    else:
        rows = tuple(RecordedOutcome(trade_id=str(i), symbol="A" if i % 2 else "B",
            side="long" if i % 2 else "short", currency="USDT", opened_at_ns=max(0, int(times[i]) - 60000000000),
            closed_at_ns=int(times[i]), close_sequence=i, net_pnl=float(i % 7 - 3),
            action_id=str(i // 2) if kind == "action" else None,
            allocated_fee=.1, allocated_funding_cost=0., allocated_slippage_cost=0.) for i in range(n))
        rosters = tuple(ActionRoster(action_id=str(i // 2), outcome_ids=(str(i), str(i + 1)),
            shared_net_adjustment=0., allocation_witness="all costs attributed in recorded leg net PnL")
            for i in range(0, n, 2)) if kind == "action" else ()
        observations = LedgerObservations(records=rows, coverage=coverage, matching="position_episode", rosters=rosters)
        reducer = reduce_ledger
        del rows
    del times
    prepare_seconds = time.perf_counter() - start
    prepared_rss = rss()
    start = time.perf_counter()
    warm = reducer(observations, contract, backend=backend)
    warmup_seconds = time.perf_counter() - start
    warm_rss = rss()
    samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        result = reducer(observations, contract, backend=backend)
        samples.append(time.perf_counter() - start)
    primary_rss = rss()
    primary_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    expected = reducer(observations, contract, backend="python" if backend == "numba" else "numba")
    metric_parity = all(a.status == b.status and a.unit == b.unit and a.sample_count == b.sample_count and (
        a.value == b.value if a.value is None or b.value is None else np.isclose(a.value, b.value, rtol=1e-11, atol=1e-12))
        for a, b in zip(result.metrics, expected.metrics))
    cache = ReportingCache()
    cache.reduce(kind if kind == "account" else "ledger", observations, contract, backend=backend)
    cache_samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        hit = cache.reduce(kind if kind == "account" else "ledger", observations, contract, backend=backend)
        cache_samples.append(time.perf_counter() - start)
    retained = cache.retained_bytes
    cache.close()
    p50, p95 = np.percentile(samples, [50, 95])
    measurement = dict(kind=kind, observations=n, backend=backend, repeats=REPEATS, samples_seconds=samples,
        p50_ms=float(p50 * 1000), p95_ms=float(p95 * 1000), observations_per_second=float(n / p50),
        prepare_ms=prepare_seconds * 1000, first_call_including_jit_ms=warmup_seconds * 1000,
        cache_hit_p50_ms=float(np.median(cache_samples) * 1000), cache_accounted_bytes=retained,
        input_identity=observations.identity, contract_identity=contract.identity,
        parity=bool(metric_parity), output=hit.to_metadata(),
        rss_bytes=dict(after_import=imported, prepared=prepared_rss, after_primary_warmup=warm_rss,
                       after_primary_measurement=primary_rss, primary_process_peak=primary_peak,
                       after_parity_and_cache=rss(), process_peak_including_parity=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
        peak_includes_other_backend_parity=True, cache_released=cache.entry_count == 0,
        output_policy="scalar metrics; no episode/population details retained", thread_env={
            name: os.getenv(name) for name in ("NUMBA_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")})
    if not metric_parity:
        raise AssertionError("matched V1 reporting parity failed")
    print(json.dumps(measurement, sort_keys=True, allow_nan=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=int)
    parser.add_argument("--backend", choices=("python", "numba"))
    parser.add_argument("--kind", choices=("account", "ledger", "action"), default="account")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.backend, args.kind)
        return
    cells = []
    for kind, sizes in (("account", SIZES), ("ledger", (32, 2000)), ("action", (2000,))):
        for n in sizes:
            for backend in ("python", "numba"):
                command = [sys.executable, __file__, "--worker", str(n), "--backend", backend, "--kind", kind]
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                cell = json.loads(result.stdout)
                cells.append(cell)
                print(json.dumps({key: cell[key] for key in ("kind", "observations", "backend", "p50_ms", "p95_ms", "parity")}), flush=True)
    payload = dict(phase="MET-02", protocol="registered before measurement; one warmup/five repeats, fresh worker per cell",
        cells=cells, measurement_scope="cold post-simulation reducer on pre-snapshotted buffers; prepare/JIT/RSS disclosed separately",
        source_hashes={path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (ROOT / "src/quantbt/metrics/reporting").glob("*.py")},
        engine_changes=False, latency_acceptance_gate="not registered; informational cost measurement only")
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
