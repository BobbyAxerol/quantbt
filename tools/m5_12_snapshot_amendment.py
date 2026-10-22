"""Exact continuous snapshot seal amendment, not an artifact certificate."""

import ast
from hashlib import sha256
import json


MANIFEST_NAME = "docs/maintenance/evidence/m5-12-snapshot-source-amendment.json"
MANIFEST_SHA256 = "0efc267ed8f2f000669916badc99b365b10d2eb8a03ce4acc96256c1a92fe8ab"
BASELINE_COMMIT = "45fd6ec5bc0f2556ff024ffd1314469e06c0b07a"
SOURCE_COMMIT = "bf3f919550a82ac97d6c4c81073a52880d5e3331"
SOURCE_COUNT = 466
CONSTRUCTORS = {
    "src/quantbt/mode5/continuous.py": (
        "ContinuousStream", "ContinuousAccountEvaluation",
    ),
    "src/quantbt/mode5/continuous_retention.py": ("ContinuousAccountRetention",),
}
SOURCE_PATHS = frozenset(CONSTRUCTORS)


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def manifest(guard):
    assert _hex(MANIFEST_SHA256, 64), "M5-12 snapshot manifest is not sealed"
    assert _hex(SOURCE_COMMIT, 40), "M5-12 snapshot source commit is not sealed"
    path = guard.ROOT / MANIFEST_NAME
    assert path.is_file() and not path.is_symlink(), "M5-12 snapshot manifest must be a regular file"
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "M5-12 snapshot manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.m5_12.snapshot_source.v1", "snapshot amendment schema"
    assert value["baseline_commit"] == BASELINE_COMMIT, "snapshot baseline differs"
    assert value["source_commit"] == SOURCE_COMMIT != BASELINE_COMMIT, "snapshot source commit"
    assert value["source_only"] is True, "snapshot amendment is source-only"
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued"):
        assert value[key] is False, "snapshot amendment cannot reissue claims: " + key
    for key in ("financial_numeric_source_unchanged", "financial_rust_unchanged"):
        assert value.get(key, False) is False, "snapshot amendment cannot claim source invariance: " + key
    for key in ("financial_rust_changed", "native_rebuild_required", "version_bump"):
        assert value.get(key, False) is False, "snapshot cannot admit native/version changes: " + key
    assert value.get("native_source_unchanged_relative_to", BASELINE_COMMIT) == BASELINE_COMMIT, "snapshot native baseline differs"
    assert set(value["sources"]) == SOURCE_PATHS, "snapshot requires exactly two reviewed runtime paths"
    for name, entry in value["sources"].items():
        assert entry["before_commit"] == BASELINE_COMMIT, "snapshot entry baseline differs: " + name
        assert entry["after_commit"] == SOURCE_COMMIT, "snapshot entry source commit differs: " + name
        assert _hex(entry["before_sha256"], 64) and _hex(entry["after_sha256"], 64), "snapshot source digests: " + name
        assert entry["before_sha256"] != entry["after_sha256"], "snapshot entry must change: " + name
    from tools.m5_12_pct_alias_amendment import manifest as alias_manifest
    previous = alias_manifest(guard)
    assert previous["source_commit"] == BASELINE_COMMIT, "snapshot must follow the sealed alias repair"
    assert value["scopes"] == previous["scopes"], "snapshot source scopes differ"
    return value


def _seal_statement(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "self"
            and node.value.func.attr == "_seal_arrays"
            and not node.value.args and not node.value.keywords)


def verify_snapshot_delta(before, after, name):
    """Only three specified trailing seal calls may differ from the pinned AST."""
    assert name in CONSTRUCTORS, "snapshot AST path is not reviewed"
    old = ast.parse(before, filename=name, type_comments=True)
    new = ast.parse(after, filename=name, type_comments=True)
    attributes = lambda tree: [node for node in ast.walk(tree)
                               if isinstance(node, ast.Attribute) and node.attr == "_seal_arrays"]
    assert not attributes(old), "snapshot baseline unexpectedly contains seal references"
    assert len(attributes(new)) == len(CONSTRUCTORS[name]), "snapshot requires exactly one seal per approved constructor"
    for class_name in CONSTRUCTORS[name]:
        classes = [node for node in new.body if isinstance(node, ast.ClassDef) and node.name == class_name]
        assert len(classes) == 1, "snapshot approved class missing or duplicated: " + class_name
        methods = [node for node in classes[0].body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__post_init__"]
        assert len(methods) == 1 and isinstance(methods[0], ast.FunctionDef), "snapshot constructor differs: " + class_name
        method = methods[0]
        assert method.body and _seal_statement(method.body[-1]), "snapshot seal must be the final constructor statement: " + class_name
        assert len(attributes(method)) == 1, "snapshot constructor must contain exactly one seal: " + class_name
        method.body.pop()
    assert ast.dump(new, include_attributes=False) == ast.dump(old, include_attributes=False), "snapshot AST differs beyond the three approved trailing seals"


def without_snapshot(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(entry["after_commit"], name, entry["after_sha256"])
    before = guard._blob(entry["before_commit"], name, entry["before_sha256"])
    verify_snapshot_delta(before, source, name)
    return before


def apply_snapshot(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"], "snapshot source scopes differ"
    before = guard._committed_source_hashes(BASELINE_COMMIT, scopes)
    assert len(before) == SOURCE_COUNT, "snapshot baseline inventory must contain 466 paths"
    assert before == expected, "snapshot does not follow exact approved current baseline"
    after = guard._committed_source_hashes(SOURCE_COMMIT, scopes)
    assert len(after) == SOURCE_COUNT and set(after) == set(before), "snapshot source inventory changed"
    assert ({n: v for n, v in before.items() if n.startswith("rust/")}
            == {n: v for n, v in after.items() if n.startswith("rust/")}), "snapshot cannot admit native changes"
    changed = guard._verify_repair_delta(value, before, after, value)
    assert set(changed) == SOURCE_PATHS, "snapshot committed delta exceeds the two reviewed paths"
    for name, entry in value["sources"].items():
        old = guard._blob(entry["before_commit"], name, entry["before_sha256"])
        new = guard._blob(entry["after_commit"], name, entry["after_sha256"])
        verify_snapshot_delta(old, new, name)
    return value, after, changed
