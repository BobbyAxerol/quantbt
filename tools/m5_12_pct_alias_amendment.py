"""Exact pct-equity alias identity amendment, not an artifact certificate."""

from hashlib import sha256
import json


MANIFEST_NAME = "docs/maintenance/evidence/m5-12-pct-activity-alias-amendment.json"
MANIFEST_SHA256 = "98cb60821074a8d3e4f320c0235c23f9bf5e0fa8c9ba0fef8d2bee878a023e36"
BASELINE_COMMIT = "b4c4f934a33465b379657bbe1b73745280db84fe"
SOURCE_COUNT = 466
SOURCE_PATHS = frozenset({
    "src/quantbt/endpoint.py",
    "src/quantbt/backends/native_wfo_public.py",
})


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def manifest(guard):
    assert _hex(MANIFEST_SHA256, 64), "M5-12 pct alias manifest is not sealed"
    path = guard.ROOT / MANIFEST_NAME
    assert path.is_file() and not path.is_symlink(), "M5-12 pct alias manifest must be a regular file"
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "M5-12 pct alias manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.m5_12.pct_activity_alias.v1", "pct alias amendment schema"
    assert value["baseline_commit"] == BASELINE_COMMIT, "pct alias baseline differs"
    assert _hex(value["source_commit"], 40) and value["source_commit"] != BASELINE_COMMIT, "pct alias source commit"
    assert value["source_only"] is True, "pct alias amendment is source-only"
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued"):
        assert value[key] is False, "pct alias amendment cannot reissue claims: " + key
    for key in ("financial_numeric_source_unchanged", "financial_rust_unchanged"):
        assert value.get(key, False) is False, "pct alias amendment cannot claim source invariance: " + key
    assert value.get("financial_rust_changed", False) is False, "pct alias cannot admit native changes"
    assert set(value["sources"]) == SOURCE_PATHS, "pct alias requires exactly two reviewed runtime paths"
    for name, entry in value["sources"].items():
        assert entry["before_commit"] == BASELINE_COMMIT, "pct alias entry baseline differs: " + name
        assert entry["after_commit"] == value["source_commit"], "pct alias entry source commit differs: " + name
        assert _hex(entry["before_sha256"], 64) and _hex(entry["after_sha256"], 64), "pct alias source digests: " + name
        assert entry["before_sha256"] != entry["after_sha256"], "pct alias entry must change: " + name
    from tools.m5_12_pct_source_amendment import manifest as activity_manifest
    previous = activity_manifest(guard)
    assert previous["source_commit"] == BASELINE_COMMIT, "pct alias must follow the sealed activity repair"
    assert value["scopes"] == previous["scopes"], "pct alias source scopes differ"
    return value


def without_pct_alias(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(entry["after_commit"], name, entry["after_sha256"])
    return guard._blob(entry["before_commit"], name, entry["before_sha256"])


def apply_pct_alias(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"], "pct alias source scopes differ"
    before = guard._committed_source_hashes(value["baseline_commit"], scopes)
    assert len(before) == SOURCE_COUNT, "pct alias baseline inventory must contain 466 paths"
    assert before == expected, "pct alias does not follow exact approved current baseline"
    after = guard._committed_source_hashes(value["source_commit"], scopes)
    assert len(after) == SOURCE_COUNT and set(after) == set(before), "pct alias source inventory changed"
    assert ({n: v for n, v in before.items() if n.startswith("rust/")}
            == {n: v for n, v in after.items() if n.startswith("rust/")}), "pct alias cannot admit native changes"
    changed = guard._verify_repair_delta(value, before, after, value)
    assert set(changed) == SOURCE_PATHS, "pct alias committed delta exceeds the two reviewed paths"
    assert not any(name.startswith("rust/") for name in changed), "pct alias cannot admit native changes"
    return value, after, changed
