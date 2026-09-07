#!/usr/bin/env python3
"""Phase 77.2 public `%_equity` prepared-WFO parity and timing evidence.

This runner deliberately imports the locked Phase 77.1 workload generator and
pairing machinery.  It measures one new explicit capability only:
``target_mode='pct_equity'``, ``target_runtime='rust'``, and
``native_prepared_wfo='require'``.  The reference remains the ordinary legacy
transition engine.  It therefore cannot be read as a generic WFO speed claim.

Examples:

    PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_2_pct_equity_wfo.py \
        --profile smoke
    PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase77_2_pct_equity_wfo.py \
        --profile standard
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
BENCHMARK_DIR = ROOT / "benchmarks" / "native_event"
for _path in (SOURCE_ROOT, ROOT, BENCHMARK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import benchmark_phase77_1_public_matrix as baseline  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks/native_event/results/phase77_2_pct_equity_wfo.json"
SCHEMA = "quantbt-phase77-2-pct-equity-public-wfo-v1"

PCT_EQUITY_ROW = baseline.WorkloadRow(
    identifier="pct_equity_rust_transition_native",
    mode="mode_4_is_only_robust",
    schedule="global",
    route="walk_forward",
    target_mode="pct_equity",
    scoring_backend="endpoint",
    native_policy="require",
    expected_resolution="native_prepared",
    selection_contract=(
        "IS-only temporal/plateau selection; Rust owns fresh candidate scoring "
        "and the one final stitched transition account only under explicit opt-in"
    ),
)


def _market_for_profile(profile: str):
    spec = baseline.PROFILE_SPECS[profile]
    data = baseline._market(int(spec["bars"]), frequency=str(spec["frequency"]))
    data.attrs.update(
        {
            "phase77_1_frequency": str(spec["frequency"]),
            "phase77_1_split_mode": str(spec["split_mode"]),
            "phase77_1_split_frequency": str(spec["split_frequency"]),
            "phase77_1_train_window": str(spec["train_window"]),
        }
    )
    return data, spec


def _assert_pct_equity_public_parity(reference: Any, native: Any) -> None:
    """Compare the actual legacy public surface, not an invented V2 schema."""

    pd.testing.assert_series_equal(reference.equity, native.equity, check_exact=False, atol=1.0e-10)
    pd.testing.assert_series_equal(reference.returns, native.returns, check_exact=False, atol=1.0e-12)
    pd.testing.assert_frame_equal(reference.positions, native.positions, check_exact=False, atol=0.0)
    assert reference.liquidated is native.liquidated
    assert reference.liquidation_bar == native.liquidation_bar
    assert reference.full_report() == native.full_report()
    assert baseline._result_fingerprint(reference) == baseline._result_fingerprint(native)
    route = native.metadata.get("walk_forward_native_final_execution", {})
    if route.get("resolved") != "rust_pct_equity_transition_v1":
        raise AssertionError(f"native result did not use the required final transition route: {route}")


def _run_pct_equity_pair(row, data, *, trials: int, repeats: int) -> dict[str, Any]:
    """Mirror the locked Phase 77.1 pairing protocol with the legacy schema."""

    reference_warm, _ = baseline._run_endpoint(row, data, native_policy="off", trials=trials, profile=True)
    native_warm, _ = baseline._run_endpoint(row, data, native_policy="require", trials=trials, profile=True)
    _assert_pct_equity_public_parity(reference_warm, native_warm)
    prepared_warm = baseline._resolved_native_metadata(native_warm)
    if prepared_warm.get("resolved_policy") != "native_prepared":
        raise AssertionError(f"{row.identifier} did not enter the declared native prepared route: {prepared_warm}")

    reference_times: list[float] = []
    native_times: list[float] = []
    rss_samples: list[dict[str, float]] = []
    reference_result = reference_warm
    native_result = native_warm
    for repeat in range(int(repeats)):
        gc.collect()
        if repeat % 2 == 0:
            reference_result, reference_elapsed = baseline._run_endpoint(
                row, data, native_policy="off", trials=trials, profile=True
            )
            native_result, native_elapsed = baseline._run_endpoint(
                row, data, native_policy="require", trials=trials, profile=True
            )
        else:
            native_result, native_elapsed = baseline._run_endpoint(
                row, data, native_policy="require", trials=trials, profile=True
            )
            reference_result, reference_elapsed = baseline._run_endpoint(
                row, data, native_policy="off", trials=trials, profile=True
            )
        _assert_pct_equity_public_parity(reference_result, native_result)
        reference_times.append(float(reference_elapsed))
        native_times.append(float(native_elapsed))
        rss_samples.append(baseline._memory_snapshot_mb())

    reference = baseline._summary(
        row,
        reference_result,
        elapsed=reference_times[-1],
        lane="legacy_pct_equity_transition_reference",
        samples=reference_times,
    )
    native = baseline._summary(
        row,
        native_result,
        elapsed=native_times[-1],
        lane="rust_pct_equity_transition_prepared",
        samples=native_times,
    )
    native["paired_speedup_vs_reference"] = float(median(reference_times) / median(native_times))
    return {
        "status": "measured_pair_parity_passed",
        "reference": reference,
        "native": native,
        "native_prepared_wfo": baseline._resolved_native_metadata(native_result),
        "rss_pss_samples_mb": rss_samples,
        "rss_pss_tail_spread_mb": {
            key: float(max(sample[key] for sample in rss_samples) - min(sample[key] for sample in rss_samples))
            for key in ("rss_mb", "pss_mb")
        },
    }


def run(*, profile: str = "smoke") -> dict[str, Any]:
    """Run the exact Phase 77.1 pair protocol for the new `%_equity` route."""

    if profile not in baseline.PROFILE_SPECS:
        raise ValueError(f"profile must be one of {', '.join(sorted(baseline.PROFILE_SPECS))}")
    if profile == "long":
        raise ValueError("Phase 77.2 long stress is intentionally not an implicit release benchmark")
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - install guard
        raise RuntimeError("Phase 77.2 public benchmark requires Optuna") from exc

    data, spec = _market_for_profile(profile)
    pair = _run_pct_equity_pair(
        PCT_EQUITY_ROW,
        data,
        trials=int(spec["trials"]),
        repeats=int(spec["repeats"]),
    )
    native = dict(pair["native"])
    reference = dict(pair["reference"])
    prepared = dict(pair.get("native_prepared_wfo", {}) or {})
    if prepared.get("score_adapter") != "scalar_columns_v1":
        raise AssertionError("Phase 77.2 benchmark did not use the scalar-column score adapter")
    if int(prepared.get("score_python_row_objects", -1)) != 0:
        raise AssertionError("Phase 77.2 benchmark materialized Python score rows")

    return baseline._json_value(
        {
            "schema": SCHEMA,
            "phase": "77.2",
            "status": "paired_public_pct_equity_parity_passed",
            "profile": {"id": profile, **spec},
            "workload": {
                "id": PCT_EQUITY_ROW.identifier,
                "target_mode": PCT_EQUITY_ROW.target_mode,
                "target_runtime": "rust",
                "prepared_policy": "require",
                "contract": "pct_equity_transition_v1",
                "reference_authority": "legacy_pct_equity_transition_v1",
                "native_score_adapter": "scalar_columns_v1",
                "final_account": "rust_pct_equity_transition_v1",
            },
            "paired_result": pair,
            "compatibility_requirements": {
                "fee": "legacy fee / 2 must equal explicit canonical fee_rate when both are supplied",
                "slippage": "legacy slippage must equal ExecutionConfig.slippage_bps when both are supplied",
                "position_surface": "public positions remain processed weights; accepted units are metadata.pct_equity_transition.accepted_positions",
                "auto_policy": "auto preserves the legacy scorer; require plus target_runtime='rust' is explicit opt-in",
            },
            "measurement_identity": baseline.capture_measurement_identity(
                root=ROOT,
                warmup_procedure=(
                    "one untimed legacy/Rust warm pair with complete public parity, then alternating paired "
                    "endpoint runs using the unchanged Phase 77.1 generator and profile"
                ),
                data_sha256=baseline.typed_array_sha256(
                    data.index.asi8,
                    data[["open", "high", "low", "close", "volume", "funding_rate"]].to_numpy(dtype=float),
                ),
                intent_sha256=baseline._stable_hash(
                    {
                        "workload": PCT_EQUITY_ROW.identifier,
                        "profile": profile,
                        "reference": reference.get("fingerprint"),
                        "native": native.get("fingerprint"),
                    }
                ),
            ),
        }
    )


def _markdown(payload: Mapping[str, Any]) -> str:
    pair = payload["paired_result"]
    native = pair["native"]
    reference = pair["reference"]
    speedup = float(native["timing_seconds"]["median"]) and (
        float(reference["timing_seconds"]["median"]) / float(native["timing_seconds"]["median"])
    )
    return "\n".join(
        [
            "# Phase 77.2 Percent-Equity Public WFO Evidence",
            "",
            "This is a paired legacy-versus-explicit-Rust `%_equity` transition contract measurement.",
            "It is not a generic WFO, portfolio, reactive, or Mode 2 speed claim.",
            "",
            "## Workload",
            "",
            (
                f"- `{payload['profile']['bars']}` bars at `{payload['profile']['frequency']}`, "
                f"`{payload['profile']['split_frequency']}` folds, `{payload['profile']['trials']}` trials, "
                f"and `{payload['profile']['repeats']}` alternating post-warm repeats."
            ),
            "- Reference: legacy transition-sized `pct_equity` engine.",
            "- Native: `target_runtime='rust'` plus `native_prepared_wfo='require'`.",
            "- Score adapter: `scalar_columns_v1`; no per-row Python score dataclass/dict is created inside the score boundary.",
            "",
            "## Result",
            "",
            "| Lane | Median | P95 | Native score rows |",
            "|---|---:|---:|---:|",
            (
                "| legacy reference | {:.6f} s | {:.6f} s | {} |".format(
                    float(reference["timing_seconds"]["median"]),
                    float(reference["timing_seconds"]["p95"]),
                    reference["native_score_rows"],
                )
            ),
            (
                "| explicit Rust transition | {:.6f} s | {:.6f} s | {} |".format(
                    float(native["timing_seconds"]["median"]),
                    float(native["timing_seconds"]["p95"]),
                    native["native_score_rows"],
                )
            ),
            f"- Paired speedup: `{speedup:.3f}x` (same named workload only).",
            "",
            "## Contract",
            "",
            "- Rust preserves first-bar snapshot, transition-only resize, no drift rebalance, funding on carried units, rejection-without-retry, and raw public signal positions.",
            "- A conflicting legacy/V2 fee or slippage declaration fails closed rather than producing a falsely comparable run.",
            "- Full parity includes selection, stitched output, equity, returns, raw positions, and public metrics before samples are recorded.",
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "standard"), default="smoke")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = run(profile=args.profile)
    default = DEFAULT_OUTPUT if args.profile == "smoke" else DEFAULT_OUTPUT.with_name(
        "phase77_2_pct_equity_wfo_standard.json"
    )
    output = default if args.output is None else args.output
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
