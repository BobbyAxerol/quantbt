#!/usr/bin/env python3
"""Fail closed when Phase 57's independent correctness foundation drifts."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "v1_1_correctness_contract.json"
REFERENCE_ROOT = ROOT / "reference" / "python"
DOCUMENTS = (
    ROOT / "docs" / "contracts" / "v1_1_execution_clock.md",
    ROOT / "docs" / "contracts" / "v1_1_linear_accounting.md",
    ROOT / "docs" / "contracts" / "v1_1_canonical_trace_v2.md",
)
FORBIDDEN_IMPORTS = {"quantbt", "numba", "numpy", "pandas", "_quantbt_native"}
REQUIRED_MUTATIONS = {
    "funding_sign",
    "fee_side",
    "fill_accounting_order",
    "next_open_vs_same_close",
    "quantity_rounding_direction",
    "maintenance_comparison",
    "oco_sibling_cancellation",
    "calendar_row_relabel",
}


def _check_reference_imports() -> None:
    expected = {
        "linear_accounting_oracle.py",
        "fill_replay_oracle.py",
        "timing_oracle.py",
    }
    present = {path.name for path in REFERENCE_ROOT.glob("*.py")}
    missing = expected - present
    if missing:
        raise ValueError(f"independent oracle files are missing: {sorted(missing)}")
    for path in sorted(REFERENCE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".", 1)[0]}
            else:
                continue
            forbidden = names & FORBIDDEN_IMPORTS
            if forbidden:
                raise ValueError(f"independent oracle imports forbidden module(s) {sorted(forbidden)}: {path.relative_to(ROOT)}")


def _check_contract() -> None:
    if not CONTRACT.is_file():
        raise ValueError("Phase 57 machine contract is missing")
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if payload.get("contract_id") != "quantbt-v1_1-correctness-foundation-v1":
        raise ValueError("unexpected Phase 57 contract ID")
    trace = payload.get("canonical_trace_v2", {})
    if trace.get("schema_version") != "canonical-trace-v2":
        raise ValueError("Canonical Trace V2 schema is not frozen")
    if trace.get("serializer") != "canonical-little-endian-v1":
        raise ValueError("Canonical Trace V2 serializer is not frozen")
    if trace.get("hash") != "fnv1a-dual-128-v1":
        raise ValueError("Canonical Trace V2 hash is not frozen")
    mutations = set(payload.get("mutation_catalog", ()))
    if mutations != REQUIRED_MUTATIONS:
        raise ValueError(f"mutation catalog drift: expected={sorted(REQUIRED_MUTATIONS)} got={sorted(mutations)}")
    tolerance = payload.get("tolerance_policy", {})
    for field in ("ids_status_timestamps", "quantity", "price", "cash_fee_funding_margin_pnl", "metrics"):
        if field not in tolerance:
            raise ValueError(f"field-specific tolerance is missing: {field}")


def _check_documents() -> None:
    for path in DOCUMENTS:
        if not path.is_file() or len(path.read_text(encoding="utf-8").strip()) < 200:
            raise ValueError(f"Phase 57 specification document is missing or too short: {path.relative_to(ROOT)}")


def main() -> int:
    _check_contract()
    _check_reference_imports()
    _check_documents()
    print("Phase 57 correctness foundation contract, docs, and independent oracle imports: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"Phase 57 foundation validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
