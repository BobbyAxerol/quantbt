#!/usr/bin/env python3
"""
Phase 13B native portfolio report-construction benchmark.

The runner reuses the Phase 12B decomposition and writes a focused artifact for
the report-construction optimization pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt.benchmarks.run_phase12_benchmark_nautilus_cert import run_certification  # noqa: E402


def run_report(rows: int = 2_000, symbols: int = 6, repeats: int = 3) -> Dict:
    report = run_certification(rows=rows, symbols=symbols, repeats=repeats, include_nautilus=False)
    bench = report["benchmark_followup"]
    stages = bench["stages"]
    return {
        "status": "pass" if report["status"] == "pass" and bench["status"] == "pass" else "fail",
        "rows": int(rows),
        "symbols": int(symbols),
        "repeats": int(repeats),
        "full_facade_seconds": float(stages["full_facade_seconds"]),
        "prepared_reuse_facade_seconds": float(stages["prepared_reuse_facade_seconds"]),
        "array_preparation_seconds": float(stages["array_preparation_seconds"]),
        "pure_numba_kernel_seconds": float(stages["pure_numba_kernel_seconds"]),
        "report_construction_estimate_seconds": float(stages["report_construction_estimate_seconds"]),
        "report_construction_share_pct": float(stages["report_construction_share_pct"]),
        "pure_kernel_share_pct": float(stages["pure_kernel_share_pct"]),
        "prepared_reuse_speedup": float(stages["prepared_reuse_speedup"]),
        "cython_cpp_recommendation": report["cython_cpp_recommendation"],
        "notes": (
            "Phase 13B keeps accounting unchanged and optimizes report construction "
            "with ndarray-first calculations for funding, diagnostics, exposure, "
            "and rebalance reports."
        ),
    }


def make_markdown(report: Dict) -> str:
    return "\n".join(
        [
            "# Phase 13B Native Portfolio Report Construction",
            "",
            f"Status: **{report['status']}**",
            "",
            f"- Rows: `{report['rows']}`",
            f"- Symbols: `{report['symbols']}`",
            f"- Repeats: `{report['repeats']}`",
            f"- Full facade seconds: `{report['full_facade_seconds']:.6f}`",
            f"- Prepared reuse seconds: `{report['prepared_reuse_facade_seconds']:.6f}`",
            f"- Array preparation seconds: `{report['array_preparation_seconds']:.6f}`",
            f"- Pure Numba kernel seconds: `{report['pure_numba_kernel_seconds']:.6f}`",
            f"- Report construction residual seconds: `{report['report_construction_estimate_seconds']:.6f}`",
            f"- Report construction share: `{report['report_construction_share_pct']:.2f}%`",
            f"- Pure kernel share: `{report['pure_kernel_share_pct']:.2f}%`",
            f"- Prepared reuse speedup: `{report['prepared_reuse_speedup']:.3f}x`",
            "",
            "## Notes",
            "",
            report["notes"],
            "",
            "## Cython/C++ Decision",
            "",
            report["cython_cpp_recommendation"],
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=2_000)
    parser.add_argument("--symbols", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase13_portfolio_report.json")
    parser.add_argument("--markdown", type=Path, default=PACKAGE_DIR / "benchmarks" / "phase13_portfolio_report.md")
    args = parser.parse_args()
    report = run_report(rows=args.rows, symbols=args.symbols, repeats=args.repeats)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(make_markdown(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
