"""Exact pct-equity amendment admission without reissuing old certificates."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_pct_source_amendment as current
from tools import portfolio_repair_source_guard as guard


REPAIR_COMMIT = "b4c4f934a33465b379657bbe1b73745280db84fe"


@pytest.fixture(scope="module")
def sealed_data():
    # No collection-time manifest read: main seals the source receipt first.
    return current.manifest(guard)


@pytest.fixture(scope="module")
def trees(sealed_data):
    return {
        side: guard._committed_source_hashes(sealed_data[side + "_commit"], sealed_data["scopes"])
        for side in ("baseline", "source")
    }


def test_sealed_manifest_binds_exact_source_repair_and_not_artifact_claims(sealed_data):
    assert sealed_data["baseline_commit"] == current.BASELINE_COMMIT
    assert sealed_data["source_commit"] == REPAIR_COMMIT
    assert set(sealed_data["sources"]) == current.SOURCE_PATHS
    assert sha256((guard.ROOT / current.MANIFEST_NAME).read_bytes()).hexdigest() == current.MANIFEST_SHA256
    assert sealed_data["source_only"] is True
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued"):
        assert sealed_data[key] is False


def test_current_source_qualification_uses_repair_without_historical_invariance(sealed_data):
    result = guard.verify_current_source()
    assert result["source_commit"] == sealed_data["source_commit"]
    assert result["current_source_qualified"]
    assert result["qualified_source_count"] == current.SOURCE_COUNT == 466
    assert result["financial_source_changed"] and not result["financial_numeric_source_unchanged"]
    assert not result["financial_rust_unchanged"]
    assert result["historical_receipts_unchanged"] and not result["historical_guards_reexecuted"]
    assert not result["native_artifacts_qualified"] and not result["publication"]


@pytest.mark.parametrize("name", sorted(current.SOURCE_PATHS))
def test_only_exact_committed_after_bytes_normalize_to_before(sealed_data, name):
    entry = sealed_data["sources"][name]
    before = guard._blob(entry["before_commit"], name, entry["before_sha256"])
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    assert before != after
    assert current.without_pct_activity(after, name, guard) == before
    assert current.without_pct_activity(before, name, guard) == before
    for unknown in (after + b"\n# unreviewed suffix\n", b"# unreviewed prefix\n" + after):
        assert current.without_pct_activity(unknown, name, guard) == unknown


def test_unknown_path_cannot_normalize_even_exact_known_contents(sealed_data):
    name = "src/quantbt/endpoint.py"
    entry = sealed_data["sources"][name]
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    assert current.without_pct_activity(after, "src/quantbt/unreviewed.py", guard) == after


def test_manifest_bytes_must_match_main_pin(tmp_path, monkeypatch, sealed_data):
    path = tmp_path / "manifest.json"
    path.write_bytes((guard.ROOT / current.MANIFEST_NAME).read_bytes() + b"\n")
    monkeypatch.setattr(current, "MANIFEST_NAME", str(path))
    with pytest.raises(AssertionError, match="pct activity manifest digest"):
        current.manifest(guard)


def test_pending_pin_is_fail_closed(monkeypatch):
    monkeypatch.setattr(current, "MANIFEST_SHA256", "PENDING_MAIN_PIN_AFTER_FOCUSED_NATIVE_PASS")
    with pytest.raises(AssertionError, match="manifest is not sealed"):
        current.manifest(guard)


def _repoint_manifest(value, tmp_path, monkeypatch):
    # Repinning only inside a negative test checks the schema's own boundaries.
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
        ("source_commit", "b4c4f93", "source commit"),
        ("scopes", ["src"], "source scopes differ"),
        ("source_only", False, "source-only"),
        ("native_artifacts_qualified", True, "cannot reissue claims"),
        ("publication", True, "cannot reissue claims"),
        ("historical_financial_invariance_claim_reissued", True, "cannot reissue claims"),
        ("financial_numeric_source_unchanged", True, "cannot claim source invariance"),
        ("financial_rust_unchanged", True, "cannot claim source invariance"),
    ],
)
def test_repinning_cannot_expand_contract(sealed_data, tmp_path, monkeypatch, key, value, message):
    changed = deepcopy(sealed_data)
    changed[key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match=message):
        current.manifest(guard)


@pytest.mark.parametrize("extra", [False, True], ids=["missing_reviewed_path", "extra_runtime_path"])
def test_manifest_requires_exact_six_path_set(sealed_data, tmp_path, monkeypatch, extra):
    changed = deepcopy(sealed_data)
    if extra:
        changed["sources"]["src/quantbt/unreviewed.py"] = deepcopy(changed["sources"]["src/quantbt/endpoint.py"])
    else:
        changed["sources"].pop("rust/native_event/src/lib.rs")
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match="exactly six reviewed runtime paths"):
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
def test_source_entry_cannot_change_commit_or_omit_exact_digest(sealed_data, tmp_path, monkeypatch, key, value, message):
    changed = deepcopy(sealed_data)
    changed["sources"]["src/quantbt/endpoint.py"][key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match=message):
        current.manifest(guard)


def test_manifest_cannot_pad_reviewed_set_with_unchanged_source(sealed_data, tmp_path, monkeypatch):
    changed = deepcopy(sealed_data)
    entry = changed["sources"]["src/quantbt/endpoint.py"]
    entry["after_sha256"] = entry["before_sha256"]
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match="entry must change"):
        current.manifest(guard)


def test_exact_baseline_inventory_and_declared_delta_apply(sealed_data, trees):
    value, after, changed = current.apply_pct_activity(guard, dict(trees["baseline"]), sealed_data["scopes"])
    assert value == sealed_data
    assert after == trees["source"]
    assert set(after) == set(trees["baseline"]) and len(after) == 466
    assert set(changed) == current.SOURCE_PATHS


@pytest.mark.parametrize("change", ["bytes", "missing", "extra"])
def test_wrong_caller_baseline_is_not_normalized(sealed_data, trees, change):
    expected = dict(trees["baseline"])
    if change == "bytes":
        expected["src/quantbt/endpoint.py"] = "0" * 64
    elif change == "missing":
        expected.pop("src/quantbt/endpoint.py")
    else:
        expected["src/quantbt/unreviewed.py"] = "0" * 64
    with pytest.raises(AssertionError, match="exact approved current baseline"):
        current.apply_pct_activity(guard, expected, sealed_data["scopes"])


def test_caller_cannot_narrow_qualified_scopes(sealed_data, trees):
    with pytest.raises(AssertionError, match="source scopes differ"):
        current.apply_pct_activity(guard, trees["baseline"], ["src"])


@pytest.mark.parametrize("change", ["extra", "missing", "replace", "undeclared_bytes", "reviewed_bytes"])
def test_post_tree_drift_never_becomes_an_amendment(sealed_data, trees, monkeypatch, change):
    after = dict(trees["source"])
    outside = next(name for name in after if name not in current.SOURCE_PATHS)
    if change in {"missing", "replace"}:
        after.pop(outside)
    if change in {"extra", "replace"}:
        after["src/quantbt/unreviewed.py"] = "0" * 64
    if change == "undeclared_bytes":
        after[outside] = "0" * 64
    if change == "reviewed_bytes":
        after["src/quantbt/endpoint.py"] = "0" * 64

    def committed(commit, scopes):
        assert scopes == sealed_data["scopes"]
        return dict(trees["baseline"]) if commit == sealed_data["baseline_commit"] else dict(after)

    monkeypatch.setattr(guard, "_committed_source_hashes", committed)
    message = ("source inventory changed" if change in {"extra", "missing", "replace"}
               else "unreviewed/missing committed repair changes" if change == "undeclared_bytes"
               else "repair approved bytes differ")
    with pytest.raises(AssertionError, match=message):
        current.apply_pct_activity(guard, trees["baseline"], sealed_data["scopes"])
