"""Exact reviewed rustfmt amendment; never a general whitespace normalization."""

from hashlib import sha256
import json


MANIFEST_NAME = "docs/maintenance/evidence/m5-12-ci-format-source-amendment.json"
MANIFEST_SHA256 = "da2d3b965b2cf7bf8732ca467f9f7e23743376efe099fedf62d984dce7a7be46"
BASELINE_COMMIT = "67f75bfbbf06932235e30d9d5ebebb0f7cb0aa0f"
SOURCE_COMMIT = "4e02a6077b974e15e9be0a4a4e94c05716193818"
SOURCE_PATHS = frozenset(("rust/crates/quantbt-engine/src/session.rs",
                          "rust/native_event/src/reactive_numeric.rs"))
EDITS = {
    "rust/crates/quantbt-engine/src/session.rs": (
        (b"""            let pure_reduction = order.reduce_only()
                && current * delta < 0.0
                && delta.abs() <= current.abs();""",
         b"""            let pure_reduction =
                order.reduce_only() && current * delta < 0.0 && delta.abs() <= current.abs();"""),
        (b"""            let market = FullMarketData::new(
                vec![0, 1, 2, 3], prices.clone(), prices.clone(), prices.clone(),
                prices, vec![10_000.0; 4], vec![0.0; 4], vec![false; 4], 1,
            ).unwrap();
            let mut engine = FullSession::new(
                Arc::new(market), vec![1.0], vec![1.0], vec![0.0004],
                20_000.0, 0.005, 0.0, false,
            ).unwrap();
            engine.set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN).unwrap();""",
         b"""            let market = FullMarketData::new(
                vec![0, 1, 2, 3],
                prices.clone(),
                prices.clone(),
                prices.clone(),
                prices,
                vec![10_000.0; 4],
                vec![0.0; 4],
                vec![false; 4],
                1,
            )
            .unwrap();
            let mut engine = FullSession::new(
                Arc::new(market),
                vec![1.0],
                vec![1.0],
                vec![0.0004],
                20_000.0,
                0.005,
                0.0,
                false,
            )
            .unwrap();
            engine
                .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
                .unwrap();"""),
        (b"            let fee = if reduce_only { quantity.min(190.0) * 110.0 * 0.0004 } else { 0.0 };",
         b"""            let fee = if reduce_only {
                quantity.min(190.0) * 110.0 * 0.0004
            } else {
                0.0
            };"""),
    ),
    "rust/native_event/src/reactive_numeric.rs": (
        (b"    fn cancellation_tokens(&self, py: Python<'_>) -> PyResult<Vec<Py<ReactiveCancellationTokenCore>>> {",
         b"""    fn cancellation_tokens(
        &self,
        py: Python<'_>,
    ) -> PyResult<Vec<Py<ReactiveCancellationTokenCore>>> {"""),
    ),
}


def verify_format_delta(before, after, name):
    assert name in EDITS, "unreviewed rustfmt path"
    expected = before
    for old, new in EDITS[name]:
        assert expected.count(old) == 1, "rustfmt reviewed baseline differs: " + name
        expected = expected.replace(old, new, 1)
    assert expected == after, "rustfmt delta exceeds exact reviewed edits: " + name


def manifest(guard):
    assert len(MANIFEST_SHA256) == 64, "CI format manifest must be sealed"
    path = guard.ROOT / MANIFEST_NAME
    assert path.is_file() and not path.is_symlink(), "regular CI format manifest required"
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, "CI format manifest digest"
    value = json.loads(raw)
    assert value["schema"] == "quantbt.m5_12.ci_format_source.v1"
    assert (value["baseline_commit"], value["source_commit"]) == (BASELINE_COMMIT, SOURCE_COMMIT)
    assert set(value["sources"]) == SOURCE_PATHS, "CI format exact reviewed scope"
    assert value["source_only"] is True and value["rustfmt_only"] is True
    assert value["fresh_native_artifacts_required"] is True
    for key in ("native_artifacts_qualified", "publication", "version_bump",
                "historical_financial_invariance_claim_reissued", "financial_numeric_source_unchanged"):
        assert value[key] is False, "CI format cannot expand claims: " + key
    from tools.m5_12_release120_amendment import manifest as previous_manifest, MANIFEST_SHA256 as previous_digest
    previous = previous_manifest(guard)
    assert value["previous_amendment_sha256"] == previous_digest
    assert value["scopes"] == previous["scopes"] and previous["source_commit"] == BASELINE_COMMIT
    for name, entry in value["sources"].items():
        assert (entry["before_commit"], entry["after_commit"]) == (BASELINE_COMMIT, SOURCE_COMMIT)
        assert entry["before_sha256"] != entry["after_sha256"]
    return value


def without_ci_format(source, name, guard):
    entry = manifest(guard)["sources"].get(name)
    if entry is None or sha256(source).hexdigest() != entry["after_sha256"]:
        return source
    assert source == guard._blob(SOURCE_COMMIT, name, entry["after_sha256"])
    before = guard._blob(BASELINE_COMMIT, name, entry["before_sha256"])
    verify_format_delta(before, source, name)
    return before


def apply_ci_format(guard, expected, scopes):
    value = manifest(guard)
    assert scopes == value["scopes"], "CI format source scopes differ"
    before = guard._committed_source_hashes(BASELINE_COMMIT, scopes)
    assert before == expected, "CI format must follow exact release120 baseline"
    after = guard._committed_source_hashes(SOURCE_COMMIT, scopes)
    assert len(before) == len(after) == 466 and set(before) == set(after), "CI format source inventory drift"
    changed = guard._verify_repair_delta(value, before, after, value)
    assert set(changed) == SOURCE_PATHS, "CI format changed paths exceed reviewed scope"
    for name, entry in value["sources"].items():
        verify_format_delta(guard._blob(BASELINE_COMMIT, name, entry["before_sha256"]),
                            guard._blob(SOURCE_COMMIT, name, entry["after_sha256"]), name)
    return value, after, changed
