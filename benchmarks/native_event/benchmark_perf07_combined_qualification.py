#!/usr/bin/env python3
"""PERF-07 current-candidate qualification across non-overlapping public routes.

This runner deliberately reports a *matrix*, not one fabricated repository-wide
speedup.  Each row retains its own economic contract, work denominator, and
retention scope.  The combined result proves that the released optimizations
coexist on one candidate source/build; it never multiplies overlapping gains.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
BENCHMARK_DIR = ROOT / "benchmarks" / "native_event"
for _path in (SOURCE_ROOT, ROOT, BENCHMARK_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import benchmark_perf01_observer as perf01  # noqa: E402
import benchmark_perf04_native_matching as perf04  # noqa: E402
import benchmark_perf05_wfo_evaluation_reuse as perf05  # noqa: E402
import benchmark_perf06_research_audit as perf06  # noqa: E402
import benchmark_phase66_rust_target_vectorized as phase66  # noqa: E402
import benchmark_phase77_3_reactive_closure as reactive  # noqa: E402
from tools.measurement_contract import (  # noqa: E402
    canonical_json_sha256,
    capture_measurement_identity,
)


SCHEMA = "quantbt-perf-07-combined-qualification-v1"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "native_event" / "results" / "perf_07_combined_qualification.json"

PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "smoke": {
        "observer": {"bars": 540, "trials": 4, "warmup": 1, "repeats": 5},
        "session_reuse": {"outlier_orders": 10_000, "repeats": 3},
        "reactive_boundary": {"bars": 1_000, "repeats": 2},
        "matching": {"bars": 1_000, "high_orders": 16, "repeats": 3},
        "wfo": {"bars": 2_048, "trials": 8, "repeats": 3},
        "target": {"bars": 5_000, "repeats": 3},
        "reactive_closure": "smoke",
    },
    "standard": {
        "observer": {"bars": 540, "trials": 4, "warmup": 3, "repeats": 30},
        "session_reuse": {"outlier_orders": 100_000, "repeats": 5},
        "reactive_boundary": {"bars": 2_000, "repeats": 5},
        "matching": {"bars": 2_000, "high_orders": 32, "repeats": 5},
        "wfo": {"bars": 2_048, "trials": 16, "repeats": 5},
        "target": {"bars": 20_000, "repeats": 5},
        "reactive_closure": "standard",
    },
}


def _rss_mb() -> float:
    status = Path("/proc/self/status")
    if not status.is_file():
        return 0.0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    return 0.0


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    source = str(SOURCE_ROOT)
    current = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = source if not current else f"{source}{os.pathsep}{current}"
    return environment


def _run_subprocess(command: list[str], *, label: str, timeout_seconds: int) -> tuple[str, float]:
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_environment(),
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    elapsed = perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {completed.returncode}:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout, float(elapsed)


def _session_reuse(spec: Mapping[str, int]) -> dict[str, Any]:
    """Run the owned Rust PERF-02 outlier-reset corpus, not a synthetic probe."""

    with tempfile.TemporaryDirectory(prefix="quantbt-perf07-perf02-") as raw:
        output = Path(raw) / "perf02.json"
        _, elapsed = _run_subprocess(
            [
                "cargo",
                "run",
                "--quiet",
                "--manifest-path",
                str(ROOT / "rust" / "Cargo.toml"),
                "--release",
                "-p",
                "quantbt-execution",
                "--example",
                "perf02_session_reuse",
                "--",
                "--outlier-orders",
                str(spec["outlier_orders"]),
                "--repeats",
                str(spec["repeats"]),
                "--output",
                str(output),
            ],
            label="PERF-02 session-reuse corpus",
            timeout_seconds=300,
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
    return {"elapsed_seconds": elapsed, "result": payload}


def _reactive_boundary(spec: Mapping[str, int]) -> dict[str, Any]:
    """Execute PERF-03 in an isolated process so callback state cannot leak."""

    with tempfile.TemporaryDirectory(prefix="quantbt-perf07-perf03-") as raw:
        root = Path(raw)
        json_output = root / "perf03.json"
        markdown_output = root / "perf03.md"
        _, elapsed = _run_subprocess(
            [
                sys.executable,
                str(BENCHMARK_DIR / "benchmark_perf03_reactive_boundary.py"),
                "--bars",
                str(spec["bars"]),
                "--repeats",
                str(spec["repeats"]),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ],
            label="PERF-03 reactive boundary corpus",
            timeout_seconds=300,
        )
        payload = json.loads(json_output.read_text(encoding="utf-8"))
    return {"elapsed_seconds": elapsed, "result": payload}


def _all_true(values: Mapping[str, Any]) -> bool:
    return all(bool(value) for value in values.values())


def _phase_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep closure evidence legible without discarding the raw result artifact."""

    return {
        "schema": payload.get("schema", payload.get("schema_version")),
        "evidence": dict(payload.get("evidence", {})),
        "measurement_identity": dict(payload.get("measurement_identity", {})),
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    inputs = payload["phase_inputs"]
    wfo = inputs["PERF-05"]["mode_matrix"]
    audit = inputs["PERF-06"]["mode_matrix"]
    wfo_rows = "\n".join(
        f"| `{row['mode']}` | `{row['exact_public_parity']}` | `{row['runtime']['resolved_policy']}` | "
        f"{row['runtime']['cache_hits']} |"
        for row in wfo
    )
    audit_rows = "\n".join(
        f"| `{row['mode']}` | `{row['public_parity']}` | {row['none_seconds_median']:.6f} s | "
        f"{row['full_seconds_median']:.6f} s | {row['full_overhead_pct']:+.2f}% |"
        for row in audit
    )
    return "\n".join(
        (
            "# PERF-07 Combined Qualification",
            "",
            "This artifact is a current-candidate integration qualification. It intentionally does not",
            "publish a single aggregate speedup: the covered routes have different execution contracts,",
            "work denominators, retention levels, and Python decision boundaries.",
            "",
            "## Qualification Scope",
            "",
            f"- Profile: `{payload['profile']}`.",
            "- Candidate source/build identity is attached to the JSON artifact.",
            "- All rows ran against the same checked source candidate; performance claims remain row-scoped.",
            "- Reactive cross-route controls cover public WFO, shared portfolio, bounded package, and intrabar.",
            "",
            "## Five-Mode WFO Reuse",
            "",
            "| Mode | Exact public parity | Reuse policy | Cache hits |",
            "|---|---|---|---:|",
            wfo_rows,
            "",
            "## Five-Mode Research Retention",
            "",
            "| Mode | Public parity | No sidecar | Full ledger | Retention overhead |",
            "|---|---|---:|---:|---:|",
            audit_rows,
            "",
            "## Result",
            "",
            f"- All current qualification gates: `{payload['evidence']['all_current_qualification_gates']}`.",
            f"- Process RSS: `{payload['rss_mb']['start']:.3f}` -> `{payload['rss_mb']['end']:.3f}` MiB; "
            f"peak observed `{payload['rss_mb']['peak']:.3f}` MiB.",
            "- The PGO/build decision and clean-wheel proof are separate immutable artifacts required by",
            "  `quantbt.performance_closure.v1`; this report alone does not promote a route or publish a wheel.",
            "",
        )
    )


def run(*, profile: str = "standard") -> dict[str, Any]:
    """Run the selected current-candidate integration matrix."""

    if profile not in PROFILE_SPECS:
        raise ValueError(f"profile must be one of {', '.join(sorted(PROFILE_SPECS))}")
    spec = PROFILE_SPECS[profile]
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError as exc:  # pragma: no cover - package-extra guard
        raise RuntimeError("PERF-07 qualification requires the optimization extra") from exc

    rss_start = _rss_mb()
    peak = rss_start
    started = perf_counter()

    observer = perf01.run_benchmark(**spec["observer"])
    peak = max(peak, _rss_mb())
    session_reuse = _session_reuse(spec["session_reuse"])
    peak = max(peak, _rss_mb())
    reactive_boundary = _reactive_boundary(spec["reactive_boundary"])
    peak = max(peak, _rss_mb())
    matching = perf04.run(**spec["matching"])
    peak = max(peak, _rss_mb())

    # The WFO runs are separate: PERF-05 measures exact score reuse while
    # PERF-06 measures the opt-in audit cost.  They must never be summed into
    # one claimed speedup.
    wfo_reuse = perf05.run(**spec["wfo"])
    peak = max(peak, _rss_mb())
    research_audit = perf06.run(**spec["wfo"])
    peak = max(peak, _rss_mb())
    direct_target = phase66.run(**spec["target"])
    peak = max(peak, _rss_mb())
    reactive_closure = reactive.run(profile=str(spec["reactive_closure"]))
    peak = max(peak, _rss_mb())
    elapsed = perf_counter() - started

    phase_inputs: dict[str, Any] = {
        "PERF-01": observer,
        "PERF-02": session_reuse,
        "PERF-03": reactive_boundary,
        "PERF-04": matching,
        "PERF-05": wfo_reuse,
        "PERF-06": research_audit,
        "PERF-07": {
            "direct_target": direct_target,
            "reactive_cross_domain_controls": reactive_closure,
        },
    }
    evidence = {
        "observer_economic_parity": bool(observer["economic_parity"]["passed"]),
        "session_reuse_completed": session_reuse["result"]["schema"] == "quantbt-perf-02-session-reuse-v1",
        "reactive_boundary_completed": len(reactive_boundary["result"]["cases"]) == 6,
        "native_matching_parity": all(
            bool(case["terminal"]["score_audit_parity"])
            for case in matching["workloads"].values()
        ),
        "five_mode_reuse_parity": _all_true(wfo_reuse["evidence"]),
        "five_mode_audit_parity": _all_true(research_audit["evidence"]),
        "direct_target_accounting_parity": bool(direct_target["evidence"]["exact_accounting_parity"]),
        "reactive_cross_domain_parity": _all_true(reactive_closure["evidence"]),
        "no_aggregate_speedup_claim": True,
    }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "phase": "PERF-07",
        "status": "current_candidate_qualification_not_promotion",
        "profile": profile,
        "profile_spec": spec,
        "elapsed_seconds": float(elapsed),
        "phase_inputs": phase_inputs,
        "summaries": {
            phase: _phase_summary(value)
            for phase, value in phase_inputs.items()
            if isinstance(value, Mapping) and "schema" in value
        },
        "evidence": {**evidence, "all_current_qualification_gates": _all_true(evidence)},
        "rss_mb": {"start": float(rss_start), "end": float(_rss_mb()), "peak": float(peak)},
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure=(
                "each constituent PERF runner performs its own declared warm-up; PERF-07 runs the "
                "non-overlapping current-candidate matrix sequentially and does not aggregate speedups"
            ),
            data_sha256=canonical_json_sha256({"profile": profile, "phase_inputs": sorted(phase_inputs)}),
            intent_sha256=canonical_json_sha256(spec),
        ),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILE_SPECS), default="standard")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run(profile=str(args.profile))
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["evidence"], indent=2, sort_keys=True))
    return 0 if payload["evidence"]["all_current_qualification_gates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
