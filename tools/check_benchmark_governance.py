#!/usr/bin/env python3
"""Validate immutable, workload-scoped native benchmark manifests."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "benchmarks" / "native_event" / "manifests"
PRODUCT_REGISTRY = ROOT / "contracts" / "native_event_product_registry.json"
LIFECYCLE_REGISTRY = ROOT / "contracts" / "native_event_contract_registry.json"


def _canonical_fingerprint(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate_manifest(path: Path) -> list[str]:
    """Return deterministic violations for one checked benchmark manifest."""

    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    if payload.get("schema") != "quantbt-native-benchmark-manifest-v1":
        violations.append(f"{path.name}: unsupported schema")
    if not str(payload.get("owner", "")).strip():
        violations.append(f"{path.name}: missing owner")
    if payload.get("product_registry_fingerprint") != _canonical_fingerprint(PRODUCT_REGISTRY):
        violations.append(f"{path.name}: product registry fingerprint drift")
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
        paths = sorted(args.manifest_dir.resolve().glob("*.json"))
        if not paths:
            raise ValueError("no benchmark manifests found")
        violations = [item for path in paths for item in validate_manifest(path)]
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
