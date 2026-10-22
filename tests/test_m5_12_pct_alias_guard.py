"""Fail-closed append-only alias amendment after the exact pct activity repair."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_pct_alias_amendment as current
from tools import m5_12_pct_source_amendment as previous
from tools import portfolio_repair_source_guard as guard


REPAIR_COMMIT = "45fd6ec5bc0f2556ff024ffd1314469e06c0b07a"


@pytest.fixture(scope="module")
def sealed_data():
    # Main supplies the sealed alias commit and pin before verification.
    return current.manifest(guard)


@pytest.fixture(scope="module")
def trees(sealed_data):
    return {
        side: guard._committed_source_hashes(sealed_data[side + "_commit"], sealed_data["scopes"])
        for side in ("baseline", "source")
    }


def test_manifest_follows_sealed_activity_repair_without_reissuing_claims(sealed_data):
    before = previous.manifest(guard)
    assert before["source_commit"] == sealed_data["baseline_commit"] == current.BASELINE_COMMIT
    assert sealed_data["source_commit"] == REPAIR_COMMIT
    assert sealed_data["scopes"] == before["scopes"]
    assert set(sealed_data["sources"]) == current.SOURCE_PATHS
    assert sha256((guard.ROOT / current.MANIFEST_NAME).read_bytes()).hexdigest() == current.MANIFEST_SHA256
    assert sealed_data["source_only"] is True
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued"):
        assert sealed_data[key] is False


def test_current_source_qualification_uses_alias_commit_without_historical_claims(sealed_data):
    result = guard.verify_current_source()
    assert result["source_commit"] == sealed_data["source_commit"]
    assert result["current_source_qualified"]
    assert result["qualified_source_count"] == current.SOURCE_COUNT == 466
    assert result["financial_source_changed"] and not result["financial_numeric_source_unchanged"]
    assert not result["financial_rust_unchanged"]
    assert result["historical_receipts_unchanged"] and not result["historical_guards_reexecuted"]
    assert not result["native_artifacts_qualified"] and not result["publication"]


@pytest.mark.parametrize("name", sorted(current.SOURCE_PATHS))
def test_exact_alias_bytes_normalize_without_hiding_prefix_or_suffix_drift(sealed_data, name):
    entry = sealed_data["sources"][name]
    before = guard._blob(entry["before_commit"], name, entry["before_sha256"])
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    assert before != after
    assert current.without_pct_alias(after, name, guard) == before
    assert current.without_pct_alias(before, name, guard) == before
    for unknown in (after + b"\n# unreviewed suffix\n", b"# unreviewed prefix\n" + after):
        assert current.without_pct_alias(unknown, name, guard) == unknown


def test_unknown_path_cannot_acquire_alias_normalization(sealed_data):
    name = "src/quantbt/endpoint.py"
    entry = sealed_data["sources"][name]
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    assert current.without_pct_alias(after, "src/quantbt/unreviewed.py", guard) == after


def test_manifest_changed_bytes_cannot_reuse_main_pin(tmp_path, monkeypatch, sealed_data):
    path = tmp_path / "manifest.json"
    path.write_bytes((guard.ROOT / current.MANIFEST_NAME).read_bytes() + b"\n")
    monkeypatch.setattr(current, "MANIFEST_NAME", str(path))
    with pytest.raises(AssertionError, match="pct alias manifest digest"):
        current.manifest(guard)


def test_unsealed_alias_pin_fails_closed(monkeypatch):
    monkeypatch.setattr(current, "MANIFEST_SHA256", "PENDING_MAIN_PIN_AFTER_ALIAS_REPAIR")
    with pytest.raises(AssertionError, match="manifest is not sealed"):
        current.manifest(guard)


def _repoint_manifest(value, tmp_path, monkeypatch):
    # Repinning here tests schema boundaries independently from file integrity.
    path = tmp_path / "manifest.json"
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(current, "MANIFEST_NAME", str(path))
    monkeypatch.setattr(current, "MANIFEST_SHA256", sha256(raw).hexdigest())


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("schema", "unreviewed-v2", "amendment schema"),
        ("baseline_commit", "0" * 40, "baseline differs"),
        ("source_commit", current.BASELINE_COMMIT, "source commit"),
        ("source_commit", "new-commit", "source commit"),
        ("scopes", ["src"], "source scopes differ"),
        ("source_only", False, "source-only"),
        ("native_artifacts_qualified", True, "cannot reissue claims"),
        ("publication", True, "cannot reissue claims"),
        ("historical_financial_invariance_claim_reissued", True, "cannot reissue claims"),
        ("financial_numeric_source_unchanged", True, "cannot claim source invariance"),
        ("financial_rust_unchanged", True, "cannot claim source invariance"),
        ("financial_rust_changed", True, "cannot admit native changes"),
    ],
)
def test_repinning_cannot_expand_alias_contract(sealed_data, tmp_path, monkeypatch, key, value, message):
    changed = deepcopy(sealed_data)
    changed[key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match=message):
        current.manifest(guard)


@pytest.mark.parametrize("extra", [False, True], ids=["missing_path", "extra_native_path"])
def test_alias_manifest_requires_exact_two_path_set(sealed_data, tmp_path, monkeypatch, extra):
    changed = deepcopy(sealed_data)
    if extra:
        changed["sources"]["rust/native_event/src/lib.rs"] = deepcopy(changed["sources"]["src/quantbt/endpoint.py"])
    else:
        changed["sources"].pop("src/quantbt/endpoint.py")
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match="exactly two reviewed runtime paths"):
        current.manifest(guard)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("before_commit", "0" * 40, "entry baseline differs"),
        ("after_commit", current.BASELINE_COMMIT, "entry source commit differs"),
        ("before_sha256", None, "source digests"),
        ("after_sha256", "0" * 63, "source digests"),
    ],
)
def test_entry_requires_exact_commits_and_digests(sealed_data, tmp_path, monkeypatch, key, value, message):
    changed = deepcopy(sealed_data)
    changed["sources"]["src/quantbt/endpoint.py"][key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match=message):
        current.manifest(guard)


def test_alias_cannot_pad_two_path_set_with_unchanged_bytes(sealed_data, tmp_path, monkeypatch):
    changed = deepcopy(sealed_data)
    entry = changed["sources"]["src/quantbt/endpoint.py"]
    entry["after_sha256"] = entry["before_sha256"]
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match="entry must change"):
        current.manifest(guard)


def test_exact_alias_tree_delta_preserves_inventory_and_all_native_sources(sealed_data, trees):
    value, after, changed = current.apply_pct_alias(guard, dict(trees["baseline"]), sealed_data["scopes"])
    assert value == sealed_data and after == trees["source"]
    assert len(after) == 466 and set(after) == set(trees["baseline"])
    assert set(changed) == current.SOURCE_PATHS
    assert {n: v for n, v in after.items() if n.startswith("rust/")} == {
        n: v for n, v in trees["baseline"].items() if n.startswith("rust/")
    }


@pytest.mark.parametrize("change", ["bytes", "missing", "extra"])
def test_wrong_caller_baseline_is_not_admitted(sealed_data, trees, change):
    expected = dict(trees["baseline"])
    if change == "bytes":
        expected["src/quantbt/endpoint.py"] = "0" * 64
    elif change == "missing":
        expected.pop("src/quantbt/endpoint.py")
    else:
        expected["src/quantbt/unreviewed.py"] = "0" * 64
    with pytest.raises(AssertionError, match="exact approved current baseline"):
        current.apply_pct_alias(guard, expected, sealed_data["scopes"])


def test_alias_caller_cannot_narrow_scopes(sealed_data, trees):
    with pytest.raises(AssertionError, match="source scopes differ"):
        current.apply_pct_alias(guard, trees["baseline"], ["src"])


@pytest.mark.parametrize("change", ["extra", "missing", "replace", "undeclared_bytes", "reviewed_bytes", "native_bytes"])
def test_post_tree_drift_never_becomes_alias_amendment(sealed_data, trees, monkeypatch, change):
    after = dict(trees["source"])
    outside = "src/quantbt/optimization/meta_selection/observer.py"
    assert outside in after and outside not in current.SOURCE_PATHS
    if change in {"missing", "replace"}:
        after.pop(outside)
    if change in {"extra", "replace"}:
        after["src/quantbt/unreviewed.py"] = "0" * 64
    if change == "undeclared_bytes":
        after[outside] = "0" * 64
    if change == "reviewed_bytes":
        after["src/quantbt/endpoint.py"] = "0" * 64
    if change == "native_bytes":
        after["rust/crates/quantbt-execution/src/target.rs"] = "0" * 64

    def committed(commit, scopes):
        assert scopes == sealed_data["scopes"]
        return dict(trees["baseline"]) if commit == sealed_data["baseline_commit"] else dict(after)

    monkeypatch.setattr(guard, "_committed_source_hashes", committed)
    message = ("source inventory changed" if change in {"extra", "missing", "replace"}
               else "cannot admit native changes" if change == "native_bytes"
               else "unreviewed/missing committed repair changes" if change == "undeclared_bytes"
               else "repair approved bytes differ")
    with pytest.raises(AssertionError, match=message):
        current.apply_pct_alias(guard, trees["baseline"], sealed_data["scopes"])
