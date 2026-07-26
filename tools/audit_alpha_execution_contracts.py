#!/usr/bin/env python3
"""
Scan alpha source files and classify required QuantBT execution contracts.

Example:
    PYTHONPATH=/root/bobby/pool_alpha python3 quantbt/tools/audit_alpha_execution_contracts.py \
        /root/bobby/pool_alpha/alphas_storage/TA \
        --json-out /tmp/alpha_contracts.json \
        --md-out /tmp/alpha_contracts.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import alpha_report_markdown, build_alpha_certification_report, scan_alpha_directory  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit alpha files for QuantBT execution-contract requirements.")
    parser.add_argument("root", type=Path, help="Alpha source directory to scan")
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "alpha_execution_contracts.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "out" / "alpha_execution_contracts.md")
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    args = parser.parse_args(argv)

    items = scan_alpha_directory(args.root, max_bytes=args.max_bytes)
    report = build_alpha_certification_report(items)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    args.md_out.write_text(alpha_report_markdown(report), encoding="utf-8")
    print(f"scanned={report['total']} json={args.json_out} markdown={args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
