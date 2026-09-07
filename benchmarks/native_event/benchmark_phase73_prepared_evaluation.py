#!/usr/bin/env python3
"""Phase 73 shared prepared-native evaluation runtime evidence.

The workload is deliberately narrow: precompiled one-symbol target-unit
requests over one immutable market/template. It measures the generic
Rust-owned scheduler after market and intent ingress has completed. It is not
an end-to-end Python strategy, Optuna, report, or public WFO benchmark.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
for path in (SOURCE_ROOT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quantbt.backends.native_prepared_evaluation import (  # noqa: E402
    NativePreparedEvaluationRuntimeV1,
)
from quantbt.core.runtime_governance import RuntimeBudgetV1  # noqa: E402
from quantbt.preparation.native_execution import (  # noqa: E402
    CachePolicy,
    NativeExecutionPreparationCache,
)
from tools.measurement_contract import (  # noqa: E402
    capture_measurement_identity,
    throughput_per_second,
    typed_array_sha256,
)


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase73_prepared_evaluation.json"


def _rss_mb() -> float:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _market_arrays(
    bars: int,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if bars < 32:
        raise ValueError("bars must be >= 32")
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = np.ascontiguousarray(
        (100.0 + 0.012 * phase + 1.7 * np.sin(phase / 17.0))[:, None], dtype=np.float64
    )
    open_ = np.ascontiguousarray(np.vstack((close[0], close[:-1])), dtype=np.float64)
    high = np.ascontiguousarray(np.maximum(open_, close) + 0.4, dtype=np.float64)
    low = np.ascontiguousarray(np.minimum(open_, close) - 0.4, dtype=np.float64)
    return index, open_, high, low, close


def _target_request(cache: NativeExecutionPreparationCache, template: Any, candidate_id: int):
    bars = int(template.core.bars)
    targets = np.zeros((bars, 1), dtype=np.float64)
    period = 7 + int(candidate_id % 19)
    signal = np.sign(np.sin(np.arange(bars, dtype=np.float64) / float(period)))
    targets[:, 0] = 0.25 + 0.25 * (candidate_id % 4) * signal
    targets[0, 0] = 0.0
    return cache.direct_target_request(template, targets=targets, output_profile=0)


def _markdown(payload: dict[str, Any]) -> str:
    timings = "\n".join(
        f"| `{name}` | {seconds:.6f} |" for name, seconds in payload["timings_seconds"].items()
    )
    return "\n".join(
        (
            "# Phase 73 Shared Prepared Evaluation Benchmark",
            "",
            "This artifact measures a warm generic prepared target-unit batch. It excludes",
            "Python strategy generation, Optuna, endpoint/report adaptation, and WFO selection.",
            "It must not be used as a generic `walk_forward()` performance claim.",
            "",
            "| Phase | Median seconds |",
            "|---|---:|",
            timings,
            "",
            f"- Bars: `{payload['workload']['bars']}`",
            f"- Candidate rows: `{payload['workload']['candidates']}`",
            f"- Workers: `{payload['workload']['workers']}`",
            f"- Warm prepared candidate-bar visits/s: `{payload['throughput_candidate_bar_visits_per_second']:.1f}`",
            f"- RSS tail spread: `{payload['rss_mb']['tail_spread']:.3f} MiB`",
            f"- RSS plateau passed: `{payload['evidence']['rss_plateau']}`",
            f"- Exact repeated terminal rows: `{payload['evidence']['warm_deterministic']}`",
            "",
            "The batch creates one persistent Rust worker pool, crosses the Python/Rust boundary",
            "once per score batch, shares market/template ownership, and returns scalar rows only.",
            "",
        )
    )


def run(*, bars: int, candidates: int, repeats: int, workers: int) -> dict[str, Any]:
    if candidates <= 0 or repeats <= 1 or workers <= 0:
        raise ValueError("candidates/workers must be > 0 and repeats must be > 1")
    index, open_, high, low, close = _market_arrays(bars)
    volumes = np.full_like(close, 1_000.0)
    funding = np.zeros_like(close)
    funding_mask = np.zeros(bars, dtype=np.bool_)
    cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=512 * 1024 * 1024, max_entries=512))

    started = perf_counter()
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        opens=open_,
        highs=high,
        lows=low,
        closes=close,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=["BTC"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(1, dtype=np.float64),
        leverages=np.full(1, 3.0, dtype=np.float64),
        fee_rates=np.full(1, 0.0005, dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0001,
        use_funding=False,
    )
    market_template_seconds = perf_counter() - started

    started = perf_counter()
    requests = tuple(_target_request(cache, template, candidate) for candidate in range(candidates))
    intent_ingest_seconds = perf_counter() - started
    runtime = NativePreparedEvaluationRuntimeV1(
        cache,
        workers=workers,
        runtime_budget=RuntimeBudgetV1(
            max_bars=bars,
            max_workers=workers,
            max_native_memory_bytes=512 * 1024 * 1024,
            max_metric_rows=candidates,
            max_error_rows=candidates,
        ),
    )
    try:
        started = perf_counter()
        bindings = tuple(
            runtime.bind_request(
                request,
                workload="target_units",
                candidate_id=candidate,
                fold_id=0,
                scenario_id=0,
                estimated_cost=bars,
            )
            for candidate, request in enumerate(requests)
        )
        binding_seconds = perf_counter() - started
        warm = runtime.evaluate(bindings)
        if any(row.status != "success" for row in warm.rows):
            raise RuntimeError("warm prepared-evaluation batch did not complete successfully")
        expected = tuple(row.terminal_fingerprint for row in warm.rows)

        durations: list[float] = []
        rss_samples: list[float] = []
        result = warm
        for iteration in range(repeats):
            started = perf_counter()
            result = runtime.evaluate(bindings)
            durations.append(perf_counter() - started)
            if iteration % max(1, repeats // 10) == 0 or iteration == repeats - 1:
                gc.collect()
                rss_samples.append(_rss_mb())
        diagnostics = runtime.diagnostics()
        tail = rss_samples[len(rss_samples) // 2 :] or rss_samples
        tail_spread = max(tail) - min(tail) if tail else 0.0
        plateau_limit = max(8.0, (tail[0] if tail else 0.0) * 0.05)
        warm_seconds = float(np.median(np.asarray(durations, dtype=np.float64)))
        evidence = {
            "warm_deterministic": tuple(row.terminal_fingerprint for row in result.rows) == expected,
            "rss_plateau": tail_spread <= plateau_limit,
            "one_worker_pool": int(diagnostics["worker_pool_creations"]) == 1,
            "one_native_boundary_per_batch": int(warm.metadata["native_boundary_calls"]) == 1,
            "zero_market_copy_per_execution": int(warm.metadata["prepared_market_copies_per_execution"]) == 0,
            "zero_intent_copy_per_execution": int(warm.metadata["prepared_intent_copies_per_execution"]) == 0,
            "scalar_rows_only": len(warm.rows) == candidates,
        }
        signatures = np.asarray([request.signature.encode("ascii") for request in requests], dtype="S64")
        return {
            "schema": "quantbt-phase73-prepared-evaluation-v1",
            "scope": "warm prepared target-units batch only; not generic public WFO",
            "workload": {
                "bars": bars,
                "candidates": candidates,
                "repeats": repeats,
                "workers": workers,
                "symbols": 1,
            },
            "timings_seconds": {
                "market_template_prepare": float(market_template_seconds),
                "intent_ingest": float(intent_ingest_seconds),
                "binding": float(binding_seconds),
                "native_execution_and_scalar_adaptation": warm_seconds,
            },
            "throughput_candidate_bar_visits_per_second": throughput_per_second(
                bars * candidates, warm_seconds
            ),
            "rss_mb": {
                "samples": rss_samples,
                "tail_spread": float(tail_spread),
                "plateau_limit": float(plateau_limit),
            },
            "copy_contract": {
                "market_copy_per_execution_bytes": 0,
                "prepared_intent_copy_per_execution_bytes": 0,
                "python_normalization_copied_bytes": int(cache.diagnostics["ingress_copied_bytes"]),
                "rust_owned_one_time_ingress_bytes": int(
                    market.prepared_bytes
                    + template.model_bytes
                    + sum(int(request.request_bytes) for request in requests)
                ),
            },
            "evidence": evidence,
            "runtime_diagnostics": diagnostics,
            "measurement_identity": capture_measurement_identity(
                root=ROOT,
                warmup_procedure="prepare immutable target requests once, warm one native batch, then repeat score batches",
                data_sha256=typed_array_sha256(index.asi8, open_, high, low, close, volumes, funding),
                intent_sha256=typed_array_sha256(signatures),
            ),
        }
    finally:
        runtime.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=4096)
    parser.add_argument("--candidates", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(
        bars=args.bars,
        candidates=args.candidates,
        repeats=args.repeats,
        workers=args.workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
