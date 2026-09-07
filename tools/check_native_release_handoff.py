#!/usr/bin/env python3
"""Validate the active native migration/deletion audit.

Phase 54B.4 originally retained a byte-identical root Python mirror.  NEXT-03
retired that mirror after an independent canonical-source inventory and clean
consumer proof.  The manifest keeps that historical policy visible while the
active gate verifies the current canonical-only source layout.
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
_ROOT_POLICIES = {
    "retained_byte_identity_gated_until_separate_approved_breaking_cleanup",
    "canonical_src_only_after_next03_retirement",
}
_REQUIRED = {
    "id",
    "paths",
    "state",
    "deletion_approved",
    "a5_review_required",
    "approval_scope",
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


def _removed_path_still_contains_source(path: Path, *, root_mirror: bool) -> bool:
    """Ignore ignored cache directories left after root-mirror ``git rm``.

    Other removed candidates retain strict path absence. Only the retired root
    Python mirror may leave an empty/``__pycache__`` directory in a live local
    checkout without recreating an importable production namespace.
    """

    if not path.exists() and not path.is_symlink():
        return False
    if not root_mirror or path.is_symlink() or path.is_file():
        return True
    return any(candidate.is_file() for candidate in path.rglob("*.py"))


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
    if payload.get("schema") not in {
        "quantbt-native-deletion-manifest-v1",
        "quantbt-native-deletion-manifest-v2",
    }:
        violations.append("unsupported native deletion manifest schema")
    if str(payload.get("phase", "")) != "54B.4":
        violations.append("native deletion manifest must be owned by Phase 54B.4")
    root_source_policy = str(payload.get("root_source_policy", ""))
    if root_source_policy not in _ROOT_POLICIES:
        violations.append("root source policy is not recognized")

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
        if not isinstance(item["a5_review_required"], bool):
            violations.append(f"{identifier}: a5_review_required must be boolean")
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
            if state == "removed" and _removed_path_still_contains_source(
                path,
                root_mirror=identifier == "root_python_mirror",
            ):
                violations.append(f"{identifier}: removed path still exists: {value}")
            if state != "removed" and not path.exists():
                violations.append(f"{identifier}: retained/deferred path is missing: {value}")
        for value in replacements + docs + tests:
            path = _relative_path(root, value, label=f"{identifier}.references")
            if not path.exists():
                violations.append(f"{identifier}: referenced replacement/doc/test is missing: {value}")
        for key in (
            "approval_scope",
            "replacement",
            "compatibility_window",
            "rollback",
            "owner",
        ):
            if not str(item[key]).strip():
                violations.append(f"{identifier}: {key} must be non-empty")
        if identifier == "root_python_mirror":
            root_candidate = item

    if root_candidate is None:
        violations.append("root_python_mirror candidate is required")
    else:
        root_paths = {str(item) for item in root_candidate.get("paths", ())}
        required_markers = {"__init__.py", "endpoint.py", "walkforward.py", "backends", "core"}
        if not required_markers.issubset(root_paths):
            violations.append("root_python_mirror must list the reviewed root module/package markers")
        if root_source_policy == "retained_byte_identity_gated_until_separate_approved_breaking_cleanup":
            if str(root_candidate.get("state")) != "retained" or bool(root_candidate.get("deletion_approved")):
                violations.append("retained root source policy requires a non-approved retained mirror")
        else:
            if str(root_candidate.get("state")) != "removed" or not bool(root_candidate.get("deletion_approved")):
                violations.append("canonical source policy requires the reviewed root mirror to be removed")
            if bool(root_candidate.get("a5_review_required", True)):
                violations.append("canonical source policy must keep root-mirror retirement outside runtime A5")
            baseline = root / "contracts" / "next03_root_mirror_retirement_baseline.json"
            if not baseline.is_file():
                violations.append("canonical source policy requires the NEXT-03 retirement baseline")
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
