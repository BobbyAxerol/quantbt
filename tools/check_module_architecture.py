#!/usr/bin/env python3
"""Enforce explicit QuantBT module ownership, boundaries, and review triggers."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts" / "module_ownership.json"
SOURCE = ROOT / "src" / "quantbt"


def _load_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", -1)) != 1:
        raise ValueError("unsupported module ownership schema")
    for key in ("reviewers", "subsystems", "import_rules", "size_guideline", "module_exceptions"):
        if key not in payload:
            raise ValueError(f"module ownership registry missing {key}")
    return payload


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            values.append("." * node.level + (node.module or ""))
    return tuple(values)


def _python_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def validate_architecture(root: Path = ROOT) -> list[str]:
    """Return deterministic architecture violations without mutating the tree."""

    registry = _load_registry()
    source = root / "src" / "quantbt"
    exceptions = {item["path"]: item for item in registry["module_exceptions"]}
    threshold = int(registry["size_guideline"]["python_module_lines"])
    violations: list[str] = []
    paths = tuple(sorted(source.rglob("*.py")))
    for path in paths:
        relative = str(path.relative_to(root))
        matching_subsystems = [
            item for item in registry["subsystems"]
            if relative.startswith(str(item["path_prefix"]))
        ]
        if not matching_subsystems:
            violations.append(f"unowned module: {relative}")
        if _python_lines(path) > threshold and relative not in exceptions:
            violations.append(f"oversized module without review exception: {relative}")
    for relative, item in exceptions.items():
        if not (root / relative).is_file():
            violations.append(f"stale module exception: {relative}")
        if not str(item.get("owner", "")).strip() or not str(item.get("review_target", "")).strip():
            violations.append(f"incomplete module exception: {relative}")
    for rule in registry["import_rules"]:
        prefix = str(rule["path_prefix"])
        forbidden = tuple(str(item) for item in rule["forbidden_substrings"])
        for path in paths:
            relative = str(path.relative_to(root))
            if not relative.startswith(prefix):
                continue
            for imported in _imports(path):
                if any(item in imported for item in forbidden):
                    violations.append(f"forbidden import {imported!r} in {relative}")
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        violations = validate_architecture(args.root.resolve())
    except (OSError, ValueError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"module architecture check failed: {exc}", file=sys.stderr)
        return 1
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("module ownership/import-boundary gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
