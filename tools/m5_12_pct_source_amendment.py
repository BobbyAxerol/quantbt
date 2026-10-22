"""Exact pct-equity position/activity amendment, not an artifact certificate."""

from hashlib import sha256
import json


MANIFEST_NAME = "docs/maintenance/evidence/m5-12-pct-activity-source-amendment.json"
MANIFEST_SHA256 = "cef8e2dfa6995197367ec896123a21747a6baf34dba48fcfa19de93c85d4d784"
BASELINE_COMMIT = "77af917f4184e4061a908c68557420223434e2db"
SOURCE_COUNT = 466
SOURCE_PATHS = frozenset({
    "src/quantbt/endpoint.py",
    "src/quantbt/optimization/meta_selection/observer.py",
    "src/quantbt/backends/native_prepared_evaluation.py",
    "src/quantbt/backends/native_wfo_public.py",
    "rust/crates/quantbt-execution/src/target.rs",
    "rust/native_event/src/lib.rs",
})


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def manifest(guard):
    assert _hex(MANIFEST_SHA256, 64), "M5-12 pct activity manifest is not sealed"
    path = guard.ROOT / MANIFEST_NAME
    assert path.is_file() and not path.is_symlink(), "M5-12 pct activity manifest must be a regular file"
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "M5-12 pct activity manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.m5_12.pct_activity_source.v1", "pct activity amendment schema"
    assert value["baseline_commit"] == BASELINE_COMMIT, "pct activity baseline differs"
    assert _hex(value["source_commit"], 40) and value["source_commit"] != BASELINE_COMMIT, "pct activity source commit"
    assert value["source_only"] is True, "pct activity amendment is source-only"
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued"):
        assert value[key] is False, "pct activity amendment cannot reissue claims: " + key
    for key in ("financial_numeric_source_unchanged", "financial_rust_unchanged"):
        assert value.get(key, False) is False, "pct activity amendment cannot claim source invariance: " + key
    assert set(value["sources"]) == SOURCE_PATHS, "pct activity requires exactly six reviewed runtime paths"
    for name, entry in value["sources"].items():
        assert entry["before_commit"] == BASELINE_COMMIT, "pct activity entry baseline differs: " + name
        assert entry["after_commit"] == value["source_commit"], "pct activity entry source commit differs: " + name
        assert _hex(entry["before_sha256"], 64) and _hex(entry["after_sha256"], 64), "pct activity source digests: " + name
        assert entry["before_sha256"] != entry["after_sha256"], "pct activity entry must change: " + name
    from tools.m5_12_source_guard import manifest as extraction_manifest
    previous = extraction_manifest(guard)
    assert previous["source_commit"] == BASELINE_COMMIT, "pct activity must follow the sealed extraction"
    assert value["scopes"] == previous["scopes"], "pct activity source scopes differ"
    return value


def without_pct_activity(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(entry["after_commit"], name, entry["after_sha256"])
    return guard._blob(entry["before_commit"], name, entry["before_sha256"])


def apply_pct_activity(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"], "pct activity source scopes differ"
    before = guard._committed_source_hashes(value["baseline_commit"], scopes)
    assert len(before) == SOURCE_COUNT, "pct activity baseline inventory must contain 466 paths"
    assert before == expected, "pct activity does not follow exact approved current baseline"
    after = guard._committed_source_hashes(value["source_commit"], scopes)
    assert len(after) == SOURCE_COUNT and set(after) == set(before), "pct activity source inventory changed"
    changed = guard._verify_repair_delta(value, before, after, value)
    assert set(changed) == SOURCE_PATHS, "pct activity committed delta exceeds the six reviewed paths"
    return value, after, changed
