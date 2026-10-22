"""Cold exact-byte guard tests; no native calls or financial execution."""

import hashlib
import json
import subprocess

import pytest

from . import source_guard as guard


MANIFEST = json.loads(guard.AMENDMENT.read_text())
SOURCES = MANIFEST["sources"]
BASELINES = [json.loads((guard.ROOT / f"docs/metrics/evidence/{phase}/baseline.json").read_text())
             for phase in ("met01", "met02")]
TRANSITIONS = [(path, change) for path, entry in SOURCES.items() for change in entry["transitions"]]


def blob(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=guard.ROOT)


@pytest.mark.parametrize("path,change", TRANSITIONS, ids=[path for path, _ in TRANSITIONS])
def test_exact_committed_before_and_after_are_admitted(path, change):
    expected = SOURCES[path]["baseline_sha256"]
    for side in ("before", "after"):
        source = blob(change[f"{side}_commit"], path)
        assert hashlib.sha256(source).hexdigest() == change[f"{side}_sha256"]
        guard.assert_protected_bytes(path, expected, source)


@pytest.mark.parametrize("path", SOURCES)
def test_original_historical_baselines_are_still_admitted(path):
    for baseline in BASELINES:
        source = blob(baseline["parent_commit"], path)
        guard.assert_protected_bytes(path, baseline["protected_sources"][path], source)


@pytest.mark.parametrize("path", SOURCES)
def test_current_source_is_exact_final_reviewed_blob(path):
    entry = SOURCES[path]
    from tools.m5_12_source_guard import verify_current_source
    current = verify_current_source()
    assert current["current_source_qualified"] and current["historical_receipts_unchanged"]
    assert (guard.ROOT / path).read_bytes() == blob(current["source_commit"], path)
    guard.assert_protected(path, entry["baseline_sha256"])


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("side", ["before", "after"])
def test_unrelated_mutations_fail_closed(path, side):
    entry = SOURCES[path]
    current = blob(entry["transitions"][-1][f"{side}_commit"], path)
    with pytest.raises(AssertionError, match="unreviewed source bytes"):
        guard.assert_protected_bytes(path, entry["baseline_sha256"], current + b"\n# unrelated mutation\n")


@pytest.mark.parametrize("path", SOURCES)
@pytest.mark.parametrize("wrong", ["different", "current"])
def test_different_or_rebased_expected_sha_is_rejected(path, wrong):
    entry = SOURCES[path]
    current = blob(entry["transitions"][-1]["after_commit"], path)
    expected = "0" * 64 if wrong == "different" else hashlib.sha256(current).hexdigest()
    with pytest.raises(AssertionError, match="amendment baseline"):
        guard.assert_protected_bytes(path, expected, current)


def test_unknown_path_has_no_amendment_admission():
    with pytest.raises(AssertionError):
        guard.assert_protected_bytes("unreviewed.py", hashlib.sha256(b"original").hexdigest(), b"changed")


def test_existing_public_mode5_stripping_is_preserved():
    path = "src/quantbt/walkforward.py"
    guard.assert_protected(path, BASELINES[0]["protected_sources"][path])
    with pytest.raises(AssertionError, match="unreviewed Mode5 public bytes"):
        guard.assert_protected_bytes(path, BASELINES[0]["protected_sources"][path],
                                     (guard.ROOT / path).read_bytes() + b"\n# mutation\n")


def test_manifest_digest_is_the_pinned_identity():
    assert hashlib.sha256(guard.AMENDMENT.read_bytes()).hexdigest() == guard.AMENDMENT_SHA256
    assert guard.source_amendment() == MANIFEST


@pytest.mark.parametrize("field", ["identity", "schema", "sources"])
def test_manifest_mutations_fail_closed(tmp_path, monkeypatch, field):
    altered = dict(MANIFEST, **{field: "unreviewed"})
    path = tmp_path / "amendment.json"
    path.write_text(json.dumps(altered))
    monkeypatch.setattr(guard, "AMENDMENT", path)
    with pytest.raises(AssertionError, match="source amendment digest"):
        guard.source_amendment()


def test_amendment_identity_is_checked_even_with_a_matching_digest(tmp_path, monkeypatch):
    path = tmp_path / "amendment.json"
    path.write_text(json.dumps(dict(MANIFEST, identity="different-amendment")))
    monkeypatch.setattr(guard, "AMENDMENT", path)
    monkeypatch.setattr(guard, "AMENDMENT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(AssertionError, match="source amendment identity"):
        guard.source_amendment()


def test_stale_commit_blob_hash_fails_closed(monkeypatch):
    manifest = json.loads(guard.AMENDMENT.read_text())
    path = next(iter(SOURCES))
    manifest["sources"][path]["transitions"][0]["after_sha256"] = "0" * 64
    monkeypatch.setattr(guard, "source_amendment", lambda: manifest)
    with pytest.raises(AssertionError, match="amendment blob"):
        guard.assert_protected(path, SOURCES[path]["baseline_sha256"])


def test_different_commit_reference_fails_closed(monkeypatch):
    manifest = json.loads(guard.AMENDMENT.read_text())
    path = next(iter(SOURCES))
    manifest["sources"][path]["transitions"][0]["after_commit"] = SOURCES[path]["baseline_commit"]
    monkeypatch.setattr(guard, "source_amendment", lambda: manifest)
    with pytest.raises(AssertionError, match="amendment blob"):
        guard.assert_protected(path, SOURCES[path]["baseline_sha256"])


def test_missing_git_object_is_not_an_admission(monkeypatch):
    manifest = json.loads(guard.AMENDMENT.read_text())
    path = next(iter(SOURCES))
    manifest["sources"][path]["transitions"][0]["after_commit"] = "0" * 40
    monkeypatch.setattr(guard, "source_amendment", lambda: manifest)
    with pytest.raises(subprocess.CalledProcessError):
        guard.assert_protected(path, SOURCES[path]["baseline_sha256"])
