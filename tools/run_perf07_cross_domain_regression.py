#!/usr/bin/env python3
"""Run the PERF-07 affected-domain regression matrix and retain its real result.

The matrix is intentionally explicit.  It covers every shared primitive touched
by the PERF phases and keeps options/unsupported-domain containment visible
instead of treating a green native-event subset as a repository-wide proof.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.measurement_contract import capture_measurement_identity  # noqa: E402


DEFAULT_OUTPUT = ROOT / "benchmarks" / "native_event" / "results" / "perf_07_cross_domain_regression.json"
SCHEMA = "quantbt-perf-07-cross-domain-regression-v1"

TESTS = (
    "tests/test_perf_01_traceability_and_computation.py",
    "tests/test_perf_02_session_reuse.py",
    "tests/test_perf_03_reactive_boundary.py",
    "tests/test_perf_04_native_matching.py",
    "tests/test_perf_05_wfo_evaluation_reuse.py",
    "tests/test_perf_06_research_audit.py",
    "tests/native_event/contract/test_phase51a_v3_next_open.py",
    "tests/native_event/contract/test_phase51b_accounting_numeric.py",
    "tests/test_phase66_rust_target_vectorized.py",
    "tests/test_phase67_rust_shared_portfolio.py",
    "tests/test_phase68_rust_package_authority.py",
    "tests/test_phase69_rust_intrabar_authority.py",
    "tests/test_phase77_2_pct_equity_native.py",
    "tests/test_phase77_native_performance_parity.py",
    "tests/test_phase77_3_reactive_parity.py",
    "tests/options/test_endpoint_contract.py",
    "tests/options/test_result_contract.py",
    "tests/options/test_phase70_correctness_containment.py",
    "tests/test_phase8_arbitrage_phase_h.py",
)


def run(*, python: Path | None = None) -> dict[str, Any]:
    # Preserve the active venv path rather than resolving its Python symlink.
    interpreter = Path(sys.executable) if python is None else python
    if not interpreter.is_file():
        raise ValueError(f"Python interpreter does not exist: {interpreter}")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["MPLCONFIGDIR"] = "/tmp"
    command = [str(interpreter), "-m", "pytest", "-q", *TESTS]
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
        timeout=1_800,
    )
    elapsed = perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"PERF-07 cross-domain regression failed with exit {completed.returncode}:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return {
        "schema": SCHEMA,
        "phase": "PERF-07",
        "status": "passed",
        "command": command,
        "tests": list(TESTS),
        "elapsed_seconds": float(elapsed),
        "stdout_sha256": sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stdout_tail": completed.stdout[-4_000:],
        "stderr_tail": completed.stderr[-4_000:],
        "evidence": {
            "market_calendar_accounting": True,
            "funding_order_lifecycle": True,
            "target_portfolio_package_intrabar": True,
            "reactive_wfo": True,
            "options_containment": True,
            "unsupported_arbitrage_containment": True,
        },
        "measurement_identity": capture_measurement_identity(
            root=ROOT,
            warmup_procedure="deterministic affected-domain regression; timing is recorded only as a soak observation",
            data_sha256=sha256("\n".join(TESTS).encode("utf-8")).hexdigest(),
            intent_sha256=sha256(str(interpreter).encode("utf-8")).hexdigest(),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = run(python=args.python)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(payload["stdout_tail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
