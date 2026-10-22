"""Only the exact reviewed rustfmt delta follows the retained release120 seal."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_ci_format_amendment as amendment
from tools import m5_12_release120_amendment as release120
from tools import portfolio_repair_source_guard as guard


@pytest.fixture(scope="module")
def sealed_data():
    return amendment.manifest(guard)


@pytest.fixture(scope="module")
def trees(sealed_data):
    return {
        side: guard._committed_source_hashes(sealed_data[side + "_commit"], sealed_data["scopes"])
        for side in ("baseline", "source")
    }


@pytest.fixture(scope="module")
def current_result():
    return guard.verify_current_source()


def _blobs(sealed_data, name):
    entry = sealed_data["sources"][name]
    return (
        guard._blob(amendment.BASELINE_COMMIT, name, entry["before_sha256"]),
        guard._blob(amendment.SOURCE_COMMIT, name, entry["after_sha256"]),
    )


def test_sealed_manifest_follows_release120_without_reissuing_artifact_claims(sealed_data):
    previous = release120.manifest(guard)
    assert sealed_data["baseline_commit"] == previous["source_commit"] == amendment.BASELINE_COMMIT
    assert amendment.BASELINE_COMMIT == "67f75bfbbf06932235e30d9d5ebebb0f7cb0aa0f"
    assert sealed_data["source_commit"] == amendment.SOURCE_COMMIT == "4e02a6077b974e15e9be0a4a4e94c05716193818"
    assert sealed_data["scopes"] == previous["scopes"]
    assert sealed_data["previous_amendment_sha256"] == release120.MANIFEST_SHA256
    assert set(sealed_data["sources"]) == amendment.SOURCE_PATHS == {
        "rust/crates/quantbt-engine/src/session.rs", "rust/native_event/src/reactive_numeric.rs",
    }
    assert sha256((guard.ROOT / amendment.MANIFEST_NAME).read_bytes()).hexdigest() == amendment.MANIFEST_SHA256
    for key in ("source_only", "rustfmt_only", "fresh_native_artifacts_required"):
        assert sealed_data[key] is True
    for key in ("native_artifacts_qualified", "publication", "version_bump",
                "historical_financial_invariance_claim_reissued", "financial_numeric_source_unchanged"):
        assert sealed_data[key] is False


def test_current_source_keeps_release120_and_snapshot_identities(sealed_data, current_result):
    from tools import m5_12_snapshot_amendment as snapshot

    assert current_result["source_commit"] == sealed_data["source_commit"]
    assert current_result["m5_12_release120_source_commit"] == release120.SOURCE_COMMIT
    assert current_result["m5_12_snapshot_source_commit"] == snapshot.SOURCE_COMMIT == release120.BASELINE_COMMIT
    assert current_result["m5_12_release120_amendment_sha256"] == release120.MANIFEST_SHA256
    assert current_result["m5_12_snapshot_amendment_sha256"] == snapshot.MANIFEST_SHA256
    assert current_result["m5_12_ci_format_amendment_sha256"] == amendment.MANIFEST_SHA256
    assert set(current_result["m5_12_ci_format_changed_sources"]) == amendment.SOURCE_PATHS
    assert current_result["current_source_qualified"] and current_result["qualified_source_count"] == 466
    assert current_result["financial_source_changed"] and not current_result["financial_numeric_source_unchanged"]
    assert not current_result["financial_rust_unchanged"]
    assert current_result["historical_receipts_unchanged"] and not current_result["historical_guards_reexecuted"]
    assert not current_result["native_artifacts_qualified"] and not current_result["publication"]


def test_retained_release_manifest_and_historical_receipts_are_not_rewritten(current_result):
    raw = (guard.ROOT / release120.MANIFEST_NAME).read_bytes()
    assert raw == guard._blob(amendment.SOURCE_COMMIT, release120.MANIFEST_NAME, release120.MANIFEST_SHA256)
    qualification = guard._qualification_manifest()
    assert set(current_result["historical_receipts"]) == set(qualification["historical_receipts"])
    for key, entry in qualification["historical_receipts"].items():
        archived = guard._blob(qualification["baseline_commit"], entry["path"], entry["sha256"])
        assert (guard.ROOT / entry["path"]).read_bytes() == archived
        receipt = current_result["historical_receipts"][key]
        assert receipt == dict(path=entry["path"], sha256=entry["sha256"], claim_scope="historical_only",
                               source=json.loads(archived)[entry["source_key"]])


@pytest.mark.parametrize("key", ("c02", "e04"))
def test_ci_format_cannot_reissue_a_modified_historical_receipt(tmp_path, monkeypatch, key):
    qualification = guard._qualification_manifest()
    entry = qualification["historical_receipts"][key]
    archived = guard._blob(qualification["baseline_commit"], entry["path"], entry["sha256"])
    path = tmp_path / entry["path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(archived + b"\n")
    qualification = deepcopy(qualification)
    qualification["historical_receipts"] = {key: entry}
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "_blob", lambda commit, name, digest: archived)
    with pytest.raises(AssertionError, match="historical receipt changed"):
        guard._historical_receipts(qualification)


@pytest.mark.parametrize("name", sorted(amendment.SOURCE_PATHS))
def test_only_exact_reviewed_bytes_normalize_to_release120(sealed_data, name):
    before, after = _blobs(sealed_data, name)
    assert before != after
    amendment.verify_format_delta(before, after, name)
    assert amendment.without_ci_format(after, name, guard) == before
    assert amendment.without_ci_format(before, name, guard) == before
    assert guard.without_portfolio_repair(after, name) == guard.without_portfolio_repair(before, name)


@pytest.mark.parametrize("name", sorted(amendment.SOURCE_PATHS))
@pytest.mark.parametrize("mutation", ("suffix", "prefix", "spacing", "numeric", "string", "comment", "comma"))
def test_formatting_never_admits_unknown_bytes_or_general_whitespace(sealed_data, name, mutation):
    before, after = _blobs(sealed_data, name)
    if mutation == "suffix":
        unknown = after + b"\n"
    elif mutation == "prefix":
        unknown = b" \n" + after
    elif mutation == "spacing":
        unknown = after.replace(b"\n    ", b"\n     ", 1)
    elif mutation == "numeric":
        unknown = after.replace(b"0.0", b"0.1", 1)
    elif mutation == "string":
        token = (b"full market tape must contain bars and symbols" if name.endswith("session.rs")
                 else b"reactive native execution canceled at a certified bar boundary")
        unknown = after.replace(token, token + b" changed", 1)
    elif mutation == "comment":
        unknown = after.replace(b"//! ", b"//! changed ", 1)
    else:
        token = (b"                1,\n            )\n            .unwrap();\n            let mut engine = FullSession::new("
                 if name.endswith("session.rs")
                 else b"        py: Python<'_>,\n    ) -> PyResult<Vec<Py<ReactiveCancellationTokenCore>>>")
        assert after.count(token) == 1
        unknown = after.replace(token, token.replace(b",\n", b"\n", 1), 1)
    assert unknown not in (before, after)
    assert amendment.without_ci_format(unknown, name, guard) == unknown
    with pytest.raises(AssertionError, match="exact reviewed edits"):
        amendment.verify_format_delta(before, unknown, name)


@pytest.mark.parametrize("name", sorted(amendment.SOURCE_PATHS))
def test_reviewed_bytes_cannot_be_normalized_under_another_path(sealed_data, name):
    before, after = _blobs(sealed_data, name)
    wrong_names = ("rust/unreviewed.rs", *sorted(amendment.SOURCE_PATHS - {name}))
    for wrong in wrong_names:
        assert amendment.without_ci_format(after, wrong, guard) == after
        with pytest.raises(AssertionError):
            amendment.verify_format_delta(before, after, wrong)


def test_modified_manifest_cannot_reuse_sealed_digest(tmp_path, monkeypatch, sealed_data):
    path = tmp_path / "manifest.json"
    path.write_bytes((guard.ROOT / amendment.MANIFEST_NAME).read_bytes() + b"\n")
    monkeypatch.setattr(amendment, "MANIFEST_NAME", str(path))
    with pytest.raises(AssertionError, match="manifest digest"):
        amendment.manifest(guard)


def test_unsealed_manifest_is_not_admitted(monkeypatch):
    monkeypatch.setattr(amendment, "MANIFEST_SHA256", "PENDING")
    with pytest.raises(AssertionError, match="must be sealed"):
        amendment.manifest(guard)


def _repoint_manifest(value, tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(amendment, "MANIFEST_NAME", str(path))
    monkeypatch.setattr(amendment, "MANIFEST_SHA256", sha256(raw).hexdigest())


@pytest.mark.parametrize(
    ("key", "value"),
    [("schema", "unreviewed-v2"), ("baseline_commit", "0" * 40),
     ("source_commit", amendment.BASELINE_COMMIT), ("scopes", ["rust"]),
     ("previous_amendment_sha256", "0" * 64), ("source_only", False),
     ("rustfmt_only", False), ("fresh_native_artifacts_required", False),
     ("native_artifacts_qualified", True), ("publication", True), ("version_bump", True),
     ("historical_financial_invariance_claim_reissued", True), ("financial_numeric_source_unchanged", True)],
)
def test_repinned_manifest_cannot_change_baseline_or_expand_claims(sealed_data, tmp_path, monkeypatch, key, value):
    changed = deepcopy(sealed_data)
    changed[key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError):
        amendment.manifest(guard)


@pytest.mark.parametrize("change", ("missing", "extra", "substitute"))
def test_manifest_requires_exact_reviewed_source_set(sealed_data, tmp_path, monkeypatch, change):
    changed = deepcopy(sealed_data)
    name = "rust/crates/quantbt-engine/src/session.rs"
    entry = deepcopy(changed["sources"][name])
    if change in {"missing", "substitute"}:
        changed["sources"].pop(name)
    if change in {"extra", "substitute"}:
        changed["sources"]["rust/unreviewed.rs"] = entry
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match="exact reviewed scope"):
        amendment.manifest(guard)


@pytest.mark.parametrize("key", ("before_commit", "after_commit", "unchanged_digest"))
def test_manifest_entries_cannot_change_identity_or_pad_delta(sealed_data, tmp_path, monkeypatch, key):
    changed = deepcopy(sealed_data)
    entry = changed["sources"]["rust/crates/quantbt-engine/src/session.rs"]
    if key == "unchanged_digest":
        entry["after_sha256"] = entry["before_sha256"]
    else:
        entry[key] = "0" * 40
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError):
        amendment.manifest(guard)


def test_exact_delta_preserves_source_inventory_and_every_other_digest(sealed_data, trees):
    value, after, changed = amendment.apply_ci_format(guard, dict(trees["baseline"]), sealed_data["scopes"])
    assert value == sealed_data and after == trees["source"]
    assert len(after) == 466 and set(after) == set(trees["baseline"])
    assert set(changed) == amendment.SOURCE_PATHS
    assert {name for name in after if after[name] != trees["baseline"][name]} == amendment.SOURCE_PATHS


@pytest.mark.parametrize("change", ("bytes", "missing", "extra"))
def test_caller_requires_exact_release120_baseline(sealed_data, trees, change):
    expected = dict(trees["baseline"])
    name = "rust/crates/quantbt-engine/src/session.rs"
    if change == "bytes":
        expected[name] = "0" * 64
    elif change == "missing":
        expected.pop(name)
    else:
        expected["rust/unreviewed.rs"] = "0" * 64
    with pytest.raises(AssertionError, match="exact release120 baseline"):
        amendment.apply_ci_format(guard, expected, sealed_data["scopes"])


def test_caller_cannot_narrow_scopes(sealed_data, trees):
    with pytest.raises(AssertionError, match="source scopes differ"):
        amendment.apply_ci_format(guard, trees["baseline"], ["rust"])


@pytest.mark.parametrize("change", ("extra", "missing", "replace", "undeclared_bytes", "reviewed_bytes", "historical_bytes"))
def test_unreviewed_post_tree_changes_are_not_formatting(sealed_data, trees, monkeypatch, change):
    after = dict(trees["source"])
    outside = "rust/native_event/src/lib.rs"
    assert outside in after and outside not in amendment.SOURCE_PATHS
    if change in {"missing", "replace"}:
        after.pop(outside)
    if change in {"extra", "replace"}:
        after["rust/unreviewed.rs"] = "0" * 64
    if change == "undeclared_bytes":
        after[outside] = "0" * 64
    if change == "reviewed_bytes":
        after["rust/crates/quantbt-engine/src/session.rs"] = "0" * 64
    if change == "historical_bytes":
        after.update({name: trees["baseline"][name] for name in amendment.SOURCE_PATHS})

    def committed(commit, scopes):
        assert scopes == sealed_data["scopes"]
        assert commit in (amendment.BASELINE_COMMIT, amendment.SOURCE_COMMIT)
        return dict(trees["baseline"]) if commit == amendment.BASELINE_COMMIT else dict(after)

    monkeypatch.setattr(guard, "_committed_source_hashes", committed)
    message = ("source inventory drift" if change in {"extra", "missing", "replace"}
               else "unreviewed/missing committed repair changes" if change == "undeclared_bytes"
               else "repair approved bytes differ")
    with pytest.raises(AssertionError, match=message):
        amendment.apply_ci_format(guard, trees["baseline"], sealed_data["scopes"])


def test_both_installed_verifiers_pin_ci_format_amendment():
    from tools.m5_12_installed_preflight import verifier_manifest
    from tools.m5_12_pct_installed import source_pins

    name = "tools/m5_12_ci_format_amendment.py"
    assert verifier_manifest()[name] == source_pins()[name] == sha256((guard.ROOT / name).read_bytes()).hexdigest()
