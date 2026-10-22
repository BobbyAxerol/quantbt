import subprocess

import pytest

from tools import qms_pre05_qualification as gate


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    path = tmp_path / ".maturin/qms08/pre-e06-05"
    (path / "mpl-cache").mkdir(parents=True)
    return path


def test_only_reviewed_font_cache_removed_and_evidence_preserved(lane):
    cache = lane / "mpl-cache/fontlist-v390.json"
    cache.write_text("{}")
    evidence = lane / "raw-evidence.json"
    evidence.write_text("do not remove")
    expected = gate.file_hash(evidence)
    receipt = gate.cleanup_snapshot(lane, [evidence])
    assert receipt["status"] == "PASS_REVIEWED_FONT_CACHE_ONLY"
    assert receipt["deleted_paths"] == [str(cache)]
    assert not cache.exists()
    assert gate.file_hash(evidence) == expected
    assert receipt["protected_before_after_equal"]
    assert receipt["task_attributed_reclaimed_bytes"] is None


@pytest.mark.parametrize("bad", ("unexpected", "symlink"))
def test_unknown_or_symlinked_cache_is_not_deleted(lane, bad):
    protected = lane / "raw-evidence.json"
    protected.write_text("do not remove")
    if bad == "unexpected":
        (lane / "mpl-cache/unreviewed.json").write_text("keep")
    else:
        (lane / "mpl-cache/fontlist-v390.json").symlink_to(protected)
    with pytest.raises(ValueError, match="unreviewed"):
        gate.cleanup_snapshot(lane, [protected])
    assert protected.read_text() == "do not remove"
