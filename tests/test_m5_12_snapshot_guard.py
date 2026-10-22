"""Fail-closed snapshot amendment after the exact pct alias repair."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import m5_12_pct_alias_amendment as previous
from tools import m5_12_snapshot_amendment as current
from tools import portfolio_repair_source_guard as guard


@pytest.fixture(scope="module")
def sealed_data():
    # Main supplies the verified runtime commit and immutable manifest pin.
    return current.manifest(guard)


@pytest.fixture(scope="module")
def trees(sealed_data):
    return {
        side: guard._committed_source_hashes(sealed_data[side + "_commit"], sealed_data["scopes"])
        for side in ("baseline", "source")
    }


def test_manifest_follows_sealed_alias_without_reissuing_claims(sealed_data):
    before = previous.manifest(guard)
    assert before["source_commit"] == sealed_data["baseline_commit"] == current.BASELINE_COMMIT
    assert current.BASELINE_COMMIT == "45fd6ec5bc0f2556ff024ffd1314469e06c0b07a"
    assert sealed_data["source_commit"] == current.SOURCE_COMMIT
    assert sealed_data["scopes"] == before["scopes"]
    assert set(sealed_data["sources"]) == current.SOURCE_PATHS == {
        "src/quantbt/mode5/continuous.py", "src/quantbt/mode5/continuous_retention.py",
    }
    assert sum(map(len, current.CONSTRUCTORS.values())) == 3
    assert sha256((guard.ROOT / current.MANIFEST_NAME).read_bytes()).hexdigest() == current.MANIFEST_SHA256
    assert sealed_data["source_only"] is True
    for key in ("native_artifacts_qualified", "publication", "historical_financial_invariance_claim_reissued"):
        assert sealed_data[key] is False


def test_current_source_after_main_hook_is_source_only(sealed_data):
    result = guard.verify_current_source()
    assert result["source_commit"] == sealed_data["source_commit"]
    assert result["current_source_qualified"]
    assert result["qualified_source_count"] == current.SOURCE_COUNT == 466
    assert result["financial_source_changed"] and not result["financial_numeric_source_unchanged"]
    assert result["historical_receipts_unchanged"] and not result["historical_guards_reexecuted"]
    assert not result["native_artifacts_qualified"] and not result["publication"]


@pytest.mark.parametrize("name", sorted(current.SOURCE_PATHS))
def test_exact_sealed_bytes_normalize_but_never_hide_prefix_or_suffix(sealed_data, name):
    entry = sealed_data["sources"][name]
    before = guard._blob(entry["before_commit"], name, entry["before_sha256"])
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    assert before != after
    current.verify_snapshot_delta(before, after, name)
    assert current.without_snapshot(after, name, guard) == before
    assert current.without_snapshot(before, name, guard) == before
    for unknown in (after + b"\n# unreviewed suffix\n", b"# unreviewed prefix\n" + after):
        assert current.without_snapshot(unknown, name, guard) == unknown


def test_unknown_path_cannot_acquire_snapshot_normalization(sealed_data):
    name = "src/quantbt/mode5/continuous.py"
    entry = sealed_data["sources"][name]
    after = guard._blob(entry["after_commit"], name, entry["after_sha256"])
    assert current.without_snapshot(after, "src/quantbt/unreviewed.py", guard) == after


def test_manifest_changed_bytes_cannot_reuse_main_pin(tmp_path, monkeypatch, sealed_data):
    path = tmp_path / "manifest.json"
    path.write_bytes((guard.ROOT / current.MANIFEST_NAME).read_bytes() + b"\n")
    monkeypatch.setattr(current, "MANIFEST_NAME", str(path))
    with pytest.raises(AssertionError, match="snapshot manifest digest"):
        current.manifest(guard)


def test_unsealed_manifest_pin_fails_closed(monkeypatch):
    monkeypatch.setattr(current, "MANIFEST_SHA256", "PENDING_MAIN_PIN_AFTER_SNAPSHOT_REPAIR")
    with pytest.raises(AssertionError, match="manifest is not sealed"):
        current.manifest(guard)


def test_unsealed_source_commit_fails_closed(monkeypatch):
    monkeypatch.setattr(current, "MANIFEST_SHA256", "0" * 64)
    monkeypatch.setattr(current, "SOURCE_COMMIT", "PENDING_MAIN_SOURCE_COMMIT_AFTER_SNAPSHOT_REPAIR")
    with pytest.raises(AssertionError, match="source commit is not sealed"):
        current.manifest(guard)


def _repoint_manifest(value, tmp_path, monkeypatch):
    # Repinning tests structural limits independently from the immutable file pin.
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
        ("source_commit", current.BASELINE_COMMIT, "snapshot source commit"),
        ("source_commit", "new-commit", "snapshot source commit"),
        ("scopes", ["src"], "source scopes differ"),
        ("source_only", False, "source-only"),
        ("native_artifacts_qualified", True, "cannot reissue claims"),
        ("publication", True, "cannot reissue claims"),
        ("historical_financial_invariance_claim_reissued", True, "cannot reissue claims"),
        ("financial_numeric_source_unchanged", True, "cannot claim source invariance"),
        ("financial_rust_unchanged", True, "cannot claim source invariance"),
        ("financial_rust_changed", True, "cannot admit native/version changes"),
        ("native_rebuild_required", True, "cannot admit native/version changes"),
        ("version_bump", True, "cannot admit native/version changes"),
        ("native_source_unchanged_relative_to", "0" * 40, "native baseline differs"),
    ],
)
def test_repinning_cannot_expand_snapshot_claims(sealed_data, tmp_path, monkeypatch, key, value, message):
    changed = deepcopy(sealed_data)
    changed[key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match=message):
        current.manifest(guard)


@pytest.mark.parametrize("change", ["missing", "extra_native", "substitute"])
def test_manifest_requires_exact_two_path_set(sealed_data, tmp_path, monkeypatch, change):
    changed = deepcopy(sealed_data)
    if change in {"missing", "substitute"}:
        changed["sources"].pop("src/quantbt/mode5/continuous_retention.py")
    if change in {"extra_native", "substitute"}:
        name = "rust/native_event/src/lib.rs" if change == "extra_native" else "src/quantbt/unreviewed.py"
        changed["sources"][name] = deepcopy(changed["sources"]["src/quantbt/mode5/continuous.py"])
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
def test_entries_require_exact_commits_and_digests(sealed_data, tmp_path, monkeypatch, key, value, message):
    changed = deepcopy(sealed_data)
    changed["sources"]["src/quantbt/mode5/continuous.py"][key] = value
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match=message):
        current.manifest(guard)


def test_unchanged_path_cannot_pad_manifest(sealed_data, tmp_path, monkeypatch):
    changed = deepcopy(sealed_data)
    entry = changed["sources"]["src/quantbt/mode5/continuous.py"]
    entry["after_sha256"] = entry["before_sha256"]
    _repoint_manifest(changed, tmp_path, monkeypatch)
    with pytest.raises(AssertionError, match="entry must change"):
        current.manifest(guard)


def test_manifest_must_follow_exact_alias_source(sealed_data, tmp_path, monkeypatch):
    changed = deepcopy(previous.manifest(guard))
    changed["source_commit"] = "0" * 40
    monkeypatch.setattr(previous, "manifest", lambda owner: changed)
    with pytest.raises(AssertionError, match="follow the sealed alias repair"):
        current.manifest(guard)


def test_exact_delta_keeps_466_inventory_and_native_sources(sealed_data, trees):
    value, after, changed = current.apply_snapshot(guard, dict(trees["baseline"]), sealed_data["scopes"])
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
        expected["src/quantbt/mode5/continuous.py"] = "0" * 64
    elif change == "missing":
        expected.pop("src/quantbt/mode5/continuous.py")
    else:
        expected["src/quantbt/unreviewed.py"] = "0" * 64
    with pytest.raises(AssertionError, match="exact approved current baseline"):
        current.apply_snapshot(guard, expected, sealed_data["scopes"])


def test_caller_cannot_narrow_scopes(sealed_data, trees):
    with pytest.raises(AssertionError, match="source scopes differ"):
        current.apply_snapshot(guard, trees["baseline"], ["src"])


@pytest.mark.parametrize("change", ["extra", "missing", "replace", "undeclared_bytes", "reviewed_bytes", "native_bytes"])
def test_post_tree_drift_never_becomes_snapshot_amendment(sealed_data, trees, monkeypatch, change):
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
        after["src/quantbt/mode5/continuous.py"] = "0" * 64
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
        current.apply_snapshot(guard, trees["baseline"], sealed_data["scopes"])


def _example(name, *, sealed):
    # Structural controls contain no QuantBT execution or scientific assertions.
    return ("\n\n".join(
        "class " + class_name + "(SnapshotValue):\n"
        "    def __post_init__(self):\n"
        "        self.validate_inputs()\n"
        + ("        self._seal_arrays()\n" if sealed else "")
        for class_name in current.CONSTRUCTORS[name]
    ) + "\n").encode()


@pytest.mark.parametrize("name", sorted(current.SOURCE_PATHS))
def test_ast_accepts_only_approved_terminal_calls(name):
    current.verify_snapshot_delta(_example(name, sealed=False), _example(name, sealed=True), name)


@pytest.mark.parametrize(
    "replacement",
    [
        b"        self.validate_snapshot()\n",
        b"        other._seal_arrays()\n",
        b"        self._seal_arrays(1)\n",
        b"        self._seal_arrays(force=True)\n",
        b"        self._seal_arrays(*args)\n",
        b"        self._seal_arrays(**kwargs)\n",
        b"        return self._seal_arrays()\n",
        b"        sealed = self._seal_arrays()\n",
        b"        self._seal_arrays\n",
        b"        if ready:\n            self._seal_arrays()\n",
        b"        self._seal_arrays()\n        self.validate_inputs()\n",
        b"        self._seal_arrays()\n        self._seal_arrays()\n",
        b"",
    ],
)
@pytest.mark.parametrize("name", sorted(current.SOURCE_PATHS))
def test_ast_rejects_missing_duplicate_conditional_nonfinal_or_nonexact_call(name, replacement):
    after = _example(name, sealed=True).replace(b"        self._seal_arrays()\n", replacement, 1)
    with pytest.raises(AssertionError, match="snapshot"):
        current.verify_snapshot_delta(_example(name, sealed=False), after, name)


@pytest.mark.parametrize("name", sorted(current.SOURCE_PATHS))
@pytest.mark.parametrize("change", ["body", "import", "extra_class", "signature", "decorator", "docstring"])
def test_ast_rejects_unrelated_semantic_changes(name, change):
    after = _example(name, sealed=True)
    if change == "body":
        after = after.replace(b"self.validate_inputs()", b"self.bypass_inputs()", 1)
    elif change == "import":
        after = b"import unreviewed\n" + after
    elif change == "extra_class":
        after += b"\nclass Unreviewed:\n    pass\n"
    elif change == "signature":
        after = after.replace(b"def __post_init__(self):", b"def __post_init__(self, extra=None):", 1)
    elif change == "decorator":
        after = after.replace(b"    def __post_init__", b"    @unreviewed\n    def __post_init__", 1)
    else:
        after = b'"""Changed runtime module docstring."""\n' + after
    with pytest.raises(AssertionError, match="AST differs beyond"):
        current.verify_snapshot_delta(_example(name, sealed=False), after, name)


def test_ast_cannot_put_both_continuous_seals_in_one_constructor():
    name = "src/quantbt/mode5/continuous.py"
    after = _example(name, sealed=True).replace(b"        self._seal_arrays()\n", b"", 1)
    after += b"        self._seal_arrays()\n"
    with pytest.raises(AssertionError, match="final constructor statement"):
        current.verify_snapshot_delta(_example(name, sealed=False), after, name)


def test_ast_cannot_move_seal_to_different_method():
    name = "src/quantbt/mode5/continuous_retention.py"
    after = _example(name, sealed=False) + b"    def unrelated(self):\n        self._seal_arrays()\n"
    with pytest.raises(AssertionError, match="final constructor statement"):
        current.verify_snapshot_delta(_example(name, sealed=False), after, name)


def test_ast_rejects_unreviewed_path_and_already_sealed_baseline():
    name = "src/quantbt/mode5/continuous_retention.py"
    before, after = _example(name, sealed=False), _example(name, sealed=True)
    with pytest.raises(AssertionError, match="path is not reviewed"):
        current.verify_snapshot_delta(before, after, "src/quantbt/unreviewed.py")
    with pytest.raises(AssertionError, match="baseline unexpectedly contains"):
        current.verify_snapshot_delta(after, after, name)


def test_pinned_semantic_drift_is_not_hidden_by_normalization(sealed_data, monkeypatch):
    name = "src/quantbt/mode5/continuous.py"
    before = _example(name, sealed=False)
    after = _example(name, sealed=True).replace(b"self.validate_inputs()", b"self.bypass_inputs()", 1)
    changed = deepcopy(sealed_data)
    entry = changed["sources"][name]
    entry["before_sha256"] = sha256(before).hexdigest()
    entry["after_sha256"] = sha256(after).hexdigest()
    monkeypatch.setattr(current, "manifest", lambda owner: changed)

    def blob(commit, path, digest):
        assert path == name
        result = before if commit == current.BASELINE_COMMIT else after
        assert sha256(result).hexdigest() == digest
        return result

    monkeypatch.setattr(guard, "_blob", blob)
    with pytest.raises(AssertionError, match="AST differs beyond"):
        current.without_snapshot(after, name, guard)
