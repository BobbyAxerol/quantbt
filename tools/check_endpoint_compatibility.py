#!/usr/bin/env python3
"""Audit endpoint signatures against committed baselines without importing QuantBT."""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "src/quantbt/endpoint.py"
INIT = "src/quantbt/__init__.py"


def methods(source):
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QuantBTEndpoint")
    return {node.name: node.args for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")}


def exports(source):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise ValueError("literal __all__ not found")


def parameters(args):
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
    rows = [(arg.arg, "positional_only" if i < len(args.posonlyargs) else "positional_or_keyword", default)
            for i, (arg, default) in enumerate(zip(positional, defaults))]
    rows += [(arg.arg, "keyword_only", default) for arg, default in zip(args.kwonlyargs, args.kw_defaults)]
    return {name: (kind, None if default is None else ast.dump(default)) for name, kind, default in rows}


def breaking_changes(old, new):
    before, after = parameters(old), parameters(new)
    findings = [f"removed or changed parameter: {name}" for name, value in before.items() if after.get(name) != value]
    findings += [f"new required parameter: {name}" for name, value in after.items()
                 if name not in before and value[1] is None]
    for kind in ("vararg", "kwarg"):
        previous, current = getattr(old, kind), getattr(new, kind)
        if previous is not None and (current is None or previous.arg != current.arg):
            findings.append(f"changed {kind}")
    before_pos = [name for name, (kind, _) in before.items() if kind != "keyword_only"]
    after_pos = [name for name, (kind, _) in after.items() if kind != "keyword_only"]
    if after_pos[:len(before_pos)] != before_pos:
        findings.append("positional parameter order changed")
    return findings


def audit(baseline, root=ROOT):
    commit = subprocess.check_output(["git", "rev-parse", "--verify", baseline + "^{commit}"], cwd=root, text=True).strip()
    blob = lambda name: subprocess.check_output(["git", "show", commit + ":" + name], cwd=root)
    old_source, source = blob(ENDPOINT), (root / ENDPOINT).read_bytes()
    old, new = methods(old_source), methods(source)
    changes = {name: dict(before=ast.unparse(old[name]), after=ast.unparse(new[name]),
                         breaking=breaking_changes(old[name], new[name]))
               for name in sorted(old.keys() & new.keys()) if ast.dump(old[name]) != ast.dump(new[name])}
    old_exports, new_exports = exports(blob(INIT)), exports((root / INIT).read_bytes())
    return dict(baseline=baseline, baseline_commit=commit, endpoint_sha256=sha256(source).hexdigest(),
                public_method_count=len(new), added_methods=sorted(new.keys()-old.keys()),
                removed_methods=sorted(old.keys()-new.keys()), changed_signatures=changes,
                added_exports=sorted(new_exports-old_exports), removed_exports=sorted(old_exports-new_exports),
                breaking_signature_change=bool(old.keys()-new.keys()) or any(item["breaking"] for item in changes.values()),
                scope="static signatures/exports only; not behavioral, installed or platform qualification")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="append", required=True)
    args = parser.parse_args()
    results = [audit(baseline) for baseline in args.baseline]
    print(json.dumps(dict(schema="quantbt.endpoint_compatibility.v1", baselines=results), indent=2, sort_keys=True))
    return int(any(item["breaking_signature_change"] or item["removed_exports"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
