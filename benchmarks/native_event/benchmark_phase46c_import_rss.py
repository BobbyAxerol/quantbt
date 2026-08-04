"""Fresh-process import/RSS evidence for Phase 46C.

Run from the repository root with the source layout selected, for example::

    MPLCONFIGDIR=/tmp PYTHONPATH=src poetry run python \
        benchmarks/native_event/benchmark_phase46c_import_rss.py

The child process deliberately starts outside the repository so the root
compatibility mirror cannot shadow ``src/quantbt``. RSS is reported as a
process floor, not as an engine execution-memory claim.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
FORBIDDEN = ("matplotlib", "seaborn", "optuna", "nautilus_trader", "quantstats")


def _rss_bytes() -> int:
    with Path("/proc/self/statm").open(encoding="utf-8") as handle:
        resident_pages = int(handle.read().split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE")


def _child_import() -> None:
    import quantbt as _quantbt  # noqa: F401

    loaded = sorted(
        name
        for name in sys.modules
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN)
    )
    before_endpoint = _rss_bytes()
    from quantbt import QuantBTEndpoint

    print(
        json.dumps(
            {
                "rss_after_import_quantbt": before_endpoint,
                "rss_after_endpoint_export": _rss_bytes(),
                "modules_loaded": len(sys.modules),
                "forbidden_modules": loaded,
                "endpoint_module": QuantBTEndpoint.__module__,
            }
        )
    )


def _run_child() -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(SOURCE_ROOT),
            "MPLCONFIGDIR": "/tmp",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        cwd="/tmp",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _importtime_summary() -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(SOURCE_ROOT),
            "MPLCONFIGDIR": "/tmp",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import quantbt"],
        cwd="/tmp",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in completed.stderr.splitlines() if line.strip()]
    return {"importtime_line_count": len(lines), "importtime_tail": lines[-3:]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        _child_import()
        return

    report = {
        "phase": "46C",
        "source_root": str(SOURCE_ROOT),
        "cwd_for_child": "/tmp",
        "import": _run_child(),
        "importtime": _importtime_summary(),
    }
    report["passed"] = (
        report["import"]["forbidden_modules"] == []
        and report["import"]["endpoint_module"] == "quantbt.endpoint"
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
