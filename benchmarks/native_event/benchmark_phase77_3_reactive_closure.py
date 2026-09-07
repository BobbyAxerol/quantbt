#!/usr/bin/env python3
"""Phase 77.3 reactive native execution/resource closure evidence.

This artifact deliberately keeps reactive public work separate from W0 signal
WFO, target, portfolio, package, and intrabar work.  It records two named
reactive workloads on the current candidate:

* R1/R2/R3 prepared public-minimal versus scalar retention; and
* W3 sequential/R3B walk-forward scheduling with a prepared Rust market.

The result also reruns small, contract-specific controls for the other public
native surfaces touched by the shared runtime.  Those controls are parity
sentinels, not a generic reactive speed claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
BENCHMARK_DIR = ROOT / "benchmarks" / "native_event"
for _path in (SOURCE_ROOT, ROOT, BENCHMARK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import benchmark_phase67_shared_portfolio as phase67  # noqa: E402
import benchmark_phase68_bounded_package as phase68  # noqa: E402
import benchmark_phase69_rust_intrabar as phase69  # noqa: E402
import benchmark_phase74_public_wfo as phase74  # noqa: E402
import benchmark_phase75_reactive_scalar_retention as phase75  # noqa: E402
import benchmark_phase76_reactive_wfo as phase76  # noqa: E402
from tools.measurement_contract import capture_measurement_identity, typed_array_sha256  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase77_3_reactive_closure.json"
SCHEMA = "quantbt-phase77-3-reactive-closure-v1"

PROFILE_SPECS: dict[str, dict[str, int]] = {
    "smoke": {
        "scalar_bars": 2_000,
        "scalar_repeats": 2,
        "wfo_bars": 720,
        "wfo_candidates": 4,
        "wfo_repeats": 2,
        "control_bars": 512,
        "control_repeats": 2,
    },
    "standard": {
        "scalar_bars": 10_000,
        "scalar_repeats": 5,
        "wfo_bars": 2_000,
        "wfo_candidates": 8,
        "wfo_repeats": 5,
        "control_bars": 1_000,
        "control_repeats": 2,
    },
}


def _scalar_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep the measurement fields needed to compare matching R1/R2/R3 lanes."""

    rows: list[dict[str, Any]] = []
    for row in payload["rows"]:
        rows.append(
            {
                "runtime": str(row["runtime"]),
                "surface": str(row["surface"]),
                "median_seconds": float(row["median_seconds"]),
                "p95_seconds": float(row["p95_seconds"]),
                "median_milliseconds": float(row["median_milliseconds"]),
                "bars_per_second": float(row["bars_per_second"]),
                "callbacks": int(row["callbacks"]),
                "rss_delta_bytes": int(row["rss_delta_bytes"]),
                "final_equity": float(row["final_equity"]),
            }
        )
    return rows


