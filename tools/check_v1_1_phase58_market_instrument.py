#!/usr/bin/env python3
"""Fail closed when the V1.1 calendar/instrument Phase 58 contract drifts."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "v1_1_market_instrument_v2_contract.json"
DOCUMENTS = (
    ROOT / "docs" / "contracts" / "v1_1_market_calendar_v2.md",
    ROOT / "docs" / "contracts" / "v1_1_instrument_registry_v2.md",
)
REFERENCE = (
    ROOT / "reference" / "python" / "calendar_oracle.py",
    ROOT / "reference" / "python" / "instrument_oracle.py",
)
FORBIDDEN_IMPORTS = {"quantbt", "numba", "numpy", "pandas", "_quantbt_native"}


def _check_contract() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if payload.get("contract_id") != "quantbt-v1_1-market-instrument-v2":
        raise ValueError("unexpected Phase 58 contract ID")
    if payload.get("certified_calendar_default") != "exact_v2":
        raise ValueError("Exact V2 is not the certified calendar default")
    if set(payload.get("calendar", {}).get("policies", ())) != {
        "exact", "intersection", "union", "primary_clock"
    }:
        raise ValueError("calendar policy contract drift")
    if "no_length_based_relabel" not in payload.get("calendar", {}).get("invariants", ()):
        raise ValueError("no-length-relabel invariant is missing")
    rounding = payload.get("instrument_registry", {}).get("rounding", {})
    if rounding.get("risk_reducing_quantity") != "floor_to_step_or_exact_remaining_close":
        raise ValueError("reduce-only rounding contract drift")


def _check_reference_imports() -> None:
    for path in REFERENCE:
        if not path.is_file():
            raise ValueError(f"independent Phase 58 oracle is missing: {path.relative_to(ROOT)}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = set()
            if isinstance(node, ast.Import):
                names = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".", 1)[0]}
            forbidden = names & FORBIDDEN_IMPORTS
            if forbidden:
                raise ValueError(f"oracle imports forbidden modules {sorted(forbidden)}: {path.relative_to(ROOT)}")


def _check_docs() -> None:
    for path in DOCUMENTS:
        if not path.is_file() or len(path.read_text(encoding="utf-8").strip()) < 500:
            raise ValueError(f"Phase 58 document is missing or too short: {path.relative_to(ROOT)}")
        if "v1_1_market_instrument_v2_contract.json" not in path.read_text(encoding="utf-8"):
            raise ValueError(f"Phase 58 document does not link its machine contract: {path.relative_to(ROOT)}")


def main() -> int:
    _check_contract()
    _check_reference_imports()
    _check_docs()
    print("Phase 58 market/calendar/instrument contract and independent oracle boundary: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"Phase 58 market/instrument validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
