#!/usr/bin/env python3
"""Validate route-level A5 review and deletion decisions without deleting code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW = ROOT / "contracts/native_event_a5_review.json"
DEFAULT_DELETION = ROOT / "contracts/native_event_deletion_manifest.json"
_REQUIRED_ROUTE_FIELDS = {
    "route_id",
    "current_stage",
    "a5_eligible",
    "stable_release_cycles",
    "unexplained_shadow_mismatches",
    "fallback_rate_measured",
    "deletion_approved",
    "blocking_reasons",
    "rollback",
}


def validate_a5_review(
    review_path: Path = DEFAULT_REVIEW,
    deletion_path: Path = DEFAULT_DELETION,
) -> list[str]:
    review: Mapping[str, Any] = json.loads(review_path.read_text(encoding="utf-8"))
    deletion: Mapping[str, Any] = json.loads(deletion_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    if review.get("schema") != "quantbt-native-a5-review-v1":
        violations.append("unsupported A5 review schema")
    if review.get("policy") != "route_by_route_no_blanket_deletion":
        violations.append("A5 review must use route-by-route deletion policy")
    routes = review.get("routes")
    if not isinstance(routes, list) or not routes:
        return violations + ["A5 review requires non-empty routes"]

    route_ids: set[str] = set()
    for route in routes:
        if not isinstance(route, Mapping):
            violations.append("A5 route must be an object")
            continue
        route_id = str(route.get("route_id", ""))
        missing = sorted(_REQUIRED_ROUTE_FIELDS - set(route))
        if not route_id or route_id in route_ids:
            violations.append(f"duplicate or empty A5 route id: {route_id!r}")
        route_ids.add(route_id)
        if missing:
            violations.append(f"{route_id or '<missing>'}: missing fields: {', '.join(missing)}")
            continue
        eligible = bool(route["a5_eligible"])
        measured_fallback = route["fallback_rate_measured"]
        blocking = route["blocking_reasons"]
        if not isinstance(blocking, list):
            violations.append(f"{route_id}: blocking_reasons must be a list")
            continue
        objective_ready = (
            int(route["stable_release_cycles"]) >= int(review.get("stable_release_cycles_required", 1))
            and int(route["unexplained_shadow_mismatches"]) == 0
            and measured_fallback is not None
            and float(measured_fallback) == 0.0
            and bool(route["deletion_approved"])
            and not blocking
        )
        if eligible != objective_ready:
            violations.append(f"{route_id}: a5_eligible disagrees with measured A5 gates")
        if eligible and str(route.get("current_stage")) != "A5":
            violations.append(f"{route_id}: eligible route must declare current_stage=A5")
        if not str(route["rollback"]).strip():
            violations.append(f"{route_id}: rollback must be non-empty")

    performed = review.get("deletions_performed")
    if not isinstance(performed, list):
        violations.append("deletions_performed must be a list")
        performed = []
    candidates = deletion.get("candidates", [])
    removed = {
        str(candidate.get("id"))
        for candidate in candidates
        if isinstance(candidate, Mapping) and candidate.get("state") == "removed"
    }
    if set(map(str, performed)) != removed:
        violations.append("A5 review deletions_performed disagrees with deletion manifest")
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--deletion", type=Path, default=DEFAULT_DELETION)
    args = parser.parse_args(argv)
    try:
        violations = validate_a5_review(args.review.resolve(), args.deletion.resolve())
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"native A5 review failed: {exc}", file=sys.stderr)
        return 1
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("native A5 route review: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
