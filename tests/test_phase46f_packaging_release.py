from __future__ import annotations

from pathlib import Path
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _event_block(payload: dict) -> dict:
    return payload.get("on", payload.get(True, {}))


def test_phase46f_core_metadata_and_release_notes_are_complete() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["name"] == "quantbt-engine"
    assert project["version"] == "0.1.0"
    assert {"3.11", "3.12", "3.13"} <= {
        classifier.rsplit(" :: ", 1)[-1]
        for classifier in project["classifiers"]
        if classifier.startswith("Programming Language :: Python :: 3.")
    }
    assert project["urls"]["Documentation"].endswith("/docs")
    assert project["urls"]["Changelog"].endswith("/CHANGELOG.md")
    assert (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").find("[0.1.0]") >= 0
    assert metadata["project"]["optional-dependencies"]["native"] == []


def test_phase46f_testpypi_workflow_is_manual_and_oidc_protected() -> None:
    payload = _load_yaml(PROJECT_ROOT / ".github" / "workflows" / "publish-testpypi.yml")
    events = _event_block(payload)
    assert "workflow_dispatch" in events
    assert "ref" in events["workflow_dispatch"]["inputs"]

    publish = payload["jobs"]["publish"]
    assert publish["environment"]["name"] == "testpypi"
    assert publish["permissions"]["id-token"] == "write"
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "publish-testpypi.yml").read_text(
        encoding="utf-8"
    )
    assert "https://test.pypi.org/legacy/" in workflow_text
    assert "PYPI_API_TOKEN" not in workflow_text
    assert "tools/check_release_version.py" in workflow_text


def test_phase46f_production_publish_rejects_prereleases() -> None:
    payload = _load_yaml(PROJECT_ROOT / ".github" / "workflows" / "publish.yml")
    assert _event_block(payload) == {"release": {"types": ["published"]}}
    assert "github.event.release.prerelease" in payload["jobs"]["publish"]["if"]
    assert "github.event.release.draft" in payload["jobs"]["publish"]["if"]


def test_phase46f_native_extra_is_not_claimed_as_a_core_dependency() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = metadata["project"]["dependencies"]
    all_extra = metadata["project"]["optional-dependencies"]["all"]
    assert not any("quantbt-native" in item for item in dependencies + all_extra)
    assert metadata["project"]["optional-dependencies"]["native"] == []
