"""MET-03 narrowly admits cold reporting only; archived baselines stay immutable."""

import ast
import hashlib
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PARENT = "864b38a"
ADMITTED = {"src/quantbt/__init__.py", "src/quantbt/endpoint.py",
            "src/quantbt/core/types.py", "src/quantbt/core/results.py"}
EXPORTS = {"ReportingRequest", "ReportingContractV1", "ReportingCoverageV1", "ReportingCache"}


def normalized(text, path, *, changed):
    tree = ast.parse(text)
    if path.endswith("__init__.py"):
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                node.value.elts = [v for v in node.value.elts if not isinstance(v, ast.Constant) or v.value not in EXPORTS]
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_LAZY_EXPORTS" for t in node.targets):
                pairs = [(k, v) for k, v in zip(node.value.keys, node.value.values)
                         if not isinstance(k, ast.Constant) or k.value not in EXPORTS]
                node.value.keys, node.value.values = map(list, zip(*pairs))
    else:
        allowed = {"full_report", "show_metrics", "quick_plot"}
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for node in cls.body:
                if not isinstance(node, ast.FunctionDef) or node.name not in allowed:
                    continue
                if changed:
                    assert node.args.kwonlyargs[-1].arg == "reporting"
                    assert isinstance(node.args.kw_defaults[-1], ast.Constant) and node.args.kw_defaults[-1].value is None
                    node.args.kwonlyargs.pop()
                    node.args.kw_defaults.pop()
                    # Only the opt-in branch is new; the legacy body must remain exact.
                    branches = [n for n in node.body if isinstance(n, ast.If) and
                                ast.dump(n.test) == ast.dump(ast.parse("reporting is not None", mode="eval").body)]
                    assert len(branches) == 1
                    assert not branches[0].orelse
                    assert all(not isinstance(n, ast.ImportFrom) or n.module.endswith("metrics.reporting.public")
                               for n in ast.walk(branches[0]))
                    node.body.remove(branches[0])
    return ast.dump(tree, include_attributes=False)


def assert_protected(path, expected_hash):
    current = (ROOT / path).read_bytes()
    from tools.mode5_public_source_guard import without_mode5_public
    current = without_mode5_public(current, path)
    if path not in ADMITTED:
        assert hashlib.sha256(current).hexdigest() == expected_hash, path
        return
    parent = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], cwd=ROOT)
    assert hashlib.sha256(parent).hexdigest() == expected_hash, path
    assert normalized(current.decode(), path, changed=True) == normalized(parent.decode(), path, changed=False), path
