#!/usr/bin/env python3
"""Validate the Phase 54B.4 native migration/deletion audit.

The audit deliberately records retained compatibility surfaces as well as
future deletion candidates.  It prevents a release note from describing a
path as removed merely because a newer Rust path exists.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "contracts" / "native_event_deletion_manifest.json"
_STATES = {"retained", "deferred", "removed"}
_REQUIRED = {
    "id",
    "paths",
    "state",
    "deletion_approved",
    "replacement",
    "replacement_paths",
    "migration_docs",
    "tests",
    "compatibility_window",
    "rollback",
    "owner",
}


def _relative_path(root: Path, value: object, *, label: str) -> Path:
    candidate = Path(str(value))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{label} must be a repository-relative path")
    return root / candidate


def _non_empty_strings(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(str(item).strip() for item in value):
        raise ValueError(f"{label} must be a non-empty list of strings")
    return [str(item) for item in value]


def validate_migration_audit(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    root: Path = ROOT,
) -> list[str]:
    """Return deterministic audit violations without modifying the repository."""

    payload: Mapping[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    if payload.get("schema") != "quantbt-native-deletion-manifest-v1":
        violations.append("unsupported native deletion manifest schema")
    if str(payload.get("phase", "")) != "54B.4":
        violations.append("native deletion manifest must be owned by Phase 54B.4")
    if payload.get("root_source_policy") != "retained_byte_identity_gated_until_separate_approved_breaking_cleanup":
        violations.append("root source policy must retain the byte-identity-gated mirror")

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return violations + ["native deletion manifest requires non-empty candidates"]

    ids: set[str] = set()
    root_candidate: Mapping[str, Any] | None = None
    for item in candidates:
        if not isinstance(item, Mapping):
            violations.append("native deletion manifest candidate must be an object")
            continue
        identifier = str(item.get("id", ""))
        if not identifier or identifier in ids:
            violations.append(f"duplicate or empty native deletion candidate id: {identifier!r}")
        ids.add(identifier)
        missing = sorted(_REQUIRED - set(item))
        if missing:
            violations.append(f"{identifier or '<missing>'}: missing fields: {', '.join(missing)}")
            continue
        state = str(item["state"])
        if state not in _STATES:
            violations.append(f"{identifier}: invalid state {state!r}")
        if not isinstance(item["deletion_approved"], bool):
            violations.append(f"{identifier}: deletion_approved must be boolean")
        if state != "removed" and bool(item["deletion_approved"]):
            violations.append(f"{identifier}: only a removed candidate may be deletion-approved")
        try:
            paths = _non_empty_strings(item["paths"], label=f"{identifier}.paths")
            replacements = _non_empty_strings(
                item["replacement_paths"], label=f"{identifier}.replacement_paths"
            )
            docs = _non_empty_strings(item["migration_docs"], label=f"{identifier}.migration_docs")
            tests = _non_empty_strings(item["tests"], label=f"{identifier}.tests")
        except ValueError as exc:
            violations.append(str(exc))
            continue
        for value in paths:
            path = _relative_path(root, value, label=f"{identifier}.paths")
            if state == "removed" and path.exists():
                violations.append(f"{identifier}: removed path still exists: {value}")
            if state != "removed" and not path.exists():
                violations.append(f"{identifier}: retained/deferred path is missing: {value}")
        for value in replacements + docs + tests:
            path = _relative_path(root, value, label=f"{identifier}.references")
            if not path.exists():
                violations.append(f"{identifier}: referenced replacement/doc/test is missing: {value}")
        for key in ("replacement", "compatibility_window", "rollback", "owner"):
            if not str(item[key]).strip():
                violations.append(f"{identifier}: {key} must be non-empty")
        if identifier == "root_python_mirror":
            root_candidate = item

    if root_candidate is None:
        violations.append("root_python_mirror candidate is required")
    elif (
        str(root_candidate.get("state")) != "retained"
        or bool(root_candidate.get("deletion_approved"))
        or not {"__init__.py", "endpoint.py", "walkforward.py", "backends", "core"}.issubset(
            {str(item) for item in root_candidate.get("paths", ())}
        )
    ):
        violations.append(
            "root_python_mirror must retain the root module/package compatibility markers "
            "and remain not deletion-approved"
        )
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        violations = validate_migration_audit(args.manifest.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"native release handoff audit failed: {exc}", file=sys.stderr)
        return 1
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("native release handoff/deletion audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
