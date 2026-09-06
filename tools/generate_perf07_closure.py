#!/usr/bin/env python3
"""Generate and validate the current-candidate PERF-07 handoff manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.performance_closure import (  # noqa: E402
    AC_IDS,
    AP_IDS,
    PHASE_IDS,
    READY,
    SCHEMA,
    capture_closure_identity,
    evidence_reference,
    require_valid_manifest,
)


RESULTS = ROOT / "benchmarks" / "native_event" / "results"
TRACEABILITY = ROOT / "benchmarks" / "native_event" / "traceability" / "perf_01_traceability_v1.json"
DEFAULT_OUTPUT = RESULTS / "perf_07_performance_closure.json"


ROUTE_MATRIX: tuple[dict[str, str], ...] = (
    {
        "id": "event_static_orders",
        "state": "explicit_support",
        "surface": "QuantBTEndpoint.event_driven(input_mode='orders')",
        "execution_contract": "event_lifecycle_v2/v3 typed static tape",
        "retention": "score/compact/audit as declared",
        "worker_scope": "single prepared native execution request",
        "reason": "current static lifecycle, canonical trace, and wheel smoke evidence",
    },
    {
        "id": "native_strategy_ir",
        "state": "explicit_support",
        "surface": "QuantBTEndpoint.event_driven(strategy=NativeStrategyIR)",
        "execution_contract": "typed static/IR lifecycle request",
        "retention": "score/compact/audit as declared",
        "worker_scope": "one Rust-owned prepared request per run/batch",
        "reason": "bounded IR has an explicit native authority and oracle corpus",
    },
    {
        "id": "walk_forward_generic_callback",
        "state": "safe_baseline",
        "surface": "QuantBTEndpoint.walk_forward with arbitrary Python strategy callback",
        "execution_contract": "Python orchestration, causal fold lifecycle, endpoint scorer",
        "retention": "financial/research plan exactly as requested",
        "worker_scope": "declared sequential or supported reactive schedule",
        "reason": "generic callback semantics retain Python decision authority; no blanket Rust promotion",
    },
    {
        "id": "walk_forward_prepared_signal",
        "state": "explicit_support",
        "surface": "prepared static signal/IR WFO companion",
        "execution_contract": "typed native candidate-fold score request",
        "retention": "score or explicit cold audit replay",
        "worker_scope": "run-local prepared market and bounded native batch",
        "reason": "explicit static/IR contract only; not a generic callback substitution",
    },
    {
        "id": "walk_forward_pct_equity_transition",
        "state": "explicit_support",
        "surface": "pct_equity target runtime='rust' plus native_prepared_wfo='require'",
        "execution_contract": "legacy transition semantics with canonical one-way fees",
        "retention": "prepared scalar score and standard final account result",
        "worker_scope": "single-symbol prepared candidate scorer",
        "reason": "explicit opt-in route preserves legacy transition/account parity",
    },
    {
        "id": "direct_target_vectorized",
        "state": "explicit_support",
        "surface": "NativeVectorizedBackend typed target units/notional/weight/fraction",
        "execution_contract": "close-target V2 same-close typed request",
        "retention": "score/compact/audit profile contract",
        "worker_scope": "one prepared Rust request with no generic order arena",
        "reason": "direct-target oracle, accounting, and clean-wheel smoke are explicit",
    },
    {
        "id": "shared_account_portfolio",
        "state": "explicit_support",
        "surface": "NativePortfolioBackend declared shared-account target policy",
        "execution_contract": "linear quote-settled shared account and declared admission policy",
        "retention": "score/compact/audit under a common attribution contract",
        "worker_scope": "one prepared shared-account native executor",
        "reason": "bounded target portfolio only; generic planning remains a safe baseline",
    },
    {
        "id": "bounded_package_arbitrage",
        "state": "explicit_support",
        "surface": "typed bounded package/scenario execution",
        "execution_contract": "same-account deterministic bar transaction with explicit package policy",
        "retention": "score/compact/audit with actual-fill dependency provenance",
        "worker_scope": "one native package request or bounded scenario batch",
        "reason": "cross-venue/multi-currency unsupported shapes remain rejected",
    },
    {
        "id": "single_symbol_intrabar",
        "state": "explicit_support",
        "surface": "QuantBTEndpoint.intrabar_bracket_rust explicit route",
        "execution_contract": "single-symbol intrabar bracket V1 with Numba oracle",
        "retention": "score/compact/audit as explicitly requested",
        "worker_scope": "one prepared Rust intrabar request",
        "reason": "bounded contract has path/fill/account parity; no generic intrabar auto-promotion",
    },
    {
        "id": "reactive_python_strategy",
        "state": "safe_baseline",
        "surface": "QuantBTEndpoint.event_driven with arbitrary reactive Python strategy",
        "execution_contract": "Python decision boundary with Rust numeric co-runtime when explicitly supported",
        "retention": "public/score/audit according to reactive protocol",
        "worker_scope": "declared R1/R2/R3 or W3 schedule only",
        "reason": "Python callback authority, dynamic mutation, and unsupported schedules remain explicit",
    },
    {
        "id": "options_containment",
        "state": "safe_baseline",
        "surface": "QuantBTEndpoint.options",
        "execution_contract": "declared option capability registry and Python option engine",
        "retention": "option ledger/report contract",
        "worker_scope": "Python option execution only",
        "reason": "outside Rust-primary scope; unsupported exercise/quanto/physical shapes fail or label explicitly",
    },
    {
        "id": "unsupported_cross_venue_or_inverse_package",
        "state": "rejected",
        "surface": "generic cross-venue, multi-currency, inverse/quanto package request",
        "execution_contract": "no nearest supported native specialization",
        "retention": "none because execution is rejected before tape preparation",
        "worker_scope": "not applicable",
        "reason": "fail-closed capability containment is part of the certified behavior",
    },
)


def _load(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _dispositions(trace: Mapping[str, Any], *, kind: str, expected_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = trace.get("ap_dispositions" if kind == "ap" else "ac_coverage")
    if not isinstance(rows, list):
        raise ValueError(f"traceability artifact lacks {kind} rows")
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, Mapping)}
    if set(by_id) != set(expected_ids):
        raise ValueError(f"traceability artifact does not contain the required {kind} IDs")
    result: list[dict[str, Any]] = []
    for identifier in expected_ids:
        source = by_id[identifier]
        state = str(source.get("state", ""))
        evidence = source.get("evidence")
        if isinstance(evidence, str):
            evidence_rows = [evidence]
        elif isinstance(evidence, list):
            evidence_rows = [str(item) for item in evidence if str(item)]
        else:
            evidence_rows = []
        if kind == "ap":
            disposition = state
        else:
            disposition = "IMPLEMENTED_VERIFIED" if state.startswith("COVERED_") else state
        result.append({"id": identifier, "disposition": disposition, "evidence": evidence_rows})
    return result


def build_manifest(
    *,
    root: Path = ROOT,
    combined_path: Path = RESULTS / "perf_07_combined_qualification.json",
    regression_path: Path = RESULTS / "perf_07_cross_domain_regression.json",
    pgo_path: Path = RESULTS / "perf_07_pgo_decision.json",
    wheel_path: Path = RESULTS / "perf_07_candidate_wheel.json",
    traceability_path: Path = TRACEABILITY,
) -> dict[str, Any]:
    """Build a candidate-bound closure from already-generated real evidence."""

    root = root.resolve()
    combined = _load(combined_path)
    regression = _load(regression_path)
    pgo = _load(pgo_path)
    wheel = _load(wheel_path)
    trace = _load(traceability_path)
    if combined.get("schema") != "quantbt-perf-07-combined-qualification-v1":
        raise ValueError("combined qualification has an unexpected schema")
    if regression.get("status") != "passed" or not all(regression.get("evidence", {}).values()):
        raise ValueError("cross-domain regression did not pass")
    if pgo.get("decision") not in {"IMPLEMENTED_VERIFIED", "NOT_BENEFICIAL"}:
        raise ValueError("PGO/build evidence has no valid decision")
    if not all(wheel.get("evidence", {}).values()):
        raise ValueError("candidate wheel evidence did not pass")
    if not bool(combined.get("evidence", {}).get("all_current_qualification_gates")):
        raise ValueError("combined qualification did not pass")

    combined_ref = evidence_reference(root, combined_path)
    regression_ref = evidence_reference(root, regression_path)
    pgo_ref = evidence_reference(root, pgo_path)
    wheel_ref = evidence_reference(root, wheel_path)
    trace_ref = evidence_reference(root, traceability_path)
    phase_results = [
        {
            "phase": phase,
            "evidence": [
                evidence_reference(root, combined_path, pointer=f"#/phase_inputs/{phase}"),
                trace_ref,
            ],
        }
        for phase in PHASE_IDS
    ]
    ap_rows = _dispositions(trace, kind="ap", expected_ids=AP_IDS)
    # The static trace records the portable build policy; the decision artifact
    # carries the concrete current-candidate PGO result.
    for row in ap_rows:
        if row["id"] == "AP-12":
            row["disposition"] = str(pgo["decision"])
            row["evidence"].append(pgo_ref["path"])
    ac_rows = _dispositions(trace, kind="ac", expected_ids=AC_IDS)
    source_identity = capture_closure_identity(root)
    return {
        "schema": SCHEMA,
        "status": READY,
        "source_identity": source_identity,
        "phase_results": phase_results,
        "ap_dispositions": ap_rows,
        "ac_coverage": ac_rows,
        "combined_qualification": combined_ref,
        "cross_domain_regression": regression_ref,
        "pgo_decision": pgo_ref,
        "candidate_wheel": wheel_ref,
        "route_matrix": [dict(row) for row in ROUTE_MATRIX],
        "audit_compatibility": {
            "roundtrip_passed": bool(combined["phase_inputs"]["PERF-06"]["evidence"]["all_legacy_trial_exports_present"]),
            "evidence": "tests/test_perf_06_research_audit.py::test_perf06_columnar_codec_is_immutable_exact_and_never_uses_repr_identity",
        },
        "performance": {
            "combined_status": "qualified per route; no aggregate speedup",
            "uncertainty": "each referenced benchmark reports its own paired sample count/median/p95 or RSS scope",
            "evidence": combined_ref,
        },
        "open_correctness_blockers": [],
        "rollback": {
            "baseline_contract": "retain existing Python/Numba compatibility routes and declared result/audit schemas",
            "candidate_scope": "only the explicit/auto-eligible rows in route_matrix",
            "action": "disable the affected explicit native selection and rerun the same contract-compatible baseline; never replay or reconstruct missing audit data",
        },
        "research_scope": {
            "prefix_checkpoints": "not promoted beyond each route's declared reducer/checkpoint contract",
            "inert_blocks": "not a public performance claim",
            "free_threaded_compiled_gpu_new_domains": "outside this closure and require a separate capability/evidence decision",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined", type=Path, default=RESULTS / "perf_07_combined_qualification.json")
    parser.add_argument("--regression", type=Path, default=RESULTS / "perf_07_cross_domain_regression.json")
    parser.add_argument("--pgo", type=Path, default=RESULTS / "perf_07_pgo_decision.json")
    parser.add_argument("--wheel", type=Path, default=RESULTS / "perf_07_candidate_wheel.json")
    parser.add_argument("--traceability", type=Path, default=TRACEABILITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build_manifest(
        combined_path=args.combined.resolve(),
        regression_path=args.regression.resolve(),
        pgo_path=args.pgo.resolve(),
        wheel_path=args.wheel.resolve(),
        traceability_path=args.traceability.resolve(),
    )
    require_valid_manifest(payload, root=ROOT)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PERF-07 closure manifest written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
