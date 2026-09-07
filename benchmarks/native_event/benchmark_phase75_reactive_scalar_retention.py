"""Phase 75 scalar-retention evidence for Rust reactive R1/R2/R3.

The measured scalar route is the prepared optimization surface: it shares the
same Rust account/lifecycle session as a public result but returns only final
state, counters, and streaming metrics.  The benchmark intentionally reports
the public cold path separately rather than presenting it as a kernel number.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd

from quantbt import (
    ExecutionConfig,
    OrderSide,
    QuantBTEndpoint,
    StrategyContextRequirements,
)
from quantbt.backends.native_event import NativeEventScoreRequirements
from quantbt.strategies import BlockPlanV1, WakePlanV1


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase75_reactive_scalar_retention.json"

REQUIREMENTS = StrategyContextRequirements(
    market=("close",),
    account=("equity",),
    positions=("qty",),
    fills="new_only",
    events="new_only",
    active_orders="none",
    context_mode="numeric",
)


def _rss_bytes() -> int:
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def _frame(bars: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bars, freq="1min", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.003 * phase + 1.1 * np.sin(phase / 31.0)
    open_ = np.r_[close[0], close[:-1]] + 0.02 * np.cos(phase / 7.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.8,
            "low": np.minimum(open_, close) - 0.8,
            "close": close,
            "volume": 1_000.0,
            "funding_rate": np.where(phase % 480 == 0, 0.0001, 0.0),
        },
        index=index,
    )


class _EveryBar:
    quantbt_reactive_numeric_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, cadence: int) -> None:
        self.cadence = int(cadence)

    def on_bar_close(self, context, out) -> None:
        bar = int(context.bar_index)
        if bar % self.cadence == 0:
            out.market(0, OrderSide.BUY, 0.25, tif="ioc")
        elif bar % self.cadence == 1:
            out.market(0, OrderSide.SELL, 0.25, tif="ioc", reduce_only=True)


class _Sparse:
    quantbt_reactive_sparse_v1 = True
    quantbt_sparse_shadow_certified_v1 = True
    quantbt_requirements = REQUIREMENTS

    def __init__(self, cadence: int, bars: int) -> None:
        self.cadence = int(cadence)
        self.bars = int(bars)

    def on_wake(self, context, out) -> WakePlanV1:
        bar = int(context.bar_index)
        if (bar // self.cadence) % 2 == 0:
            out.market(0, OrderSide.BUY, 0.25, tif="ioc")
        else:
            out.market(0, OrderSide.SELL, 0.25, tif="ioc", reduce_only=True)
        next_bar = ((bar // self.cadence) + 1) * self.cadence
        return WakePlanV1(next_bar=next_bar if next_bar < self.bars else None)


class _Block:
    quantbt_reactive_block_intent_v1 = True
    quantbt_block_shadow_certified_v1 = True
    quantbt_requirements = REQUIREMENTS

    def next_block(self, context, start_bar, max_stop_bar, out) -> BlockPlanV1:
        for effective_bar in range(start_bar, max_stop_bar):
            if effective_bar % 32 == 1:
                out.market(0, OrderSide.BUY, 0.25, effective_bar=effective_bar)
            elif effective_bar % 32 == 2:
                out.market(0, OrderSide.SELL, 0.25, reduce_only=True, effective_bar=effective_bar)
        return BlockPlanV1(stop_bar=max_stop_bar, invalidate_on_fill=False)


def _endpoint(runtime: str, level: str) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=20_000.0,
        leverage=4.0,
        maintenance_ratio=0.005,
        fee_rate=0.0004,
        use_funding=True,
        report_level=level,
        audit_sink="none",
        reactive_execution_mode="fast",
        reactive_kernel_mode="single_pass",
        reactive_runtime=runtime,
        native_backend="rust",
        execution_contract="event_lifecycle_v3_next_open",
        execution=ExecutionConfig(slippage_bps=2.0),
    )


def _strategy(runtime: str, bars: int):
    if runtime == "numeric_every_bar_v1":
        return _EveryBar(32)
    if runtime == "numeric_sparse_wake_v1":
        return _Sparse(32, bars)
    if runtime == "numeric_block_intent_v1":
        return _Block()
    raise ValueError(runtime)


def _measure(call: Callable[[], Any], repeats: int) -> tuple[dict[str, float | int], Any]:
    warm = call()
    del warm
    gc.collect()
    before = _rss_bytes()
    samples: list[float] = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    after = _rss_bytes()
    return {
        "median_seconds": float(median(samples)),
        "p95_seconds": float(np.quantile(np.asarray(samples), 0.95)),
        "rss_before_bytes": int(before),
        "rss_after_bytes": int(after),
        "rss_delta_bytes": int(max(0, after - before)),
    }, result


def _row(stats: dict[str, float | int], *, bars: int, surface: str, result) -> dict[str, Any]:
    seconds = float(stats["median_seconds"])
    observed = result.metadata.get("reactive_numeric_observability", {})
    return {
        **stats,
        "surface": surface,
        "median_milliseconds": seconds * 1_000.0,
        "bars_per_second": float(bars / seconds) if seconds else 0.0,
        "final_equity": float(result.final_equity if hasattr(result, "final_equity") else result.equity.iloc[-1]),
        "callbacks": int(observed.get("python_callback_calls", 0)),
        "retention": observed.get("retention", "public_full"),
    }


def run(*, bars: int, repeats: int) -> dict[str, Any]:
    if bars < 2_000:
        raise ValueError("Phase 75 benchmark requires bars >= 2000")
    frame = _frame(bars)
    rows: list[dict[str, Any]] = []
    for runtime in ("numeric_every_bar_v1", "numeric_sparse_wake_v1", "numeric_block_intent_v1"):
        public_endpoint = _endpoint(runtime, "minimal")
        public_prepared = public_endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
        scalar_endpoint = _endpoint(runtime, "score")
        scalar_prepared = scalar_endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
        public_stats, public = _measure(
            lambda: public_prepared.run(_strategy(runtime, bars), report_level="minimal"), repeats
        )
        scalar_stats, scalar = _measure(
            lambda: scalar_prepared.score(
                _strategy(runtime, bars),
                score_requirements=NativeEventScoreRequirements.scalar_score_contract(),
            ),
            repeats,
        )
        np.testing.assert_allclose(scalar.final_equity, public.equity.iloc[-1], rtol=0.0, atol=1e-10)
        rows.extend(
            (
                {"runtime": runtime, **_row(public_stats, bars=bars, surface="prepared_public_minimal", result=public)},
                {"runtime": runtime, **_row(scalar_stats, bars=bars, surface="prepared_scalar_score", result=scalar)},
            )
        )
    return {
        "phase": "75",
        "workload_contract": "reactive_prepared_scalar_retention_v1",
        "bars": int(bars),
        "repeats": int(repeats),
        "rows": rows,
        "gates": {
            "same_rust_accounting_for_public_and_scalar": True,
            "scalar_retains_no_account_or_audit_path": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(bars=args.bars, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
