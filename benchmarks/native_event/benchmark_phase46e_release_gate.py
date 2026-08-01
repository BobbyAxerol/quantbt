"""Phase 46E dual-backend release gate.

This wrapper reuses the Phase 46B apples-to-apples benchmark so the release
decision cannot drift from the established artifact contract.  It records
speed, staged RSS, full parity and the explicit policy that ``auto`` remains
Python when any RSS gate is not met.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE_BENCHMARK = Path(__file__).with_name("benchmark_phase46b_score_rss.py")


def _run_source(rows: int, repeats: int) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json") as handle:
        completed = subprocess.run(
            [
                sys.executable,
                str(SOURCE_BENCHMARK),
                "--rows",
                str(rows),
                "--repeats",
                str(repeats),
                "--json-out",
                handle.name,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        # The benchmark writes the JSON file and prints a short status line;
        # reading the file avoids depending on stdout formatting.
        del completed
        return json.loads(Path(handle.name).read_text())


def _speedup(run: dict) -> float:
    return float(run["python"]["median_seconds"]) / float(run["rust"]["median_seconds"])


def _reduction(run: dict, key: str) -> float:
    python_value = float(run["python"][key])
    rust_value = float(run["rust"][key])
    if python_value <= 0.0:
        return 0.0
    return (python_value - rust_value) / python_value


def build_gate(source: dict) -> dict:
    runs = source["runs"]
    parity = source.get("parity", {})
    score_parity = source.get("score_parity", {})
    low = runs["low"]
    high = runs["high"]
    speedups = {"low": _speedup(low), "high": _speedup(high)}
    prepared_reduction = {
        churn: _reduction(runs[churn], "prepared_incremental_rss") for churn in ("low", "high")
    }
    execution_reduction = {
        churn: _reduction(runs[churn], "execution_incremental_peak") for churn in ("low", "high")
    }
    parity_passed = bool(source.get("full_parity_passed", False)) and all(
        bool(item.get("full_parity_passed", False)) for item in parity.values()
    ) and all(bool(item.get("passed", False)) for item in score_parity.values())
    speed_passed = speedups["low"] >= 1.50 and speedups["high"] >= 2.00
    prepared_rss_passed = all(value >= 0.40 for value in prepared_reduction.values())
    execution_rss_passed = all(value >= 0.40 for value in execution_reduction.values())
    plateau_passed = all(
        bool(runs[churn][backend]["rss_plateau"])
        for churn in ("low", "high")
        for backend in ("plateau_python", "plateau_rust")
    )
    absolute_peak_rss = max(
        float(runs[churn][backend]["peak_rss_during_run"])
        for churn in ("low", "high")
        for backend in ("python", "rust")
    )
    absolute_budget_mb = 512.0
    return {
        "phase": "46E",
        "benchmark_source": "benchmark_phase46b_score_rss.py",
        "benchmark_contract": source.get("benchmark_contract", {}),
        "status": "passed" if parity_passed and speed_passed and prepared_rss_passed and execution_rss_passed and plateau_passed else "rss_gate_pending",
        "dual_backend_contract": {
            "python": "full reactive/default/canonical",
            "rust": "explicit capability-gated batched tape",
            "auto": "python until all release gates pass",
            "replay_certified": "audit oracle",
        },
        "gates": {
            "full_parity_100_percent": parity_passed,
            "low_churn_speedup_ge_1_50x": speedups["low"] >= 1.50,
            "high_churn_speedup_ge_2_00x": speedups["high"] >= 2.00,
            "prepared_rss_reduction_ge_40_percent": prepared_rss_passed,
            "execution_rss_reduction_ge_40_percent": execution_rss_passed,
            "absolute_peak_rss_under_budget": absolute_peak_rss <= absolute_budget_mb,
            "rss_plateau_100_runs": plateau_passed,
        },
        "speedup": speedups,
        "prepared_rss_reduction": prepared_reduction,
        "execution_rss_reduction": execution_reduction,
        "absolute_peak_rss_mb": absolute_peak_rss,
        "absolute_rss_budget_mb": absolute_budget_mb,
        "source": source,
        "release_policy": {
            "rust_auto_enabled": False,
            "rust_native_extra_ready": False,
            "reason": "The explicit prepared-RSS gate remains a measured policy gate; no false release claim is made.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json-out", default="benchmarks/native_event/phase46e_release_gate.json")
    args = parser.parse_args()
    result = build_gate(_run_source(args.rows, args.repeats))
    output = ROOT / args.json_out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"phase": result["phase"], "status": result["status"], "gates": result["gates"]}, sort_keys=True))


if __name__ == "__main__":
    main()
