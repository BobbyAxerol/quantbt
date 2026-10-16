"""Verify this source promotion kept mathematical bodies and execution owners."""

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def body(source):
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))
                 and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                          and isinstance(node.value.value, str))]
    return ast.dump(tree, include_attributes=False)


def qualify(baseline):
    paths = [(f"tools/mode5_geometry/{name}.py", f"src/quantbt/diagnostics/geometry/{name}.py")
        for name in ("design", "neighborhoods", "estimators", "sensitivity", "structured",
                     "finite_panel", "basins")]
    paths += [(f"tools/mode5_diagnostics/{name}.py", f"src/quantbt/diagnostics/{name}.py")
              for name in ("evidence", "reuse")]
    rows = []
    for old, new in paths:
        original = subprocess.check_output(["git", "show", f"{baseline}:{old}"], cwd=ROOT, text=True)
        current = (ROOT / new).read_text()
        if body(original) != body(current):
            raise ValueError("changed mathematical body: " + new)
        rows.append(dict(source=old, destination=new, body_equal=True,
                         current_sha256=sha256(current.encode()).hexdigest()))
    protected = ["src/quantbt/walkforward.py", "src/quantbt/endpoint.py",
        "src/quantbt/backends", "src/quantbt/optimization", "src/quantbt/metrics", "rust"]
    changed = subprocess.check_output(["git", "diff", "--name-only", baseline, "--", *protected],
                                      cwd=ROOT, text=True).splitlines()
    if changed:
        raise ValueError("protected execution/model changes: " + repr(changed))
    return dict(schema="quantbt.shared_diagnostics_source_promotion.v1", baseline=baseline,
        body_checks=rows, protected_changed=changed, status="PASS",
        limitation="Source/AST preservation, not installed-wheel or economic qualification.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="f57aef7")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(result["status"], len(result["body_checks"]), "unchanged owners")
