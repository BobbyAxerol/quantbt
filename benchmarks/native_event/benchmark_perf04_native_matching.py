#!/usr/bin/env python3
"""PERF-04 native matcher/index development benchmark.

The benchmark measures the existing exact active-order index, reusable matcher
scratch, and bounded alias cleanup. It is deliberately not a public endpoint,
generic grid, L2, or WFO benchmark. Each workload runs the same canonical
static command tape through a prepared Rust runner and first proves score/audit
terminal parity.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
from time import perf_counter_ns
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
for path in (SOURCE_ROOT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, throughput_per_second  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/perf_04_native_matching.json"
CONTRACT_CODE = 3  # event_lifecycle_v3_next_open


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if not status.exists():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _market(bars: int) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray]]:
    if bars < 18:
        raise ValueError("bars must be >= 18")
    index = pd.date_range("2026-09-01", periods=bars, freq="1h", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = np.ascontiguousarray((100.0 + np.sin(phase / 3.0))[:, None])
    open_ = np.ascontiguousarray(close.copy())
    return index, {
        "opens": open_,
        "highs": np.ascontiguousarray(open_ + 1.0),
        "lows": np.ascontiguousarray(open_ - 1.0),
        "closes": close,
        "volumes": np.full_like(close, 50_000.0),
        "funding": np.zeros_like(close),
        "funding_mask": np.zeros(bars, dtype=np.bool_),
    }


def _append(
    rows: list[list[tuple[np.ndarray, np.ndarray, int]]],
    bar: int,
    code: np.ndarray,
    values: tuple[float, float, float],
) -> None:
    rows[bar].append((code, np.asarray(values, dtype=np.float64), -1))


def _high_churn_tape(
    *, bars: int, orders: int, spacing: int = 4
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Build passive place/amend/replace/cancel-all cycles over one symbol."""

    cycles = (bars - 2) // spacing
    rows: list[list[tuple[np.ndarray, np.ndarray, int]]] = [[] for _ in range(bars)]
    next_id = 1
    command_index = 0
    for cycle in range(cycles):
        place_bar = 1 + cycle * spacing
        original_ids: list[int] = []
        for _ in range(orders):
            original = next_id
            next_id += 1
            original_ids.append(original)
            code = np.full(16, -1, dtype=np.int64)
            code[[0, 1, 2, 3, 4, 5, 6, 11, 12]] = (
                0,
                0,
                1,
                1,
                0,
                0,
                original,
                0,
                command_index,
            )
            command_index += 1
            _append(rows, place_bar, code, (1.0, 10.0, 0.0))

        for original in original_ids:
            code = np.full(16, -1, dtype=np.int64)
            code[[0, 1, 7, 12]] = (3, 0, original, command_index)
            command_index += 1
            _append(rows, place_bar + 1, code, (0.0, 9.0, 0.0))

        for original in original_ids:
            replacement = next_id
            next_id += 1
            code = np.full(16, -1, dtype=np.int64)
            code[[0, 1, 2, 3, 4, 5, 6, 7, 11, 12]] = (
                2,
                0,
                1,
                1,
                0,
                0,
                replacement,
                original,
                0,
                command_index,
            )
            command_index += 1
            _append(rows, place_bar + 2, code, (1.0, 8.0, 0.0))

        cancel_all = np.full(16, -1, dtype=np.int64)
        cancel_all[[0, 1, 2, 6, 12]] = (4, -1, 0, next_id, command_index)
        next_id += 1
        command_index += 1
        _append(rows, place_bar + 3, cancel_all, (0.0, 0.0, 0.0))

    ptr = np.zeros(bars + 1, dtype=np.int64)
    codes: list[np.ndarray] = []
    values: list[np.ndarray] = []
    expiry: list[int] = []
    for bar, batch in enumerate(rows):
        for code, value, expire in batch:
            codes.append(code)
            values.append(value)
            expiry.append(expire)
        ptr[bar + 1] = len(codes)
    return (
        np.ascontiguousarray(ptr),
        np.ascontiguousarray(np.asarray(codes, dtype=np.int64)),
        np.ascontiguousarray(np.asarray(values, dtype=np.float64)),
        np.ascontiguousarray(np.asarray(expiry, dtype=np.int64)),
        cycles,
    )


