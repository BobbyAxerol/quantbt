"""Exact compiler-compatibility repair, distinct from retained formatting proof."""

from hashlib import sha256
import json

MANIFEST_NAME = "docs/maintenance/evidence/m5-12-ci-rust-source-amendment.json"
MANIFEST_SHA256 = "c066ffa2dc596aeb410725191f539cae59f1ec35ba56fd0ad431681c2f0d43fe"
BASELINE_COMMIT = "4e02a6077b974e15e9be0a4a4e94c05716193818"
SOURCE_COMMIT = "33f22c6473971d45c09026b5f242a40bd7fa13aa"
SOURCE_PATHS = frozenset(("rust/crates/quantbt-batch/src/lib.rs", "rust/native_event/src/qms_numeric.rs"))


def manifest(guard):
    path = guard.ROOT / MANIFEST_NAME
    assert len(MANIFEST_SHA256) == 64 and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "CI Rust manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.m5_12.ci_rust_source.v1"
    assert (value["baseline_commit"], value["source_commit"]) == (BASELINE_COMMIT, SOURCE_COMMIT)
    assert set(value["sources"]) == SOURCE_PATHS
    assert value["source_only"] is True and value["fresh_native_artifacts_required"] is True
    for key in ("native_artifacts_qualified", "publication", "version_bump",
                "historical_financial_invariance_claim_reissued", "financial_numeric_source_unchanged"):
        assert value[key] is False, "CI Rust repair cannot expand claims"
    from tools.m5_12_ci_format_amendment import manifest as previous_manifest, MANIFEST_SHA256 as previous_digest
    previous = previous_manifest(guard)
    assert value["previous_amendment_sha256"] == previous_digest
    assert value["scopes"] == previous["scopes"] and previous["source_commit"] == BASELINE_COMMIT
    for entry in value["sources"].values():
        assert (entry["before_commit"], entry["after_commit"]) == (BASELINE_COMMIT, SOURCE_COMMIT)
        assert entry["before_sha256"] != entry["after_sha256"]
    return value


def without_ci_rust(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(SOURCE_COMMIT, name, entry["after_sha256"])
    return guard._blob(BASELINE_COMMIT, name, entry["before_sha256"])


def apply_ci_rust(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"], "CI Rust source scopes differ"
    before = guard._committed_source_hashes(BASELINE_COMMIT, scopes)
    assert before == expected, "CI Rust must follow exact formatting baseline"
    after = guard._committed_source_hashes(SOURCE_COMMIT, scopes)
    assert len(before) == len(after) == 466 and set(before) == set(after), "CI Rust inventory drift"
    changed = guard._verify_repair_delta(value, before, after, value)
    assert set(changed) == SOURCE_PATHS, "CI Rust changed paths exceed reviewed scope"
    return value, after, changed
