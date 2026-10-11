"""Exact reviewed amendments; archived MET source baselines stay immutable."""

import ast
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PARENT = "864b38a"
ADMITTED = {"src/quantbt/__init__.py", "src/quantbt/endpoint.py",
            "src/quantbt/core/types.py", "src/quantbt/core/results.py"}
EXPORTS = {"ReportingRequest", "ReportingContractV1", "ReportingCoverageV1", "ReportingCache"}
AMENDMENT = ROOT / "docs/metrics/evidence/met-source-amendment-v1.json"
AMENDMENT_SHA256 = "a67d8573b89d7e1312230a657c51c1ea6e5868e11aae14e17192f2a5ed1a403f"
AMENDMENT_ID = "met-m5-11-clock-and-m5-11-1-native-output-v1"


def source_amendment():
    raw = AMENDMENT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == AMENDMENT_SHA256, "source amendment digest"
    manifest = json.loads(raw)
    assert manifest["schema"] == "met-reviewed-source-amendment-v1", "source amendment schema"
    assert manifest["identity"] == AMENDMENT_ID, "source amendment identity"
    return manifest


def committed_blob(commit, path, expected_hash):
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), path
    source = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
    assert hashlib.sha256(source).hexdigest() == expected_hash, f"amendment blob: {path}"
    return source


def without_reviewed_amendments(current, path, expected_hash):
    entry = source_amendment()["sources"].get(path)
    if entry is None:
        return current
    assert expected_hash == entry["baseline_sha256"], f"amendment baseline: {path}"
    baseline = committed_blob(entry["baseline_commit"], path, expected_hash)
    if current == baseline:
        return baseline
    previous_hash = expected_hash
    admitted = False
    # Every link must start at the archived bytes or the preceding reviewed blob.
    for change in entry["transitions"]:
        assert change["before_sha256"] == previous_hash, f"amendment chain: {path}"
        committed_blob(change["before_commit"], path, previous_hash)
        after = committed_blob(change["after_commit"], path, change["after_sha256"])
        admitted |= current == after
        previous_hash = change["after_sha256"]
    assert admitted, f"unreviewed source bytes: {path}"
    return baseline


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
    assert_protected_bytes(path, expected_hash, (ROOT / path).read_bytes())


def assert_protected_bytes(path, expected_hash, current):
    current = without_reviewed_amendments(current, path, expected_hash)
    from tools.mode5_public_source_guard import without_mode5_public
    current = without_mode5_public(current, path)
    if hashlib.sha256(current).hexdigest() == expected_hash:
        return
    if path not in ADMITTED:
        assert hashlib.sha256(current).hexdigest() == expected_hash, path
        return
    parent = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], cwd=ROOT)
    assert hashlib.sha256(parent).hexdigest() == expected_hash, path
    assert normalized(current.decode(), path, changed=True) == normalized(parent.decode(), path, changed=False), path
