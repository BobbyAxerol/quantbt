"""Local closure must never remove unknown or active environments."""

import pytest

from tools import qms_e08_closure as closure


def test_e08_unknown_scratch_is_rejected():
    with pytest.raises(ValueError, match="unreviewed"):
        closure.scratch("../g01-package-v1/consumer")


def test_e08_symlink_scratch_is_rejected(tmp_path, monkeypatch):
    outside = tmp_path/"outside"
    outside.mkdir()
    package = tmp_path/"package"
    package.mkdir()
    (package/"pair").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(closure, "PACKAGE", package)
    with pytest.raises(ValueError, match="symlinked"):
        closure.scratch("pair")
    assert outside.is_dir()


def test_e08_non_consumer_directory_is_rejected(tmp_path, monkeypatch):
    (tmp_path/"pair").mkdir()
    monkeypatch.setattr(closure, "PACKAGE", tmp_path)
    monkeypatch.setattr(closure.subprocess, "run", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="identity missing"):
        closure.scratch("pair")


def test_e08_active_consumers_are_never_removed(tmp_path, monkeypatch):
    roots = {name: tmp_path/name for name in closure.CLEANABLE}
    for path in roots.values():
        path.mkdir(parents=True)
    monkeypatch.setattr(closure, "scratch", roots.__getitem__)
    monkeypatch.setattr(closure.subprocess, "check_output", lambda *a, **kw: str(roots["pair"]/"bin/python"))
    with pytest.raises(ValueError, match="still in use"):
        closure.cleanup()
    assert all(path.exists() for path in roots.values())
