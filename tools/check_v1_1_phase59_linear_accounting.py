#!/usr/bin/env python3
"""Fail closed when the V1.1 Phase 59 accounting contract drifts."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "v1_1_linear_accounting_fill_replay_v2_contract.json"
INVENTORY = ROOT / "benchmarks" / "baselines" / "v1_1_endpoint_inventory.json"
DOCUMENTS = (
    ROOT / "docs" / "contracts" / "v1_1_linear_accounting.md",
    ROOT / "docs" / "contracts" / "v1_1_linear_accounting_fill_replay_v2.md",
    ROOT / "docs" / "endpoint.md",
)
REFERENCE = ROOT / "reference" / "python" / "fill_replay_v2_oracle.py"
RUST_ACCOUNT = ROOT / "rust" / "crates" / "quantbt-engine" / "src" / "account" / "linear_v1.rs"
RUST_REPLAY = ROOT / "rust" / "crates" / "quantbt-engine" / "src" / "fill_replay.rs"
NATIVE_BINDING = ROOT / "rust" / "native_event" / "src" / "lib.rs"
PYTHON_ADAPTER = ROOT / "src" / "quantbt" / "core" / "fill_replay_v2.py"

FORBIDDEN_IMPORTS = {"quantbt", "numba", "numpy", "pandas", "_quantbt_native"}


def _check_contract() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if payload.get("contract_id") != "quantbt-v1_1-linear-accounting-fill-replay-v2":
        raise ValueError("unexpected Phase 59 contract ID")
    if payload.get("authority", {}).get("runtime") != "rust":
        raise ValueError("Phase 59 accounting authority is not Rust")
    if payload.get("market", {}).get("bar_timestamp_semantics") != "close_only":
        raise ValueError("Phase 59 must fail closed for non-close timestamp semantics")
    if payload.get("funding", {}).get("apply_once") != "event_id":
        raise ValueError("funding apply-once contract drift")
    if set(payload.get("funding", {}).get("phases", ())) != {
        "before_fills_at_close",
        "after_fills_at_close",
    }:
        raise ValueError("funding phase contract drift")
    accounting = payload.get("accounting", {})
    if accounting.get("post_cost_margin") != "reject_immutable":
        raise ValueError("post-cost margin immutability contract drift")
    if accounting.get("liquidation") != "deterministic_symbol_order_executable_close_fills":
        raise ValueError("liquidation contract drift")
    trace = payload.get("trace", {})
    if trace.get("schema") != "canonical-trace-v2":
        raise ValueError("Phase 59 canonical trace schema drift")
    if trace.get("cross_backend_state_checkpoint", {}).get("financial_quantum") != 1e-6:
        raise ValueError("Phase 59 canonical state checkpoint quantum drift")


def _check_oracle_boundary() -> None:
    if not REFERENCE.is_file():
        raise ValueError("Phase 59 independent FillReplay V2 oracle is missing")
    tree = ast.parse(REFERENCE.read_text(encoding="utf-8"), filename=str(REFERENCE))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.split(".", 1)[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names = {(node.module or "").split(".", 1)[0]}
        else:
            continue
        forbidden = names & FORBIDDEN_IMPORTS
        if forbidden:
            raise ValueError(f"independent oracle imports forbidden modules {sorted(forbidden)}")


def _check_source_markers() -> None:
    required = {
        RUST_ACCOUNT: ("LinearAccountTransactionV1", "canonical_trace_state_hash", "ReservationMismatch"),
        RUST_REPLAY: ("run_fill_replay_v2", "FundingPhaseV1", "LiquidationFill"),
        NATIVE_BINDING: ("run_fill_replay_v2_native", "fill_replay_v2_output_payload"),
        PYTHON_ADAPTER: ("FillReplayTapeV2", "FundingReplayTapeV2", "FillReplayV2NativeUnavailable"),
    }
    for path, markers in required.items():
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise ValueError(f"Phase 59 source marker missing in {path.relative_to(ROOT)}: {missing}")


def _check_docs() -> None:
    for path in DOCUMENTS:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if len(text.strip()) < 500:
            raise ValueError(f"Phase 59 document is missing or too short: {path.relative_to(ROOT)}")
        if path.name != "endpoint.md" and "v1_1_linear_accounting_fill_replay_v2_contract.json" not in text:
            raise ValueError(f"Phase 59 document does not link its machine contract: {path.relative_to(ROOT)}")
    endpoint = (ROOT / "docs" / "endpoint.md").read_text(encoding="utf-8")
    if 'accounting_backend="rust_v2"' not in endpoint or "funding_replay" not in endpoint:
        raise ValueError("endpoint documentation does not describe the explicit FillReplay V2 route")


def _check_inventory() -> None:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    routes = {row.get("id"): row for row in payload.get("rows", ())}
    rust_route = routes.get("fill_replay_v2_rust")
    legacy_route = routes.get("fill_replay_v1_numba")
    if not isinstance(rust_route, dict) or not isinstance(legacy_route, dict):
        raise ValueError("V1.1 endpoint inventory must list both FillReplay V1 and V2 routes")
    if rust_route.get("maturity") != "a2_domain_certified":
        raise ValueError("FillReplay V2 inventory maturity drift")
    if rust_route.get("authority", {}).get("accounting") != "Rust LinearGrossCrossAccountV1":
        raise ValueError("FillReplay V2 inventory does not identify the Rust accounting authority")
    if legacy_route.get("maturity") != "legacy_accounting_comparator":
        raise ValueError("FillReplay V1 inventory no longer identifies its compatibility role")


def main() -> int:
    _check_contract()
    _check_oracle_boundary()
    _check_source_markers()
    _check_docs()
    _check_inventory()
    print("Phase 59 linear accounting/FillReplay V2 contract and oracle boundary: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"Phase 59 linear accounting validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