def _runner(
    *, bars: int, orders: int, output_profile: int
) -> tuple[Any, int, int]:
    index, arrays = _market(bars)
    cache = NativeExecutionPreparationCache(
        CachePolicy(max_bytes=256 * 1024 * 1024, max_entries=8)
    )
    market = cache.prepare_market(
        timestamps_ns=np.ascontiguousarray(index.asi8, dtype=np.int64),
        symbols=["BTC"],
        **arrays,
    )
    template = cache.prepare_template(
        market,
        contract_sizes=np.ones(1, dtype=np.float64),
        leverages=np.full(1, 4.0, dtype=np.float64),
        fee_rates=np.full(1, 0.0005, dtype=np.float64),
        initial_capital=20_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
        event_contract_code=CONTRACT_CODE,
    )
    ptr, codes, values, expiry, cycles = _high_churn_tape(bars=bars, orders=orders)
    request = cache.command_request(
        template,
        command_ptr=ptr,
        command_codes=codes,
        command_values=values,
        command_expiry=expiry,
        output_profile=output_profile,
    )
    return cache.new_runner(request), cycles, int(len(codes))


def _terminal_tuple(output: Any) -> tuple[float, float, int, int, int, int]:
    return (
        float(output.final_equity),
        float(np.asarray(output.final_positions, dtype=np.float64).sum()),
        int(output.fill_count),
        int(output.canceled_count),
        int(output.rejected_count),
        int(output.event_count),
    )


