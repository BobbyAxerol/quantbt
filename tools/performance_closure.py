#!/usr/bin/env python3
"""Versioned validation for the PERF-07 performance-closure handoff.

The closure is intentionally evidence-oriented.  It does not decide that a
route should be promoted and it never executes a backtest.  Instead it binds a
known candidate source tree to immutable benchmark, regression, wheel, and
build-decision artifacts so Phase 78 cannot accidentally promote a stale or
partially-qualified result.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.measurement_contract import (  # noqa: E402
    IDENTITY_REQUIRED_FIELDS,
    capture_measurement_identity,
    file_sha256,
)


SCHEMA = "quantbt.performance_closure.v1"
READY = "READY_FOR_PHASE78"
BLOCKED = "BLOCKED"
PHASE_IDS = tuple(f"PERF-{ordinal:02d}" for ordinal in range(1, 8))
AP_IDS = tuple(f"AP-{ordinal:02d}" for ordinal in range(1, 13))
AC_IDS = tuple(f"AC-{ordinal:02d}" for ordinal in range(1, 45))
ALLOWED_DISPOSITIONS = frozenset(
    {"IMPLEMENTED_VERIFIED", "VERIFIED_EXISTING", "NOT_BENEFICIAL"}
)
ALLOWED_ROUTE_STATES = frozenset(
    {"explicit_support", "auto_eligible", "safe_baseline", "rejected"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PLACEHOLDERS = frozenset(
    {
        "resolved_by_ci",
        "evidence_reference",
        "candidate_bound_artifact_store",
        "todo",
        "tbd",
        "not_yet_measured",
    }
)


class PerformanceClosureError(ValueError):
    """Raised when a closure manifest cannot support its declared status."""


def canonical_json_sha256(payload: Any) -> str:
    """Return a presentation-independent digest for a JSON-compatible value."""

    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _relative_path(root: Path, value: object, *, label: str) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise PerformanceClosureError(f"{label} must be a repository-relative path")
    return root / path


def evidence_reference(root: Path, path: Path, *, pointer: str | None = None) -> dict[str, str]:
    """Build an immutable reference to a committed repository artifact."""

    root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise PerformanceClosureError("evidence artifact must live below the repository root") from exc
    if not resolved.is_file():
        raise PerformanceClosureError(f"evidence artifact does not exist: {relative}")
    reference = {"path": relative.as_posix(), "sha256": file_sha256(resolved)}
    if pointer is not None:
        if not pointer.startswith("#/"):
            raise PerformanceClosureError("evidence pointer must be a JSON pointer beginning '#/'")
        reference["pointer"] = pointer
    return reference


def capture_closure_identity(root: Path) -> dict[str, Any]:
    """Capture source identity for a clean closure candidate without market data."""

    return capture_measurement_identity(
        root=root,
        warmup_procedure="PERF-07 closure provenance only; workload identities live in referenced evidence",
        data_sha256=sha256(b"PERF-07 closure has no synthetic market tape").hexdigest(),
        intent_sha256=sha256(b"PERF-07 closure has no synthetic execution intent").hexdigest(),
    )


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _is_ancestor(root: Path, ancestor: str) -> bool:
    if not _GIT_SHA.fullmatch(ancestor):
        return False
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, "HEAD"],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    return completed.returncode == 0


def _has_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _PLACEHOLDERS
    if isinstance(value, Mapping):
        return any(_has_placeholder(key) or _has_placeholder(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return any(_has_placeholder(item) for item in value)
    return False


def _validate_reference(root: Path, reference: object, *, label: str) -> list[str]:
    if not isinstance(reference, Mapping):
        return [f"{label} must be an evidence reference object"]
    path_value = reference.get("path")
    digest = reference.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        return [f"{label} is missing path"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        return [f"{label} is missing a valid sha256"]
    try:
        path = _relative_path(root, path_value, label=label)
    except PerformanceClosureError as exc:
        return [str(exc)]
    if not path.is_file():
        return [f"{label} does not exist: {path_value}"]
    if file_sha256(path) != digest:
        return [f"{label} checksum changed: {path_value}"]
    pointer = reference.get("pointer")
    if pointer is not None and (not isinstance(pointer, str) or not pointer.startswith("#/")):
        return [f"{label} has an invalid JSON pointer"]
    return []


def _referenced_json(root: Path, reference: object, *, label: str) -> tuple[Mapping[str, Any] | None, list[str]]:
    """Load a checked JSON evidence object without trusting its filename alone."""

    violations = _validate_reference(root, reference, label=label)
    if violations or not isinstance(reference, Mapping):
        return None, violations
    try:
        path = _relative_path(root, reference["path"], label=label)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, [f"{label} is not a readable JSON evidence object: {exc}"]
    if not isinstance(payload, Mapping):
        return None, [f"{label} JSON evidence must be an object"]
    return payload, []


def _validate_identity(root: Path, identity: object) -> list[str]:
    if not isinstance(identity, Mapping):
        return ["source_identity must be an object"]
    missing = sorted(IDENTITY_REQUIRED_FIELDS - set(identity))
    if missing:
        return ["source_identity missing " + ", ".join(missing)]
    violations: list[str] = []
    if identity.get("git_dirty") is not False:
        violations.append("source_identity must be captured from a clean tree")
    source_hash = identity.get("canonical_source_sha256")
    if not isinstance(source_hash, str) or not _SHA256.fullmatch(source_hash):
        violations.append("source_identity has invalid canonical_source_sha256")
    else:
        current = capture_closure_identity(root).get("canonical_source_sha256")
        if current != source_hash:
            violations.append("source_identity no longer matches the current source tree")
    commit = identity.get("git_commit")
    if not isinstance(commit, str) or not _is_ancestor(root, commit):
        violations.append("source_identity git_commit is not an ancestor of the checked candidate")
    native = identity.get("native_extension")
    if not isinstance(native, Mapping) or native.get("available") is not True:
        violations.append("source_identity must record an available native extension")
    return violations


def _required_rows(
    value: object,
    *,
    expected_ids: tuple[str, ...],
    label: str,
    require_disposition: bool,
) -> list[str]:
    if not isinstance(value, list):
        return [f"{label} must be a list"]
    by_id = {str(item.get("id")): item for item in value if isinstance(item, Mapping)}
    violations: list[str] = []
    if set(by_id) != set(expected_ids):
        violations.append(f"{label} must contain exactly {expected_ids[0]} through {expected_ids[-1]}")
        return violations
    for identifier in expected_ids:
        row = by_id[identifier]
        disposition = row.get("disposition")
        if require_disposition and disposition not in ALLOWED_DISPOSITIONS:
            violations.append(f"{label} {identifier} has unresolved disposition {disposition!r}")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
            violations.append(f"{label} {identifier} requires concrete evidence labels")
    return violations


def _validate_routes(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        return ["route_matrix must be a non-empty list"]
    seen: set[str] = set()
    violations: list[str] = []
    for row in value:
        if not isinstance(row, Mapping):
            violations.append("route_matrix contains a non-object row")
            continue
        identifier = str(row.get("id", ""))
        if not identifier or identifier in seen:
            violations.append(f"route_matrix has duplicate/empty id {identifier!r}")
        seen.add(identifier)
        if identifier.lower() in {"all", "generic", "everything"}:
            violations.append("route_matrix cannot use a blanket route id")
        if row.get("state") not in ALLOWED_ROUTE_STATES:
            violations.append(f"route {identifier} has invalid state {row.get('state')!r}")
        for field in ("surface", "execution_contract", "retention", "worker_scope", "reason"):
            if not isinstance(row.get(field), str) or not str(row[field]).strip():
                violations.append(f"route {identifier} lacks {field}")
    return violations


def validate_manifest(payload: Mapping[str, Any], *, root: Path) -> list[str]:
    """Return all deterministic closure violations without executing workloads."""

    root = root.resolve()
    violations: list[str] = []
    if payload.get("schema") != SCHEMA:
        violations.append("unsupported performance closure schema")
    if payload.get("status") not in {READY, BLOCKED}:
        violations.append("closure status must be READY_FOR_PHASE78 or BLOCKED")
    if _has_placeholder(payload):
        violations.append("closure contains a forbidden placeholder value")
    violations.extend(_validate_identity(root, payload.get("source_identity")))

    phase_results = payload.get("phase_results")
    if not isinstance(phase_results, list):
        violations.append("phase_results must be a list")
    else:
        phases = {str(row.get("phase")): row for row in phase_results if isinstance(row, Mapping)}
        if set(phases) != set(PHASE_IDS):
            violations.append("phase_results must contain PERF-01 through PERF-07")
        for phase in PHASE_IDS:
            row = phases.get(phase)
            if row is None:
                continue
            references = row.get("evidence")
            if not isinstance(references, list) or not references:
                violations.append(f"{phase} requires at least one immutable evidence reference")
                continue
            for ordinal, reference in enumerate(references):
                violations.extend(_validate_reference(root, reference, label=f"{phase}.evidence[{ordinal}]"))

    violations.extend(_required_rows(payload.get("ap_dispositions"), expected_ids=AP_IDS, label="ap_dispositions", require_disposition=True))
    violations.extend(_required_rows(payload.get("ac_coverage"), expected_ids=AC_IDS, label="ac_coverage", require_disposition=True))
    violations.extend(_validate_routes(payload.get("route_matrix")))

    combined, issues = _referenced_json(root, payload.get("combined_qualification"), label="combined_qualification")
    violations.extend(issues)
    if combined is not None and combined.get("evidence", {}).get("all_current_qualification_gates") is not True:
        violations.append("combined_qualification did not pass all current gates")

    regression, issues = _referenced_json(root, payload.get("cross_domain_regression"), label="cross_domain_regression")
    violations.extend(issues)
    if regression is not None and (
        regression.get("status") != "passed" or not all(dict(regression.get("evidence", {})).values())
    ):
        violations.append("cross_domain_regression did not pass")

    pgo, issues = _referenced_json(root, payload.get("pgo_decision"), label="pgo_decision")
    violations.extend(issues)
    if pgo is not None:
        if pgo.get("decision") not in {"IMPLEMENTED_VERIFIED", "NOT_BENEFICIAL"}:
            violations.append("pgo_decision has no allowed disposition")
        guards = pgo.get("guards")
        if not isinstance(guards, Mapping) or not all(
            guards.get(field) is expected
            for field, expected in (
                ("no_target_cpu_native", True),
                ("no_fast_math_or_panic_or_unsafe_override", True),
                ("financial_capability_changed", False),
                ("enabled_routes_changed", False),
                ("held_out_parity", True),
            )
        ):
            violations.append("pgo_decision does not preserve the portable safety/capability guard")

    wheel, issues = _referenced_json(root, payload.get("candidate_wheel"), label="candidate_wheel")
    violations.extend(issues)
    if wheel is not None:
        checks = wheel.get("evidence")
        required_wheel_checks = {
            "source_hash_parity": True,
            "clean_install": True,
            "direct_target_smoke": True,
            "exact_native_pair": True,
            "source_tree_import_blocked": True,
        }
        if not isinstance(checks, Mapping) or any(checks.get(name) is not expected for name, expected in required_wheel_checks.items()):
            violations.append("candidate_wheel lacks the required clean exact-pair proof")

    if payload.get("open_correctness_blockers") != []:
        violations.append("READY closure requires an empty open_correctness_blockers list")
    audit = payload.get("audit_compatibility")
    if not isinstance(audit, Mapping) or audit.get("roundtrip_passed") is not True:
        violations.append("audit_compatibility must record a passing round-trip")
    rollback = payload.get("rollback")
    if not isinstance(rollback, Mapping):
        violations.append("rollback must be an object")
    else:
        for field in ("baseline_contract", "candidate_scope", "action"):
            if not isinstance(rollback.get(field), str) or not rollback[field].strip():
                violations.append(f"rollback lacks {field}")
    if payload.get("status") == READY and violations:
        # The status itself is invalid when any mandatory proof is absent.  Keep
        # all violations for callers instead of hiding the first failure.
        pass
    return sorted(set(violations))


def require_valid_manifest(payload: Mapping[str, Any], *, root: Path) -> None:
    """Raise a compact error suitable for a CI/release gate."""

    violations = validate_manifest(payload, root=root)
    if violations:
        raise PerformanceClosureError("; ".join(violations))
