"""Artifact, privacy and cleanup gates must reject unqualified handoffs."""

from copy import deepcopy

import pytest

from tools import qms_e07_closure as closure
from tools.qms_pre06_contract import EXTENSION_SHA


def identity():
    return dict(core="1.1.2", native="0.4.3", modules=260, native_sha256=EXTENSION_SHA,
                core_origin="/tmp/e07/lib/python3.12/site-packages/quantbt/__init__.py")


def test_e07_exact_installed_identity():
    assert closure.installed_identity(identity()) == identity()


@pytest.mark.parametrize("key,value", (("core", "1.1.1"), ("native", "0.4.2"),
    ("modules", 259), ("native_sha256", "wrong"), ("core_origin", "/tmp/src/quantbt/__init__.py")))
def test_e07_wrong_artifact_or_checkout_runtime_rejected(key, value):
    changed = deepcopy(identity())
    changed[key] = value
    with pytest.raises(ValueError, match="runtime identity"):
        closure.installed_identity(changed)


def test_e07_cleanup_unknown_root_rejected():
    with pytest.raises(ValueError, match="unreviewed"):
        closure.scratch("../g01-package-v1")


def test_e07_cleanup_symlink_root_rejected(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / "wheel-consumer").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(closure, "LANE", lane)
    with pytest.raises(ValueError, match="symlinked"):
        closure.scratch("wheel-consumer")
    assert outside.is_dir()


def test_e07_cleanup_active_consumer_never_removed(tmp_path, monkeypatch):
    roots = {name: tmp_path / name for name in closure.CLEANABLE}
    for path in roots.values():
        path.mkdir(parents=True)
    monkeypatch.setattr(closure, "LANE", tmp_path)
    monkeypatch.setattr(closure, "scratch", roots.__getitem__)
    monkeypatch.setattr(closure.subprocess, "check_output",
                        lambda *a, **kw: str(roots["wheel-consumer"] / "bin/python"))
    with pytest.raises(ValueError, match="still used"):
        closure.cleanup({})
    assert all(path.is_dir() for path in roots.values())


@pytest.mark.parametrize("private", ("alpha", "token"))
def test_e07_public_patch_rejects_private_material(private, monkeypatch):
    material = ("/root/bobby/pool_alpha/"+"alphas_storage/private.py") if private == "alpha" else "pypi-"+"x"*35

    def output(args, **kwargs):
        if args[:3] == ["git", "diff", "--name-only"]:
            return "docs/e07-fixture.md\n"
        if args[:2] == ["git", "ls-files"]:
            return ""
        return "diff fixture\n+"+material

    monkeypatch.setattr(closure.subprocess, "check_output", output)
    with pytest.raises(ValueError, match="private path or credential"):
        closure.privacy()


def test_e07_closure_bound_to_registered_source_and_native():
    registered = closure.check_registration()
    assert len(registered["runtime_sha256"]) == 322
    assert closure.artifacts(registered)["wheel"]["modules"] == 260
    assert registered["native"]["extension_sha256"] == EXTENSION_SHA


def test_e07_public_grid_example_fits_mature_history_without_private_inputs():
    from examples.wfo_meta_reactive_grid import run
    value = run("active")
    assert value["folds"] == value["observed_revisions"] == 26
    assert value["fit_count"] > 0 and len(value["params_by_fold"]) == 26
    assert not value["continuous_equity_available"] and not value["economic_promotion"]