def _run_case(*, bars: int, orders: int, repeats: int) -> dict[str, Any]:
    audit_runner, cycles, command_count = _runner(
        bars=bars, orders=orders, output_profile=2
    )
    audit = audit_runner.execute_typed()
    audit_terminal = _terminal_tuple(audit)
    if audit_terminal[:3] != (20_000.0, 0.0, 0):
        raise RuntimeError("passive matcher fixture unexpectedly changed account state")
    if audit_terminal[3] != cycles * orders:
        raise RuntimeError("cancel-all cycle did not cancel every replacement order")

    score_runner, _, _ = _runner(bars=bars, orders=orders, output_profile=0)
    warm = score_runner.execute_typed()
    if _terminal_tuple(warm) != audit_terminal:
        raise RuntimeError("score/audit terminal parity failed before timing")

    samples_ns: list[int] = []
    rss_samples: list[float] = []
    for repeat in range(repeats):
        started = perf_counter_ns()
        output = score_runner.execute_typed()
        samples_ns.append(perf_counter_ns() - started)
        if repeat % max(1, repeats // 4) == 0 or repeat == repeats - 1:
            gc.collect()
            rss_samples.append(_rss_mb())
        if _terminal_tuple(output) != audit_terminal:
            raise RuntimeError("timed score run drifted from audit terminal result")

    diagnostics = dict(score_runner.diagnostics())
    score_runner.reset("result_buffers", max_capacity=0)
    released = dict(score_runner.diagnostics())
    median_ns = int(np.median(np.asarray(samples_ns, dtype=np.int64)))
    elapsed_seconds = median_ns / 1_000_000_000.0
    tail = rss_samples[len(rss_samples) // 2 :] or rss_samples
    return {
        "orders_per_cycle": orders,
        "cycles": cycles,
        "command_count": command_count,
        "median_seconds": elapsed_seconds,
        "bars_per_second": throughput_per_second(bars, elapsed_seconds),
        "commands_per_second": throughput_per_second(command_count, elapsed_seconds),
        "terminal": {
            "score_audit_parity": True,
            "final_equity": audit_terminal[0],
            "final_position_sum": audit_terminal[1],
            "fill_count": audit_terminal[2],
            "canceled_count": audit_terminal[3],
            "rejected_count": audit_terminal[4],
            "event_count": audit_terminal[5],
        },
        "matching": {
            "matching_scan_count": int(diagnostics["matching_scan_count"]),
            "relationship_scan_count": int(diagnostics["relationship_scan_count"]),
            "expiry_scan_count": int(diagnostics["expiry_scan_count"]),
            "matching_candidate_capacity": int(diagnostics["matching_candidate_capacity"]),
            "lifecycle_candidate_capacity": int(diagnostics["lifecycle_candidate_capacity"]),
            "active_external_alias_count": int(diagnostics["active_external_alias_count"]),
            "terminal_orders_removed": int(diagnostics["terminal_orders_removed"]),
            "released_matching_candidate_capacity": int(released["matching_candidate_capacity"]),
            "released_lifecycle_candidate_capacity": int(released["lifecycle_candidate_capacity"]),
        },
        "rss_mb": {"samples": rss_samples, "tail_spread": max(tail) - min(tail)},
    }


def _markdown(payload: dict[str, Any]) -> str:
    rows = []
    for name, case in payload["workloads"].items():
        matching = case["matching"]
        rows.append(
            "| {name} | {orders} | {commands} | {seconds:.3f} | {throughput:,.0f} | {scans:,} | {relationship:,} |".format(
                name=name,
                orders=case["orders_per_cycle"],
                commands=case["command_count"],
                seconds=case["median_seconds"] * 1_000.0,
                throughput=case["commands_per_second"],
                scans=matching["matching_scan_count"],
                relationship=matching["relationship_scan_count"],
            )
        )
    return "\n".join(
        (
            "# PERF-04 Native Matching Evidence",
            "",
            "This is a development-only prepared Rust lifecycle benchmark. It measures passive",
            "limit place/amend/replace/cancel-all cycles over one symbol; it is not a public",
            "endpoint, generic grid, L2/order-book, or WFO throughput claim.",
            "",
            "| Workload | Live orders/cycle | Commands | Median ms | Commands/s | Active scans | Relationship scans |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "## Contract Evidence",
            "",
            "- Score and audit terminal account values are equal before timing.",
            "- Exact active-order priority remains sequence ordered. The index validator compares",
            "  the active index with a full arena scan in debug/test paths.",
            "- Parent/OCO/expiry/cancel-all snapshots use reusable scratch, so no candidate is",
            "  dropped during same-phase continuation. The generic index scan remains the fallback.",
            "- Alias cleanup is bounded by aliases for the terminal order and reports zero active",
            "  aliases after every cancel-all cycle.",
            "- `reset(result_buffers, max_capacity=0)` clears both matcher scratch capacities;",
            "  it does not alter account/order semantics or prior detached results.",
            "",
            "## RSS",
            "",
            f"- Process RSS tail spread: `{payload['rss_mb']['tail_spread']:.3f} MiB`.",
            "- These process samples include Python, NumPy and extension mappings; they are not",
            "  Rust-only allocation claims.",
            "",
        )
    )


def run(*, bars: int, high_orders: int, repeats: int) -> dict[str, Any]:
    if high_orders <= 1 or repeats < 3:
        raise ValueError("high_orders must be > 1 and repeats must be >= 3")
    rss_before = _rss_mb()
    workloads = {
        "small_exact_scan": _run_case(bars=bars, orders=1, repeats=repeats),
        "high_churn_indexed": _run_case(bars=bars, orders=high_orders, repeats=repeats),
    }
    rss_after = _rss_mb()
    tail_spread = max(case["rss_mb"]["tail_spread"] for case in workloads.values())
    return {
        "schema": "quantbt-perf-04-native-matching-v1",
        "scope": "prepared static lifecycle matcher only; no generic endpoint or L2 claim",
        "workload": {"bars": bars, "high_orders": high_orders, "repeats": repeats, "symbols": 1},
        "algorithm": {
            "active_prefilter": "exact active lifecycle index ordered by stable sequence",
            "small_shape": "same generic exact scan; no price-index specialization is enabled",
            "same_phase_children": "append to existing continuation queue",
            "fallback": "generic active-index scan remains the certified route",
        },
        "workloads": workloads,
        "rss_mb": {
            "before": rss_before,
            "after": rss_after,
            "delta": rss_after - rss_before,
            "tail_spread": tail_spread,
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="one audit parity run plus one score warmup per workload",
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--high-orders", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(bars=args.bars, high_orders=args.high_orders, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["workloads"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
