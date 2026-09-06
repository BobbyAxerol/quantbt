"""PERF-07 closure integrity tests.

These are intentionally evidence-contract tests.  They do not rerun the long
benchmarks or rebuild wheels; the dedicated PERF-07 tools own that expensive
work and this suite makes stale, partial, or placeholder evidence fail closed.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from tools import performance_closure as closure


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _identity() -> dict[str, object]:
    payload: dict[str, object] = {field: "recorded" for field in closure.IDENTITY_REQUIRED_FIELDS}
    payload.update(
        {
            "git_commit": "0" * 40,
            "git_dirty": False,
            "canonical_source_sha256": "1" * 64,
            "native_extension": {"available": True},
        }
    )
    return payload


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": _digest(path)}


def _rows(prefix: str, count: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"{prefix}-{ordinal:02d}",
            "disposition": "IMPLEMENTED_VERIFIED",
            "evidence": [f"tests/{prefix.lower()}_{ordinal:02d}.py::test_contract"],
        }
        for ordinal in range(1, count + 1)
    ]


def _write_evidence(root: Path) -> dict[str, dict[str, str]]:
    common = root / "combined.json"
    common.write_text(json.dumps({"evidence": {"all_current_qualification_gates": True}}), encoding="utf-8")
    regression = root / "regression.json"
    regression.write_text(json.dumps({"status": "passed", "evidence": {"matrix": True}}), encoding="utf-8")
    pgo = root / "pgo.json"
    pgo.write_text(
        json.dumps(
            {
                "decision": "NOT_BENEFICIAL",
                "guards": {
                    "no_target_cpu_native": True,
                    "no_fast_math_or_panic_or_unsafe_override": True,
                    "financial_capability_changed": False,
                    "enabled_routes_changed": False,
                    "held_out_parity": True,
                },
            }
        ),
        encoding="utf-8",
    )
    wheel = root / "wheel.json"
    wheel.write_text(
        json.dumps(
            {
                "evidence": {
                    "source_hash_parity": True,
                    "clean_install": True,
                    "direct_target_smoke": True,
                    "exact_native_pair": True,
                    "source_tree_import_blocked": True,
                }
            }
        ),
        encoding="utf-8",
    )
    return {name: _reference(path) for name, path in {"combined": common, "regression": regression, "pgo": pgo, "wheel": wheel}.items()}


def _manifest(root: Path) -> dict[str, object]:
    refs = _write_evidence(root)
    return {
        "schema": closure.SCHEMA,
        "status": closure.READY,
        "source_identity": _identity(),
        "phase_results": [
            {"phase": phase, "evidence": [refs["combined"]]} for phase in closure.PHASE_IDS
        ],
        "ap_dispositions": _rows("AP", 12),
        "ac_coverage": _rows("AC", 44),
        "combined_qualification": refs["combined"],
        "cross_domain_regression": refs["regression"],
        "pgo_decision": refs["pgo"],
        "candidate_wheel": refs["wheel"],
        "route_matrix": [
            {
                "id": "bounded_static_route",
                "state": "explicit_support",
                "surface": "public bounded fixture",
                "execution_contract": "typed contract",
                "retention": "score",
                "worker_scope": "single worker",
                "reason": "independent oracle evidence",
            }
        ],
        "open_correctness_blockers": [],
        "audit_compatibility": {"roundtrip_passed": True},
        "rollback": {
            "baseline_contract": "same accounting contract",
            "candidate_scope": "one explicit route",
            "action": "select baseline without dropping audit",
        },
    }


@pytest.fixture()
def patched_identity(monkeypatch):
    expected = _identity()
    monkeypatch.setattr(closure, "capture_closure_identity", lambda _root: expected)
    monkeypatch.setattr(closure, "_is_ancestor", lambda _root, _commit: True)
    return expected


def test_perf07_valid_manifest_requires_all_current_candidate_proofs(tmp_path: Path, patched_identity) -> None:
    assert closure.validate_manifest(_manifest(tmp_path), root=tmp_path) == []


def test_perf07_candidate_wheel_evidence_requires_clean_install(tmp_path: Path, patched_identity) -> None:
    payload = _manifest(tmp_path)
    wheel_path = tmp_path / "wheel.json"
    wheel = json.loads(wheel_path.read_text(encoding="utf-8"))
    wheel["evidence"]["clean_install"] = False
    wheel_path.write_text(json.dumps(wheel), encoding="utf-8")
    payload["candidate_wheel"]["sha256"] = _digest(wheel_path)
    violations = closure.validate_manifest(payload, root=tmp_path)
    assert "candidate_wheel lacks the required clean exact-pair proof" in violations


def test_perf07_manifest_rejects_changed_evidence_or_source_identity(tmp_path: Path, patched_identity) -> None:
    payload = _manifest(tmp_path)
    combined = tmp_path / "combined.json"
    combined.write_text(json.dumps({"evidence": {"all_current_qualification_gates": False}}), encoding="utf-8")
    violations = closure.validate_manifest(payload, root=tmp_path)
    assert any("checksum changed" in item for item in violations)

    payload = _manifest(tmp_path)
    payload["source_identity"]["canonical_source_sha256"] = "2" * 64
    violations = closure.validate_manifest(payload, root=tmp_path)
    assert "source_identity no longer matches the current source tree" in violations


def test_perf07_manifest_rejects_placeholders_and_open_coverage(tmp_path: Path, patched_identity) -> None:
    payload = _manifest(tmp_path)
    payload["rollback"]["action"] = "resolved_by_ci"
    payload["ac_coverage"][0]["disposition"] = "OWNED_BY_LATER_PHASE"
    violations = closure.validate_manifest(payload, root=tmp_path)
    assert "closure contains a forbidden placeholder value" in violations
    assert any("AC-01 has unresolved disposition" in item for item in violations)
