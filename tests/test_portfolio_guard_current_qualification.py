"""Current byte qualification is separate from historical financial invariance."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools import portfolio_repair_source_guard as guard


def test_current_qualification_preserves_historical_claims_without_reissuing_them(monkeypatch):
    from tools import qms_c02_source_guard, qms_e04_source_guard

    def historical_verify():
        pytest.fail("current qualification must not rerun historical financial-unchanged guards")

    monkeypatch.setattr(qms_c02_source_guard, "verify", historical_verify)
    monkeypatch.setattr(qms_e04_source_guard, "verify", historical_verify)
    source = guard.verify_current_source()
    assert source["current_source_qualified"] is True
    from tools.m5_12_ci_format_amendment import SOURCE_COMMIT
    from tools.m5_12_release120_amendment import SOURCE_COMMIT as release120_commit
    assert source["source_commit"] == SOURCE_COMMIT
    assert source["m5_12_release120_source_commit"] == release120_commit
    assert source["pre_m512_source_commit"] == "77af917f4184e4061a908c68557420223434e2db"
    assert source["acc01_source_commit"] == "70fe9f7c9b14469e6ea935e75f180f26ca1c175e"
    assert source["cold_extraction_semantics_unchanged"]
    assert source["previous_source_commit"] == "9c2bfd95c65f71618f52c736dfff341953066961"
    assert source["acc01_amendment_sha256"]
    assert source["financial_source_changed"] is True
    assert source["financial_numeric_source_unchanged"] is False
    assert source["financial_rust_unchanged"] is False
    assert "src/quantbt/core/engine.py" in source["repair_changed_sources"]
    assert "rust/crates/quantbt-execution/src/target.rs" in source["repair_changed_sources"]
    assert source["historical_receipts_unchanged"] is True
    assert source["historical_guards_reexecuted"] is False
    assert source["native_artifacts_qualified"] is False
    assert source["publication"] is False
    for key, claim in (("e04", "financial_numeric_source_unchanged"), ("c02", "financial_rust_unchanged")):
        archived = source["historical_receipts"][key]
        assert archived["claim_scope"] == "historical_only"
        assert archived["source"][claim] is True
        raw = (guard.ROOT / archived["path"]).read_bytes()
        assert sha256(raw).hexdigest() == archived["sha256"]


@pytest.fixture
def current_tree(tmp_path, monkeypatch):
    sources = {
        "src/quantbt/mode5/geometry/schema.py": b"accepted pre-repair geometry\n",
        "src/quantbt/endpoint.py": b"approved repaired endpoint\n",
        "src/quantbt/unrelated.py": b"unchanged source\n",
        "rust/engine.rs": b"approved repaired Rust\n",
        "uv.lock": b"unchanged release identity\n",
    }
    for name, value in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    scopes = ("src", "rust", "uv.lock")
    expected = {name: sha256(value).hexdigest() for name, value in sources.items()}
    monkeypatch.setattr(guard, "ROOT", tmp_path)

    def git(*args):
        assert args == ("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *scopes)
        names = set(sources) | {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
        return b"".join(name.encode() + b"\0" for name in sorted(names))

    monkeypatch.setattr(guard, "_git", git)
    return tmp_path, expected, scopes


def test_exact_accepted_tree_including_legacy_geometry_is_qualified(current_tree):
    _, expected, scopes = current_tree
    guard._assert_current_sources(expected, scopes)


@pytest.mark.parametrize("name", [
    "src/quantbt/mode5/geometry/schema.py", "src/quantbt/endpoint.py",
    "src/quantbt/unrelated.py", "rust/engine.rs", "uv.lock",
])
def test_current_qualification_rejects_mutations_even_on_known_paths(current_tree, name):
    root, expected, scopes = current_tree
    path = root / name
    path.write_bytes(path.read_bytes() + b"\n# unreviewed\n")
    with pytest.raises(AssertionError, match="unreviewed current source bytes"):
        guard._assert_current_sources(expected, scopes)


def test_current_qualification_rejects_untracked_addition(current_tree):
    root, expected, scopes = current_tree
    (root / "src/quantbt/new.py").write_bytes(b"not approved\n")
    with pytest.raises(AssertionError, match="unreviewed/missing current source paths"):
        guard._assert_current_sources(expected, scopes)


def test_current_qualification_rejects_missing_source(current_tree):
    root, expected, scopes = current_tree
    (root / "src/quantbt/endpoint.py").unlink()
    with pytest.raises(AssertionError, match="missing/non-file current source"):
        guard._assert_current_sources(expected, scopes)


def test_current_qualification_rejects_symlink_even_to_identical_bytes(current_tree):
    root, expected, scopes = current_tree
    path = root / "src/quantbt/endpoint.py"
    original = path.read_bytes()
    path.unlink()
    target = root / "outside-source"
    target.write_bytes(original)
    path.symlink_to(target)
    # Keep the inventory fixed so the byte-identical symlink itself is checked.
    monkeypatch_names = b"".join(name.encode() + b"\0" for name in sorted(expected))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(guard, "_git", lambda *args: monkeypatch_names)
        with pytest.raises(AssertionError, match="missing/non-file current source"):
            guard._assert_current_sources(expected, scopes)


def test_committed_hash_inventory_uses_exact_binary_blobs(monkeypatch):
    commit = "a" * 40
    blobs = {"src/a.py": b"a\x00\r\n", "rust/b.rs": b"binary\nblob\xff"}
    oids = [b"1" * 40, b"2" * 40]

    def git(*args, input=None):
        if args == ("ls-tree", "-r", "-z", commit, "--", "src", "rust"):
            return b"".join(b"100644 blob " + oid + b"\t" + name.encode() + b"\0"
                            for name, oid in zip(blobs, oids))
        assert args == ("cat-file", "--batch")
        assert input == b"".join(oid + b"\n" for oid in oids)
        return b"".join(oid + b" blob " + str(len(value)).encode() + b"\n" + value + b"\n"
                        for oid, value in zip(oids, blobs.values()))

    monkeypatch.setattr(guard, "_git", git)
    assert guard._committed_source_hashes(commit, ["src", "rust"]) == {
        name: sha256(value).hexdigest() for name, value in blobs.items()}


@pytest.fixture
def repair_delta():
    qualification = {"baseline_commit": "a" * 40, "source_commit": "b" * 40}
    before = {"src/engine.py": "before", "src/geometry.py": "accepted"}
    after = {"src/engine.py": "after", "src/geometry.py": "accepted", "src/new.py": "new"}
    repair = {"sources": {name: {
        "before_commit": qualification["baseline_commit"], "before_sha256": before.get(name),
        "after_commit": qualification["source_commit"], "after_sha256": digest,
    } for name, digest in after.items()}}
    return repair, before, after, qualification


def test_repair_delta_requires_exact_changes_and_handles_additions(repair_delta):
    assert guard._verify_repair_delta(*repair_delta) == ["src/engine.py", "src/new.py"]


@pytest.mark.parametrize("field", ["before_commit", "after_commit", "before_sha256", "after_sha256"])
def test_repair_delta_rejects_incorrect_committed_identity(repair_delta, field):
    repair, before, after, qualification = deepcopy(repair_delta)
    repair["sources"]["src/engine.py"][field] = "incorrect"
    with pytest.raises(AssertionError, match="repair .*differs|repair .*differ"):
        guard._verify_repair_delta(repair, before, after, qualification)


def test_repair_delta_rejects_missing_amendment_entry(repair_delta):
    repair, before, after, qualification = repair_delta
    del repair["sources"]["src/engine.py"]
    with pytest.raises(AssertionError, match="unreviewed/missing committed repair changes"):
        guard._verify_repair_delta(repair, before, after, qualification)


def test_repair_delta_rejects_unreviewed_committed_change(repair_delta):
    repair, before, after, qualification = repair_delta
    after["src/unapproved.py"] = "arbitrary newer commit"
    with pytest.raises(AssertionError, match="unreviewed/missing committed repair changes"):
        guard._verify_repair_delta(repair, before, after, qualification)


def test_current_qualification_manifest_is_digest_locked(tmp_path, monkeypatch):
    path = tmp_path / "qualification.json"
    path.write_bytes(guard.QUALIFICATION.read_bytes() + b"\n")
    monkeypatch.setattr(guard, "QUALIFICATION", path)
    with pytest.raises(AssertionError, match="current qualification manifest digest"):
        guard._qualification_manifest()


def test_current_qualification_preserves_repair_manifest_digest_lock(tmp_path, monkeypatch):
    path = tmp_path / "repair.json"
    path.write_bytes(guard.MANIFEST.read_bytes() + b"\n")
    monkeypatch.setattr(guard, "MANIFEST", path)
    with pytest.raises(AssertionError, match="portfolio repair manifest digest"):
        guard.verify_current_source()


def test_current_qualification_rejects_changed_historical_receipt(tmp_path, monkeypatch):
    raw = json.dumps({"source": {"financial_numeric_source_unchanged": True}}).encode()
    qualification = {"baseline_commit": "a" * 40, "historical_receipts": {"e04": {
        "path": "receipt.json", "sha256": sha256(raw).hexdigest(), "source_key": "source"}}}
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "_blob", lambda commit, name, digest: raw)
    path = tmp_path / "receipt.json"
    path.write_bytes(raw)
    assert guard._historical_receipts(qualification)["e04"]["claim_scope"] == "historical_only"
    path.write_bytes(raw + b"\n")
    with pytest.raises(AssertionError, match="historical receipt changed"):
        guard._historical_receipts(qualification)
