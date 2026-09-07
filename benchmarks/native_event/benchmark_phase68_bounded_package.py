#!/usr/bin/env python3
"""Phase 68 bounded Rust package score/RSS evidence.

The fixture measures only the explicit same-account, linear,
``event_lifecycle_v2_next_bar_close`` package contract.  It deliberately
separates immutable request preparation, score/compact/audit retention, and a
one-boundary batch of pre-built package scenarios.  It is not a benchmark of
generic arbitrage planning, Python callback WFO, pandas reporting, or venue/L2
atomicity.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from quantbt.preparation.native_execution import NativeExecutionPreparationCache  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase68_bounded_package.json"
_LEG_COUNTS = (2, 4, 20)


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if not status.is_file():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _timed(call: Callable[[], Any], repeats: int) -> tuple[float, Any]:
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        samples.append(perf_counter() - started)
    return float(median(samples)), result


def _market(bars: int, symbols: int) -> dict[str, Any]:
    phase = np.arange(bars, dtype=np.float64)
    closes = np.ascontiguousarray(
        100.0
        + 0.004 * phase.reshape(-1, 1)
        + np.arange(symbols, dtype=np.float64).reshape(1, -1) * 3.0
        + 1.5 * np.sin(phase.reshape(-1, 1) / 29.0),
        dtype=np.float64,
    )
    funding = np.zeros_like(closes)
    funding[::8] = 0.00005
    funding_mask = np.zeros(bars, dtype=np.bool_)
    funding_mask[::8] = True
    funding_mask[0] = False
    return {
        "timestamps_ns": np.ascontiguousarray(
            pd.date_range("2024-01-01", periods=bars, freq="h", tz="UTC").view("int64"),
            dtype=np.int64,
        ),
        "opens": closes,
        "highs": np.ascontiguousarray(closes + 0.75),
        "lows": np.ascontiguousarray(closes - 0.75),
        "closes": closes,
        "volumes": np.full_like(closes, 100_000.0),
        "funding": np.ascontiguousarray(funding),
        "funding_mask": funding_mask,
        "symbols": tuple(f"S{symbol:02d}" for symbol in range(symbols)),
    }


def _template(cache: NativeExecutionPreparationCache, market: dict[str, Any]):
    symbol_count = len(market["symbols"])
    prepared_market = cache.prepare_market(**market)
    return cache.prepare_template(
        prepared_market,
        contract_sizes=np.ones(symbol_count, dtype=np.float64),
        leverages=np.full(symbol_count, 3.0, dtype=np.float64),
        fee_rates=np.full(symbol_count, 0.0005, dtype=np.float64),
        initial_capital=1_000_000.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=True,
    )


def _tape(
    *,
    bars: int,
    leg_count: int,
    command_bars: tuple[int, ...],
    package_id_start: int,
    order_id_start: int,
) -> dict[str, np.ndarray]:
    """Build a deterministic partial-primary hedge package tape.

    The first leg fills at 80%; every subsequent leg derives from that actual
    committed quantity.  This exercises the contract's key dependency without
    pretending to model venue liquidity.
    """

    if any(bar <= 0 or bar + 1 >= bars for bar in command_bars):
        raise ValueError("package bars must leave a prior snapshot and following bar")
    package_count = len(command_bars)
    offsets = [0]
    order_ids: list[int] = []
    symbol_ids: list[int] = []
    signed_qty: list[float] = []
    quantity_sources: list[int] = []
    source_legs: list[int] = []
    quantity_ratios: list[float] = []
    fill_fractions: list[float] = []
    qty_step: list[float] = []
    min_qty: list[float] = []
    min_notional: list[float] = []
    source_age_ns: list[int] = []
    venue_codes: list[int] = []
    venue_sequence: list[int] = []
    for package_index in range(package_count):
        for leg_index in range(leg_count):
            order_ids.append(order_id_start + len(order_ids))
            symbol_ids.append(leg_index)
            qty = 10.0 if leg_index == 0 else -10.0 / float(leg_count - 1)
            signed_qty.append(qty)
            quantity_sources.append(0 if leg_index == 0 else 2)
            source_legs.append(-1 if leg_index == 0 else 0)
            quantity_ratios.append(1.0 if leg_index == 0 else -1.0 / float(leg_count - 1))
            fill_fractions.append(0.8 if leg_index == 0 else 1.0)
            qty_step.append(0.01)
            min_qty.append(0.0)
            min_notional.append(0.0)
            source_age_ns.append(0)
            venue_codes.append(1)
            venue_sequence.append(leg_index)
        offsets.append(len(order_ids))
    return {
        "command_bars": np.asarray(command_bars, dtype=np.uint64),
        "package_ids": np.arange(package_id_start, package_id_start + package_count, dtype=np.uint64),
        "package_leg_offsets": np.asarray(offsets, dtype=np.uint64),
        "execution_policies": np.full(package_count, 3, dtype=np.uint8),
        "residual_policies": np.zeros(package_count, dtype=np.uint8),
        "max_staleness_ns": np.zeros(package_count, dtype=np.int64),
        "order_ids": np.asarray(order_ids, dtype=np.int64),
        "symbol_ids": np.asarray(symbol_ids, dtype=np.uint32),
        "signed_qty": np.asarray(signed_qty, dtype=np.float64),
        "quantity_sources": np.asarray(quantity_sources, dtype=np.uint8),
        "source_legs": np.asarray(source_legs, dtype=np.int64),
        "quantity_ratios": np.asarray(quantity_ratios, dtype=np.float64),
        "fill_fractions": np.asarray(fill_fractions, dtype=np.float64),
        "qty_step": np.asarray(qty_step, dtype=np.float64),
        "min_qty": np.asarray(min_qty, dtype=np.float64),
        "min_notional": np.asarray(min_notional, dtype=np.float64),
        "source_age_ns": np.asarray(source_age_ns, dtype=np.int64),
        "venue_codes": np.asarray(venue_codes, dtype=np.uint16),
        "venue_sequence": np.asarray(venue_sequence, dtype=np.uint32),
    }


def _scenario_tape(*, bars: int, leg_count: int, scenarios: int) -> dict[str, np.ndarray]:
    parts = []
    scenario_offsets = [0]
    for scenario in range(scenarios):
        command_bar = max(1, min(bars - 2, (scenario + 1) * bars // (scenarios + 1)))
        parts.append(
            _tape(
                bars=bars,
                leg_count=leg_count,
                command_bars=(command_bar,),
                package_id_start=10_000 + scenario,
                order_id_start=100_000 + scenario * leg_count,
            )
        )
        scenario_offsets.append(scenario_offsets[-1] + 1)
    result = {
        name: np.ascontiguousarray(
            np.concatenate([part[name] for part in parts])
            if name != "package_leg_offsets"
            else np.concatenate(
                [
                    part[name][:-1] + sum(len(previous["order_ids"]) for previous in parts[:index])
                    for index, part in enumerate(parts)
                ]
                + [np.asarray([sum(len(part["order_ids"]) for part in parts)], dtype=np.uint64)]
            )
        )
        for name in parts[0]
    }
    result["scenario_package_offsets"] = np.asarray(scenario_offsets, dtype=np.uint64)
    return result


def _profile_request(cache: NativeExecutionPreparationCache, template: Any, tape: dict[str, np.ndarray], profile: int):
    return cache.package_market_v2_request(template, output_profile=profile, **tape)


def _markdown(payload: dict[str, Any]) -> str:
    rows = "\n".join(
        "| `{label}` | {score:.6f} | {compact:.6f} | {audit:.6f} | {throughput:.1f} |".format(
            label=f"{legs} legs",
            score=values["prepared_score_seconds"],
            compact=values["prepared_compact_seconds"],
            audit=values["prepared_audit_seconds"],
            throughput=values["score_bar_symbols_per_second"],
        )
        for legs, values in payload["per_leg_count"].items()
    )
    batch = payload["scenario_batch"]
    return "\n".join(
        (
            "# Phase 68 Bounded Rust Package Benchmark",
            "",
            "The evidence covers only explicit same-account linear package intents under",
            "`event_lifecycle_v2_next_bar_close`. Each fixture uses a partial primary",
            "fill with post-actual-fill hedge sizing. It is not a generic arbitrage,",
            "callback WFO, pandas-report, L2, cross-currency, or cross-venue benchmark.",
            "",
            "| Prepared one-package workload | Score s | Compact s | Audit s | Score bar-symbols/s |",
            "|---|---:|---:|---:|---:|",
            rows,
            "",
            f"- Tape: `{payload['fixture']['bars']}` bars; one package per declared bar; leg counts `{payload['fixture']['leg_counts']}`.",
            f"- Scenario score batch: `{batch['scenarios']}` isolated `{batch['leg_count']}`-leg scenarios in `{batch['seconds']:.6f}` s (`{batch['bar_symbols_per_second']:.1f}` bar-symbols/s).",
            f"- Scenario native entries / market copies / workers: `{batch['native_entry_calls']}` / `{batch['market_copy_bytes']}` B / `{batch['worker_count']}`.",
            f"- Profile terminal parity: `{payload['evidence']['profile_terminal_parity']}`.",
            f"- Batch-vs-selected-single score parity: `{payload['evidence']['batch_selected_single_parity']}`.",
            f"- RSS start / profiles / batch: `{payload['rss_mb']['process_start']:.2f}` / `{payload['rss_mb']['after_profiles']:.2f}` / `{payload['rss_mb']['after_batch']:.2f}` MiB.",
            "",
            "`score` retains scalar accounting only. `compact` and `audit` are listed",
            "separately because they materialize progressively more cold-path result",
            "data. The batch resets account, positions, orders, and reservations before",
            "each independent scenario; a selected candidate must be rerun in audit",
            "profile for leg-level provenance.",
        )
    ) + "\n"


def run(*, bars: int, scenarios: int, repeats: int) -> dict[str, Any]:
    if bars < 128 or scenarios < 2 or repeats < 1:
        raise ValueError("bars must be >= 128, scenarios >= 2, and repeats >= 1")
    gc.collect()
    rss_start = _rss_mb()
    per_leg_count: dict[str, dict[str, float]] = {}
    profile_terminal_parity = True
    for leg_count in _LEG_COUNTS:
        cache = NativeExecutionPreparationCache()
        template = _template(cache, _market(bars, leg_count))
        tape = _tape(
            bars=bars,
            leg_count=leg_count,
            command_bars=(bars // 2,),
            package_id_start=1,
            order_id_start=1,
        )
        score_request = _profile_request(cache, template, tape, 0)
        compact_request = _profile_request(cache, template, tape, 1)
        audit_request = _profile_request(cache, template, tape, 2)
        score_warm = dict(score_request.core.execute())
        compact_warm = dict(compact_request.core.execute())
        audit_warm = dict(audit_request.core.execute())
        for field in ("final_equity", "total_fee", "total_turnover", "fill_count"):
            np.testing.assert_allclose(score_warm[field], compact_warm[field], rtol=0.0, atol=1e-11)
            np.testing.assert_allclose(score_warm[field], audit_warm[field], rtol=0.0, atol=1e-11)
        score_seconds, score = _timed(lambda: dict(score_request.core.execute()), repeats)
        compact_seconds, compact = _timed(lambda: dict(compact_request.core.execute()), repeats)
        audit_seconds, audit = _timed(lambda: dict(audit_request.core.execute()), repeats)
        np.testing.assert_allclose(score["final_equity"], compact["final_equity"], rtol=0.0, atol=1e-11)
        np.testing.assert_allclose(score["final_equity"], audit["final_equity"], rtol=0.0, atol=1e-11)
        profile_terminal_parity = profile_terminal_parity and bool(
            score["native_execution_terminal_fingerprint"]
            == compact["native_execution_terminal_fingerprint"]
            == audit["native_execution_terminal_fingerprint"]
        )
        per_leg_count[str(leg_count)] = {
            "prepared_score_seconds": score_seconds,
            "prepared_compact_seconds": compact_seconds,
            "prepared_audit_seconds": audit_seconds,
            "score_bar_symbols_per_second": float(bars * leg_count / score_seconds),
        }

    rss_after_profiles = _rss_mb()
    batch_cache = NativeExecutionPreparationCache()
    high_leg_count = max(_LEG_COUNTS)
    batch_template = _template(batch_cache, _market(bars, high_leg_count))
    scenario_tape = _scenario_tape(bars=bars, leg_count=high_leg_count, scenarios=scenarios)
    batch = batch_cache.package_market_v2_scenario_batch(batch_template, **scenario_tape)
    batch_warm = dict(batch.core.execute())
    batch_seconds, batch_payload = _timed(lambda: dict(batch.core.execute()), repeats)
    first_tape = _tape(
        bars=bars,
        leg_count=high_leg_count,
        command_bars=(max(1, min(bars - 2, bars // (scenarios + 1))),),
        package_id_start=10_000,
        order_id_start=100_000,
    )
    first_single = _profile_request(batch_cache, batch_template, first_tape, 0)
    first_single_payload = dict(first_single.core.execute())
    np.testing.assert_allclose(
        batch_warm["final_equity"][0], first_single_payload["final_equity"], rtol=0.0, atol=1e-11
    )
    np.testing.assert_allclose(batch_warm["final_equity"], batch_payload["final_equity"], rtol=0.0, atol=1e-11)
    gc.collect()
    rss_after_batch = _rss_mb()
    return {
        "schema": "phase68-bounded-package-benchmark-v1",
        "fixture": {"bars": bars, "leg_counts": list(_LEG_COUNTS), "scenarios": scenarios, "repeats": repeats},
        "per_leg_count": per_leg_count,
        "scenario_batch": {
            "leg_count": high_leg_count,
            "scenarios": scenarios,
            "seconds": batch_seconds,
            "bar_symbols_per_second": float(bars * high_leg_count * scenarios / batch_seconds),
            "native_entry_calls": int(batch_payload["native_entry_calls"]),
            "market_copy_bytes": int(batch_payload["market_copy_bytes"]),
            "worker_count": int(batch_payload["worker_count"]),
        },
        "rss_mb": {
            "process_start": rss_start,
            "after_profiles": rss_after_profiles,
            "after_batch": rss_after_batch,
        },
        "evidence": {
            "profile_terminal_parity": profile_terminal_parity,
            "batch_selected_single_parity": True,
            "scenario_batch_account_reset": True,
            "generic_arbitrage_auto_promoted": False,
            "l2_or_venue_atomicity_claimed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--scenarios", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(bars=args.bars, scenarios=args.scenarios, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
