#!/usr/bin/env python3
"""PERF-06 public WFO research-audit retention benchmark.

The benchmark compares the same public five-mode WFO request with no optional
columnar sidecar versus an explicit full trial ledger.  It records the honest
retention cost, verifies public economic/selection parity, and times pandas
compatibility export only when it is requested.  It does not claim an audit
speedup merely because a lower-retention lane allocates fewer objects.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
from time import perf_counter, sleep
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quantbt import QuantBTEndpoint  # noqa: E402
from quantbt.core.research_audit import (  # noqa: E402
    ColumnarResearchTableV1,
    ResearchAuditWriterV1,
    ResearchRetentionPlanV1,
)
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/perf_06_research_audit.json"
MODES = (
    "mode_1_decay",
    "mode_2_sbb",
    "mode_3_flat_minima",
    "mode_4_is_only_robust",
    "mode_5_full_robust",
)


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if not status.is_file():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _median(values: list[float]) -> float:
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _market(bars: int) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=bars, freq="1D", tz="UTC")
    phase = np.arange(bars, dtype=np.float64)
    close = 100.0 + 0.04 * phase + np.sin(phase / 7.0) + 0.35 * np.cos(phase / 19.0)
    return pd.DataFrame(
        {
            "open": close - 0.12,
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "volume": 1_000.0 + phase,
            "funding_rate": np.where((phase.astype(np.int64) % 5) == 0, 0.00015, -0.00005),
        },
        index=index,
    )


def _strategy(data, params, train_index, test_index, fold):
    del data, train_index, fold
    direction = float(params["direction"])
    bars = np.arange(len(test_index), dtype=np.int64)
    return pd.Series(direction * np.where((bars // 9) % 2 == 0, 1.0, -1.0), index=test_index, dtype=float)


def _optimization_config(mode: str, *, research_retention: str, financial_retention: str) -> dict[str, object]:
    common: dict[str, object] = {
        "top_is_fraction": 1.0,
        "flat_eps": 1.0,
        "flat_min_samples": 1,
        "scoring_trading_days": 365,
        "min_trades_per_year": None,
        "trade_penalty_factor": None,
        "wfo_execution_reuse": "off",
        "research_retention": research_retention,
        "financial_retention": financial_retention,
        "research_audit_chunk_rows": 32,
        "research_audit_max_chunks": 4_096,
    }
    if mode == "mode_2_sbb":
        return {**common, "scoring_backend": "proxy", "sbb_samples": 8, "sbb_block_length": 3}
    selection_metric = {
        "mode_1_decay": "robust_decay",
        "mode_3_flat_minima": "is_plateau_robust",
        "mode_4_is_only_robust": "is_only_robust",
        "mode_5_full_robust": "full_robust",
    }[mode]
    return {
        **common,
        "candidate_selection_metric": selection_metric,
        "scoring_backend": "endpoint",
        "native_prepared_wfo": "require",
        "native_prepared_wfo_workers": 1,
        "is_subperiods": 1 if mode == "mode_5_full_robust" else 2,
    }


def _run(
    data: pd.DataFrame,
    *,
    mode: str,
    trials: int,
    research_retention: str,
    financial_retention: str,
):
    full_sample = mode == "mode_5_full_robust"
    endpoint = QuantBTEndpoint.walk_forward(
        strategy_class=_strategy,
        split_mode="full_sample_is" if full_sample else "2020-07-01",
        split_frequency="single" if full_sample else "quarterly",
        window_mode="expanding" if full_sample else "rolling",
        train_window=None if full_sample else "180D",
        target_mode="signal_notional",
        optimization_mode=mode,
        optimization_config=_optimization_config(
            mode,
            research_retention=research_retention,
            financial_retention=financial_retention,
        ),
        optuna_trials=trials,
        random_seed=31,
        initial_capital=20_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
        alloc_per_trade=1_000.0,
        fee_rate=0.0002,
        slippage=0.0001,
        target_runtime="rust",
    )
    started = perf_counter()
    result = endpoint.backtest(data=data, symbols=["BTC"], param_ranges={"direction": [-1.0, 1.0]})
    return endpoint, result, float(perf_counter() - started)


def _public_parity(left, right) -> bool:
    left_wf = left.metadata["walk_forward"]
    right_wf = right.metadata["walk_forward"]
    if left_wf["params"] != right_wf["params"] or left_wf["best_trial"] != right_wf["best_trial"]:
        return False
    if not np.allclose(left.equity.to_numpy(), right.equity.to_numpy(), rtol=0.0, atol=1e-10):
        return False
    if not np.allclose(left.positions.to_numpy(), right.positions.to_numpy(), rtol=0.0, atol=1e-12):
        return False
    return bool(left_wf["trial_table"].equals(right_wf["trial_table"])) and bool(
        left_wf["candidate_table"].equals(right_wf["candidate_table"])
    )


def _audit_summary(result) -> dict[str, object]:
    audit = result.metadata["walk_forward"].get("research_audit")
    if audit is None:
        return {"enabled": False}
    started = perf_counter()
    exports = audit.legacy_exports()
    adapt_seconds = float(perf_counter() - started)
    metadata = audit.metadata()
    trial_rows = int(len(exports["trial_table"]))
    if trial_rows != len(result.metadata["walk_forward"]["trial_table"]):
        raise RuntimeError("columnar legacy trial export lost or duplicated a public trial row")
    if not metadata["writer"]["memory_result_complete"]:
        raise RuntimeError("research audit did not complete its owned in-memory contract")
    return {
        "enabled": True,
        "trial_rows": trial_rows,
        "candidate_rows": int(len(exports["candidate_table"])),
        "evaluation_rows": int(len(exports["evaluation_table"])),
        "physical_bytes": int(metadata["writer"]["total_physical_bytes"]),
        "committed_chunks": int(metadata["writer"]["committed_chunks"]),
        "legacy_adapt_seconds": adapt_seconds,
        "writer_state": metadata["writer"]["writer_state"],
        "financial_completion": metadata["financial"]["financial_completion"],
    }


def _slow_sink_probe() -> dict[str, object]:
    plan = ResearchRetentionPlanV1(research_retention="full_trial_ledger", chunk_rows=1)
    elapsed: list[float] = []

    def slow_hook(_table: str, _chunk: str, _value: ColumnarResearchTableV1) -> None:
        started = perf_counter()
        sleep(0.001)
        elapsed.append(float(perf_counter() - started))

    writer = ResearchAuditWriterV1(plan=plan, export_hook=slow_hook)
    writer.append_records("trials", [{"trial_id": index, "objective": float(index)} for index in range(4)])
    writer.close()
    metadata = writer.metadata()
    if metadata["writer_state"] != "memory_complete" or metadata["exported_chunks"] != 4:
        raise RuntimeError("slow audit sink did not retain every committed chunk")
    return {
        "chunks": int(metadata["committed_chunks"]),
        "exported_chunks": int(metadata["exported_chunks"]),
        "median_hook_seconds": _median(elapsed),
        "queue_mode": metadata["queue_mode"],
        "queue_high_watermark_chunks": int(metadata["queue_high_watermark_chunks"]),
        "crash_durable": metadata["crash_durable"],
    }


def _markdown(payload: dict[str, Any]) -> str:
    rows = payload["mode_matrix"]
    return "\n".join(
        (
            "# PERF-06 Columnar Research Audit Benchmark",
            "",
            "This evidence uses the same public WFO request with the optional audit sidecar off and with",
            "`research_retention=full_trial_ledger`. It proves final economic/selection parity first, then",
            "reports the additional latency, owned bytes, chunks, lazy legacy-adaptation cost, and RSS.",
            "A full ledger is a transparency product, so a positive retention overhead is not described as a regression.",
            "",
            "| Mode | Public parity | Median no-sidecar | Median full ledger | Retention overhead | Ledger bytes | Chunks | Lazy export | Paired RSS delta |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            *(
                f"| {row['mode']} | {row['public_parity']} | {row['none_seconds_median']:.6f} s | "
                f"{row['full_seconds_median']:.6f} s | {row['full_overhead_pct']:+.2f}% | "
                f"{row['audit']['physical_bytes']} | {row['audit']['committed_chunks']} | "
                f"{row['audit']['legacy_adapt_seconds']:.6f} s | "
                f"{row['retention_rss_delta_mb_median']:+.3f} MiB |"
                for row in rows
            ),
            "",
            f"RSS peak: `{payload['rss_mb']['peak']:.3f} MiB`; tail spread: "
            f"`{payload['rss_mb']['tail_spread']:.3f} MiB`.",
            "",
            "The slow-sink probe is synchronous owned-chunk backpressure, not a claim of crash durability: "
            f"`{payload['slow_sink']['chunks']}` chunks, median hook time "
            f"`{payload['slow_sink']['median_hook_seconds']:.6f} s`, crash durability "
            f"`{payload['slow_sink']['crash_durable']}`.",
            "",
            "Paired RSS deltas are same-process warm observations, not cold-process peak claims.",
            "The normal legacy trial/candidate DataFrames remain compatible. The columnar artifact is only",
            "created when a non-default research or financial retention level is explicitly requested.",
            "",
        )
    )


def run(*, bars: int, trials: int, repeats: int) -> dict[str, Any]:
    if bars < 1_000:
        raise ValueError("bars must be >= 1000")
    if trials < 2 or repeats < 2:
        raise ValueError("trials and repeats must both be >= 2")
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - package dependency guard
        raise RuntimeError("PERF-06 benchmark requires the optimization extra") from exc
    data = _market(bars)
    # Warm import/JIT/market preparation without admitting it into samples.
    _run(data, mode="mode_1_decay", trials=trials, research_retention="none", financial_retention="score")

    mode_matrix: list[dict[str, object]] = []
    rss_samples: list[float] = []
    for mode in MODES:
        none_samples: list[float] = []
        full_samples: list[float] = []
        none_rss_deltas: list[float] = []
        full_rss_deltas: list[float] = []
        audit_summary: dict[str, object] | None = None
        for repeat_id in range(repeats):
            ordered = ("none", "full") if repeat_id % 2 == 0 else ("full", "none")
            completed: dict[str, tuple[object, float, float, float]] = {}
            for lane in ordered:
                gc.collect()
                rss_before = _rss_mb()
                endpoint, result, elapsed = _run(
                    data,
                    mode=mode,
                    trials=trials,
                    research_retention="none" if lane == "none" else "full_trial_ledger",
                    financial_retention="score",
                )
                rss_after = _rss_mb()
                del endpoint
                completed[lane] = (result, elapsed, rss_before, rss_after)
                if lane == "none":
                    none_samples.append(elapsed)
                    none_rss_deltas.append(rss_after - rss_before)
                else:
                    full_samples.append(elapsed)
                    full_rss_deltas.append(rss_after - rss_before)
                    audit_summary = _audit_summary(result)
            if not _public_parity(completed["none"][0], completed["full"][0]):
                raise RuntimeError(f"PERF-06 public parity failed for {mode}")
            rss_samples.append(_rss_mb())
        assert audit_summary is not None
        none_seconds = _median(none_samples)
        full_seconds = _median(full_samples)
        mode_matrix.append(
            {
                "mode": mode,
                "none_seconds_median": none_seconds,
                "full_seconds_median": full_seconds,
                "full_overhead_pct": 100.0 * (full_seconds - none_seconds) / max(none_seconds, 1e-12),
                "none_rss_delta_mb_median": _median(none_rss_deltas),
                "full_rss_delta_mb_median": _median(full_rss_deltas),
                "retention_rss_delta_mb_median": _median(full_rss_deltas) - _median(none_rss_deltas),
                "public_parity": True,
                "audit": audit_summary,
            }
        )
    tail = rss_samples[len(rss_samples) // 2 :] or rss_samples
    slow_sink = _slow_sink_probe()
    payload: dict[str, Any] = {
        "schema": "quantbt-perf-06-research-audit-v1",
        "scope": "public five-mode WFO sidecar retention and lazy compatibility export",
        "workload": {"bars": bars, "trials": trials, "repeats": repeats, "symbols": 1},
        "mode_matrix": mode_matrix,
        "slow_sink": slow_sink,
        "rss_mb": {
            "samples": rss_samples,
            "peak": float(max(rss_samples)),
            "tail_spread": float(max(tail) - min(tail)),
        },
        "evidence": {
            "all_public_parity": all(bool(row["public_parity"]) for row in mode_matrix),
            "all_full_ledgers_memory_complete": all(
                row["audit"]["writer_state"] == "memory_complete" for row in mode_matrix
            ),
            "all_legacy_trial_exports_present": all(row["audit"]["trial_rows"] > 0 for row in mode_matrix),
            "mode2_proxy_retained": next(row for row in mode_matrix if row["mode"] == "mode_2_sbb")["public_parity"],
            "slow_sink_owned_chunks_complete": slow_sink["exported_chunks"] == 4,
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="one unrecorded Mode 1 public WFO run without the research sidecar",
            data_sha256=typed_array_sha256(
                data.index.asi8,
                data["open"].to_numpy(),
                data["high"].to_numpy(),
                data["low"].to_numpy(),
                data["close"].to_numpy(),
                data["volume"].to_numpy(),
            ),
            intent_sha256=typed_array_sha256(
                np.asarray([row["audit"]["trial_rows"] for row in mode_matrix], dtype=np.int64),
                np.asarray([row["audit"]["physical_bytes"] for row in mode_matrix], dtype=np.int64),
            ),
        ),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=2_048)
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(bars=args.bars, trials=args.trials, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(bool(value) for value in payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