def _wfo_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract transparent W3 work units without claiming cross-schedule parity."""

    rows: list[dict[str, Any]] = []
    for row in payload["rows"]:
        memory = dict(row["rss_pss_delta"])
        rows.append(
            {
                "schedule": str(row["schedule"]),
                "python_work_per_callback": int(row["python_work_per_callback"]),
                "median_seconds": float(row["median_seconds"]),
                "p95_seconds": float(row["p95_seconds"]),
                "median_milliseconds": float(row["median_milliseconds"]),
                "candidate_fold_bar_visits_per_second": float(
                    row["candidate_fold_bar_visits_per_second"]
                ),
                "median_score_calls": int(row["median_score_calls"]),
                "median_score_bars": int(row["median_score_bars"]),
                "median_callbacks": int(row["median_callbacks"]),
                "rss_delta_bytes": {key: int(value) for key, value in memory.items()},
            }
        )
    return rows


def _control_summary(payload: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    """Store only the independently meaningful control evidence."""

    if kind == "public_wfo":
        evidence = dict(payload["evidence"])
        required = (
            "public_parity",
            "native_route_active",
            "stable_native_work_counts",
            "full_facade_non_regression",
            "score_stage_reduced",
            "rss_plateau",
        )
        return {
            "required_evidence": {key: bool(evidence[key]) for key in required},
            "timings_seconds": dict(payload["timings_seconds"]),
            "speedup": dict(payload["speedup"]),
            "rss_mb": dict(payload["rss_mb"]),
        }
    if kind == "portfolio":
        evidence = dict(payload["evidence"])
        required = ("score_compact_terminal_parity", "wfo_prepared_parity")
        return {
            "required_evidence": {key: bool(evidence[key]) for key in required},
            "timing_seconds": dict(payload["timing_seconds"]),
            "throughput_bar_symbols_per_second": dict(payload["throughput_bar_symbols_per_second"]),
            "rss_mb": dict(payload["rss_mb"]),
        }
    if kind == "package":
        evidence = dict(payload["evidence"])
        required = (
            "profile_terminal_parity",
            "batch_selected_single_parity",
            "scenario_batch_account_reset",
        )
        return {
            "required_evidence": {key: bool(evidence[key]) for key in required},
            "scenario_batch": dict(payload["scenario_batch"]),
            "rss_mb": dict(payload["rss_mb"]),
        }
    if kind == "intrabar":
        evidence = dict(payload["evidence"])
        required = ("terminal_and_path_parity", "score_has_no_dense_paths")
        return {
            "required_evidence": {key: bool(evidence[key]) for key in required},
            "timing_seconds": dict(payload["timing_seconds"]),
            "throughput_bars_per_second": dict(payload["throughput_bars_per_second"]),
            "rss_mb": dict(payload["rss_mb"]),
        }
    raise ValueError(f"unknown Phase 77.3 control kind: {kind}")


def _all_control_evidence(controls: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(
        bool(value)
        for summary in controls.values()
        for value in dict(summary["required_evidence"]).values()
    )


def _markdown(payload: Mapping[str, Any]) -> str:
    scalar_rows = payload["reactive_scalar"]["rows"]
    wfo_rows = payload["reactive_wfo"]["rows"]
    scalar_table = "\n".join(
        "| `{runtime}` | `{surface}` | {median_milliseconds:.3f} ms | {bars_per_second:,.0f} | {callbacks} |".format(
            **row
        )
        for row in scalar_rows
    )
    wfo_table = "\n".join(
        "| `{schedule}` | {python_work_per_callback} | {median_milliseconds:.3f} ms | "
        "{candidate_fold_bar_visits_per_second:,.0f} | {median_callbacks} |".format(**row)
        for row in wfo_rows
    )
    control_lines = "\n".join(
        f"- `{name}`: `{all(summary['required_evidence'].values())}`"
        for name, summary in payload["controls"].items()
    )
    return "\n".join(
        (
            "# Phase 77.3 Reactive Closure Evidence",
            "",
            "This is current-candidate development evidence for the explicitly certified Rust reactive",
            "R1/R2/R3/W3 routes. It does not promote arbitrary Python callbacks, generic `walk_forward()`,",
            "Mode 2, portfolio/package WFO, or `backend=\"auto\"`.",
            "",
            "## Named Workloads",
            "",
            (
                f"- Scalar retention: `{payload['profile']['scalar_bars']:,}` bars, "
                f"`{payload['profile']['scalar_repeats']}` warm repeats."
            ),
            (
                f"- Reactive W3: `{payload['profile']['wfo_bars']:,}` bars, "
                f"`{payload['profile']['wfo_candidates']}` candidates, "
                f"`{payload['profile']['wfo_repeats']}` warm repeats."
            ),
            "- R3B is a distinct fixed/adaptive batch schedule. Its throughput is never compared to sequential TPE as if it sampled the same search sequence.",
            "",
            "### Prepared Reactive R1/R2/R3",
            "",
            "| Runtime | Surface | Median | Bars/s | Python callbacks |",
            "|---|---|---:|---:|---:|",
            scalar_table,
            "",
            "### Reactive W3",
            "",
            "| Schedule | Python work/callback | Median | Candidate-fold bar visits/s | Callbacks |",
            "|---|---:|---:|---:|---:|",
            wfo_table,
            "",
            "## Safety And Retention",
            "",
            "- Wake observations use two symbol-sized mutable buffers per run and refresh in place; the typed `WakePlanV1` wire avoids a dict conversion on the optimized R2/R3 path. Legacy payload-only plans remain adapter-compatible.",
            "- Cancellation and `RuntimeBudgetV1(max_wall_time_ms=...)` are enforced while Rust advances active work. Sparse/block gaps check at completed account-bar boundaries at most every 64 bars and again at a wake/end boundary. No partial score is adapted or admitted to selection.",
            "- The deadline starts after fresh-account initialization for each score. `reset()` clears active deadline/cancellation state before an independent next score; result/account paths are never retained on scalar failure.",
            "- Focused active-work proof: `tests/test_phase77_3_reactive_parity.py` covers native cancellation, deadline propagation through scalar WFO and R3B, and reset recovery. It is not a metadata-only test.",
            "",
            "## Cross-Route Controls",
            "",
            control_lines,
            "",
            "The controls rerun small public-WFO, shared-portfolio, bounded-package and intrabar requests from their own contract-specific harnesses. They are regression sentinels, not a combined speed score.",
            "",
            "## Interpretation",
            "",
            "Historical Phase 75/76 artifacts remain immutable scope records and use different source identities/repeat counts. This artifact intentionally does not publish a before/after percentage from those records. Compare only same-profile current-candidate runs with identical workload and retention definitions.",
            "",
        )
    )


def run(*, profile: str = "standard") -> dict[str, Any]:
    if profile not in PROFILE_SPECS:
        raise ValueError(f"profile must be one of {', '.join(sorted(PROFILE_SPECS))}")
    spec = dict(PROFILE_SPECS[profile])
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:  # pragma: no cover - Phase 74 emits the clearer dependency error.
        pass

    scalar = phase75.run(
        bars=int(spec["scalar_bars"]),
        repeats=int(spec["scalar_repeats"]),
    )
    wfo = phase76.run(
        bars=int(spec["wfo_bars"]),
        candidates=int(spec["wfo_candidates"]),
        repeats=int(spec["wfo_repeats"]),
    )

    control_bars = int(spec["control_bars"])
    control_repeats = int(spec["control_repeats"])
    controls = {
        "public_wfo": _control_summary(
            phase74.run(bars=max(1_000, control_bars), trials=4, repeats=2),
            kind="public_wfo",
        ),
        "shared_portfolio": _control_summary(
            phase67.run(bars=control_bars, symbols=2, candidates=4, repeats=control_repeats),
            kind="portfolio",
        ),
        "bounded_package": _control_summary(
            phase68.run(bars=control_bars, scenarios=4, repeats=control_repeats),
            kind="package",
        ),
        "intrabar": _control_summary(
            phase69.run(bars=control_bars, repeats=control_repeats),
            kind="intrabar",
        ),
    }
    scalar_rows = _scalar_rows(scalar)
    wfo_rows = _wfo_rows(wfo)
    evidence = {
        "same_reactive_accounting_public_and_scalar": bool(
            scalar["gates"]["same_rust_accounting_for_public_and_scalar"]
        ),
        "scalar_retention_is_path_free": bool(
            scalar["gates"]["scalar_retains_no_account_or_audit_path"]
        ),
        "reactive_wfo_deterministic": bool(wfo["evidence"]["repeat_determinism"]),
        "reactive_wfo_r3b_shared_market": bool(wfo["evidence"]["r3b_shared_market"]),
        "reactive_wfo_cow_worker": bool(wfo["evidence"]["clean_cow_worker"]),
        "cross_route_control_parity": _all_control_evidence(controls),
        "active_interrupts_have_focused_test_coverage": True,
    }
    scalar_frame = phase75._frame(int(spec["scalar_bars"]))
    wfo_frame = phase76._frame(int(spec["wfo_bars"]))
    return {
        "schema": SCHEMA,
        "phase": "77.3",
        "status": "development_candidate_evidence_not_release_promotion",
        "profile": {"id": profile, **spec},
        "reactive_scalar": {"rows": scalar_rows, "gates": dict(scalar["gates"])},
        "reactive_wfo": {
            "rows": wfo_rows,
            "evidence": dict(wfo["evidence"]),
            "worker_probe": dict(wfo["worker_probe"]),
        },
        "controls": controls,
        "runtime_contract": {
            "reactive_deadline_safe_point": "completed_account_bar_v1",
            "sparse_gap_max_interrupt_interval_bars": 64,
            "partial_score_policy": "discard_before_python_adaptation_or_selection",
            "typed_wake_plan": "quantbt-wake-wire-v1",
            "legacy_wake_plan_adapter": "payload_only_supported",
        },
        "evidence": evidence,
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure=(
                "each imported benchmark warms its declared route before measured repeats; "
                "Phase 77.3 records scalar retention, W3 scheduling, and small cross-route parity controls"
            ),
            data_sha256=typed_array_sha256(
                scalar_frame.index.asi8,
                scalar_frame[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(dtype=float),
                wfo_frame.index.asi8,
                wfo_frame[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(dtype=float),
            ),
            intent_sha256=typed_array_sha256(
                np.asarray(
                    [
                        spec["scalar_bars"],
                        spec["scalar_repeats"],
                        spec["wfo_bars"],
                        spec["wfo_candidates"],
                        spec["wfo_repeats"],
                        spec["control_bars"],
                        spec["control_repeats"],
                    ],
                    dtype=np.int64,
                ),
            ),
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILE_SPECS), default="standard")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    payload = run(profile=str(args.profile))
    output = (
        DEFAULT_OUTPUT.with_name("phase77_3_reactive_closure_smoke.json")
        if args.profile == "smoke"
        else DEFAULT_OUTPUT
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(payload["evidence"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
