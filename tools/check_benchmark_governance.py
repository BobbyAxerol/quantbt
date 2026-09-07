#!/usr/bin/env python3
"""Validate immutable, workload-scoped native benchmark manifests."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

try:  # Supports both ``python tools/...`` and module-based test loading.
    from measurement_contract import (
        CURRENT_CANDIDATE_VERIFIED,
        HISTORICAL_SCOPE_ONLY,
        MEASUREMENT_CONTRACT_SCHEMA,
        current_candidate_evidence_violations,
        historical_manifest_record,
        load_measurement_contract,
    )
except ModuleNotFoundError:  # pragma: no cover - import style depends on caller.
    from tools.measurement_contract import (
        CURRENT_CANDIDATE_VERIFIED,
        HISTORICAL_SCOPE_ONLY,
        MEASUREMENT_CONTRACT_SCHEMA,
        current_candidate_evidence_violations,
        historical_manifest_record,
        load_measurement_contract,
    )


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "benchmarks" / "native_event" / "manifests"
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"
MEASUREMENT_CONTRACT = MANIFEST_DIR / "phase72_measurement_contract_v1.json"
NON_PROMOTIONAL_MANIFEST_SCHEMAS = frozenset(
    {
        # A Phase 77.1 public workload baseline is deliberately captured on a
        # development tree before a route can be promoted. It has a different
        # evidence contract from immutable product-release manifests and must
        # never be coerced into one merely to satisfy this checker.
        "quantbt-phase77-1-public-workload-manifest-v1",
        # Phase 77.2 and 77.3 are development-tree workload contracts. They
        # record reproducible scope and required evidence, but intentionally
        # cannot promote a public route or release artifact on their own.
        "quantbt-phase77-2-pct-equity-public-wfo-v1",
        "quantbt-phase77-3-reactive-closure-manifest-v1",
    }
)


def _canonical_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _validate_registry_evidence(
    product: dict[str, Any],
    measurement: dict[str, Any],
) -> list[str]:
    """Validate that current promotion cannot consume historical evidence."""

    violations: list[str] = []
    declaration = product.get("measurement_contract")
    if not isinstance(declaration, dict):
        return ["product registry: missing measurement_contract declaration"]
    if declaration.get("id") != measurement.get("measurement_contract_id"):
        violations.append("product registry: measurement contract id mismatch")
    if declaration.get("path") != _relative_path(MEASUREMENT_CONTRACT):
        violations.append("product registry: measurement contract path mismatch")

    route_ids = {str(route["id"]) for route in measurement["routes"]}
    profile_pair_ids = {str(pair["id"]) for pair in measurement["profile_pairs"]}
    evidence_by_workload = product.get("performance_evidence", {})
    if not isinstance(evidence_by_workload, dict):
        return [*violations, "product registry: performance_evidence must be an object"]
    for workload_id, evidence in evidence_by_workload.items():
        label = f"performance evidence {workload_id}"
        if not isinstance(evidence, dict):
            violations.append(f"{label}: must be an object")
            continue
        for key in (
            "measurement_contract_id",
            "route_id",
            "profile_pair",
            "measurement_status",
            "identity_status",
            "promotion_eligible",
        ):
            if key not in evidence:
                violations.append(f"{label}: missing {key}")
        if evidence.get("measurement_contract_id") != measurement.get("measurement_contract_id"):
            violations.append(f"{label}: measurement contract mismatch")
        if str(evidence.get("route_id")) not in route_ids:
            violations.append(f"{label}: unknown route id")
        if str(evidence.get("profile_pair")) not in profile_pair_ids:
            violations.append(f"{label}: unknown profile pair")
        if not isinstance(evidence.get("promotion_eligible"), bool):
            violations.append(f"{label}: promotion_eligible must be boolean")
            continue
        status = evidence.get("measurement_status")
        if status == CURRENT_CANDIDATE_VERIFIED:
            if (
                evidence.get("status") != "pass"
                or evidence.get("identity_status") != "current_candidate"
                or evidence.get("promotion_eligible") is not True
                or evidence.get("end_to_end_faster_than_python") is not True
                or evidence.get("rss_plateau") is not True
            ):
                violations.append(f"{label}: current candidate evidence is incomplete")
            for violation in current_candidate_evidence_violations(evidence, measurement):
                violations.append(f"{label}: {violation}")
        elif evidence.get("promotion_eligible"):
            violations.append(f"{label}: non-current evidence cannot be promotion eligible")
        if status == HISTORICAL_SCOPE_ONLY and evidence.get("identity_status") != "historical_pre_phase72":
            violations.append(f"{label}: historical evidence needs historical_pre_phase72 identity")

    for rule in product.get("promotion_policy", {}).get("rules", []):
        if not rule.get("enabled"):
            continue
        workload_id = str(rule.get("workload_id"))
        evidence = evidence_by_workload.get(workload_id, {})
        if (
            evidence.get("measurement_status") != CURRENT_CANDIDATE_VERIFIED
            or evidence.get("promotion_eligible") is not True
        ):
            violations.append(
                f"promotion rule {rule.get('id')}: requires current candidate measurement evidence"
            )
    return violations


def _validate_baseline_only_manifest(payload: dict[str, Any], *, path: Path) -> list[str]:
    """Validate a non-promotional workload declaration without release semantics."""

    violations: list[str] = []
    if payload.get("phase") != "77.1":
        violations.append(f"{path.name}: baseline manifest phase must be '77.1'")
    if payload.get("promotion_eligible") is not False:
        violations.append(f"{path.name}: baseline-only manifest must not be promotion eligible")
    if not str(payload.get("purpose", "")).startswith("baseline_only_"):
        violations.append(f"{path.name}: baseline-only manifest needs a baseline_only purpose")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not {"smoke", "standard", "long"}.issubset(profiles):
        violations.append(f"{path.name}: baseline-only manifest must declare smoke, standard, and long profiles")
    matrix = payload.get("required_mode_schedule_matrix")
    required_modes = {
        "mode_1_decay",
        "mode_2_sbb",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    }
    if not isinstance(matrix, dict) or set(matrix) != required_modes:
        violations.append(f"{path.name}: baseline-only manifest must declare all five WFO modes")
    return violations


def _validate_phase77_2_manifest(payload: dict[str, Any], *, path: Path) -> list[str]:
    """Validate the non-promotional P77.2 public WFO scope contract."""

    violations: list[str] = []
    if payload.get("phase") != "77.2":
        violations.append(f"{path.name}: phase must be '77.2'")
    if payload.get("promotion_eligible") is not False:
        violations.append(f"{path.name}: P77.2 scope evidence must not be promotion eligible")
    profiles = payload.get("benchmark_profiles")
    if not isinstance(profiles, dict) or not {"smoke", "standard"}.issubset(profiles):
        violations.append(f"{path.name}: P77.2 must declare smoke and standard profiles")
    scope = payload.get("scope")
    if not isinstance(scope, dict) or not {"endpoint", "optimization_modes", "opt_in"}.issubset(scope):
        violations.append(f"{path.name}: P77.2 must bind endpoint, modes, and opt-in policy")
    contracts = payload.get("contracts")
    if not isinstance(contracts, dict) or not {"fee", "slippage", "candidate_account", "final_account"}.issubset(contracts):
        violations.append(f"{path.name}: P77.2 must bind accounting contracts")
    if not isinstance(payload.get("required_parity"), list) or not payload["required_parity"]:
        violations.append(f"{path.name}: P77.2 must declare required parity")
    if not isinstance(payload.get("outputs"), list) or not payload["outputs"]:
        violations.append(f"{path.name}: P77.2 must declare evidence outputs")
    return violations


def _validate_phase77_3_manifest(payload: dict[str, Any], *, path: Path) -> list[str]:
    """Validate the non-promotional P77.3 reactive closure contract."""

    violations: list[str] = []
    if payload.get("phase") != "77.3":
        violations.append(f"{path.name}: phase must be '77.3'")
    if payload.get("promotion_eligible") is not False:
        violations.append(f"{path.name}: P77.3 scope evidence must not be promotion eligible")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not {"smoke", "standard"}.issubset(profiles):
        violations.append(f"{path.name}: P77.3 must declare smoke and standard profiles")
    reactive_contract = payload.get("reactive_contract")
    required_contract_keys = {
        "runtimes",
        "wfo_schedules",
        "selection_modes",
        "account_policy",
        "deadline_safe_point",
    }
    if not isinstance(reactive_contract, dict) or not required_contract_keys.issubset(reactive_contract):
        violations.append(f"{path.name}: P77.3 must bind reactive runtime and accounting semantics")
    if not isinstance(payload.get("required_evidence"), list) or not payload["required_evidence"]:
        violations.append(f"{path.name}: P77.3 must declare required evidence")
    if not isinstance(payload.get("non_claims"), list) or not payload["non_claims"]:
        violations.append(f"{path.name}: P77.3 must declare non-claims")
    return violations


def validate_manifest(
    path: Path,
    *,
    measurement: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
) -> list[str]:
    """Return deterministic violations for one checked benchmark manifest."""

    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    schema = payload.get("schema")
    if schema == MEASUREMENT_CONTRACT_SCHEMA:
        try:
            load_measurement_contract(path, root=ROOT)
        except ValueError as exc:
            violations.append(f"{path.name}: {exc}")
        return violations
    if schema == "quantbt-phase77-1-public-workload-manifest-v1":
        return _validate_baseline_only_manifest(payload, path=path)
    if schema == "quantbt-phase77-2-pct-equity-public-wfo-v1":
        return _validate_phase77_2_manifest(payload, path=path)
    if schema == "quantbt-phase77-3-reactive-closure-manifest-v1":
        return _validate_phase77_3_manifest(payload, path=path)
    if measurement is None:
        measurement = load_measurement_contract(MEASUREMENT_CONTRACT, root=ROOT)
    if product is None:
        product = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
    if payload.get("schema") != "quantbt-native-benchmark-manifest-v1":
        violations.append(f"{path.name}: unsupported schema")
    if not str(payload.get("owner", "")).strip():
        violations.append(f"{path.name}: missing owner")
    current_product_fingerprint = _canonical_fingerprint(PRODUCT_REGISTRY)
    manifest_product_fingerprint = payload.get("product_registry_fingerprint")
    if manifest_product_fingerprint != current_product_fingerprint:
        historical = historical_manifest_record(
            measurement,
            relative_path=_relative_path(path),
        )
        if historical is None:
            violations.append(f"{path.name}: product registry fingerprint drift")
        elif historical.get("product_registry_fingerprint") != manifest_product_fingerprint:
            violations.append(f"{path.name}: historical registry fingerprint drift")
        elif historical.get("manifest_id") != payload.get("manifest_id"):
            violations.append(f"{path.name}: historical manifest id drift")
        elif historical.get("sha256") != _file_sha256(path):
            violations.append(f"{path.name}: historical manifest checksum drift")
    if payload.get("lifecycle_registry_fingerprint") != _canonical_fingerprint(LIFECYCLE_REGISTRY):
        violations.append(f"{path.name}: lifecycle registry fingerprint drift")
    workloads = payload.get("workloads")
    if not isinstance(workloads, list) or not workloads:
        violations.append(f"{path.name}: missing workloads")
        return violations
    ids: set[str] = set()
    for workload in workloads:
        label = str(workload.get("id", "<unknown>"))
        if not label or label in ids:
            violations.append(f"{path.name}: duplicate or empty workload id {label!r}")
        ids.add(label)
        baseline = ROOT / str(workload.get("baseline_path", ""))
        if not baseline.is_file():
            violations.append(f"{path.name}: {label} baseline does not exist")
            continue
        if str(workload.get("baseline_sha256", "")) != _file_sha256(baseline):
            violations.append(f"{path.name}: {label} baseline checksum drift")
        for key in ("contract_ids", "strategy_mode", "profiles", "fixture", "required_result_fields"):
            value = workload.get(key)
            if value in (None, "", []):
                violations.append(f"{path.name}: {label} missing {key}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    args = parser.parse_args(argv)
    try:
        measurement = load_measurement_contract(MEASUREMENT_CONTRACT, root=ROOT)
        product = json.loads(PRODUCT_REGISTRY.read_text(encoding="utf-8"))
        paths = sorted(args.manifest_dir.resolve().glob("*.json"))
        if not paths:
            raise ValueError("no benchmark manifests found")
        violations = _validate_registry_evidence(product, measurement)
        violations.extend(
            item
            for path in paths
            for item in validate_manifest(path, measurement=measurement, product=product)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark governance check failed: {exc}", file=sys.stderr)
        return 1
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("native benchmark governance gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
