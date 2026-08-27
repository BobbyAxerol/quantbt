"""Release-channel policy locks for the public native/core package pair."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_release_channel_policy_requires_dev_rc_for_testpypi_and_main_final_for_pypi() -> None:
    from tools.check_release_channel import resolve_channel, validate_release_channel

    assert resolve_channel("auto", "v1.0.11rc1") == "testpypi"
    assert resolve_channel("auto", "v1.0.10") == "pypi"

    assert validate_release_channel(
        "testpypi", "v1.0.11rc1", release_commit="dev-sha", branch_commit="dev-sha"
    )["branch"] == "dev"
    assert validate_release_channel(
        "pypi", "v1.0.10", release_commit="main-sha", branch_commit="main-sha"
    )["branch"] == "main"

    with pytest.raises(ValueError, match="RC tag from dev"):
        validate_release_channel("testpypi", "v1.0.10", release_commit="sha", branch_commit="sha")
    with pytest.raises(ValueError, match="final non-RC tag from main"):
        validate_release_channel("pypi", "v1.0.11rc1", release_commit="sha", branch_commit="sha")
    with pytest.raises(ValueError, match="origin/main tip"):
        validate_release_channel("pypi", "v1.0.10", release_commit="old", branch_commit="main")


def test_release_workflows_invoke_the_channel_guard() -> None:
    for relative in (
        ".github/workflows/native-release.yml",
        ".github/workflows/publish-native.yml",
        ".github/workflows/publish-testpypi.yml",
        ".github/workflows/publish.yml",
    ):
        assert "tools/check_release_channel.py" in (ROOT / relative).read_text(encoding="utf-8")


def test_release_documentation_keeps_rc_and_final_channels_distinct() -> None:
    release_document = (ROOT / "docs" / "release_packaging.md").read_text(encoding="utf-8")

    assert "`vX.Y.ZrcN` at the exact current `dev` tip" in release_document
    assert "final `vX.Y.Z` at the exact current `main` tip" in release_document
    assert "Do not tag from `dev`." not in release_document
