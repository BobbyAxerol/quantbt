from __future__ import annotations

import json
from pathlib import Path
import re
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
    assert project["version"].startswith("1.")
    assert {"3.11", "3.12", "3.13"} <= {
        classifier.rsplit(" :: ", 1)[-1]
        for classifier in project["classifiers"]
        if classifier.startswith("Programming Language :: Python :: 3.")
    }
    assert project["urls"]["Documentation"].endswith("/docs")
    assert project["urls"]["Changelog"].endswith("/CHANGELOG.md")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = dict(re.findall(r"^## \[([^\]]+)\](?: - \d{4}-\d{2}-\d{2})?\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S))
    registry = json.loads((PROJECT_ROOT / "contracts/native_event_product_registry.json").read_text(encoding="utf-8"))
    native_version = registry["versions"]["native_package"]["version"]
    readme = (PROJECT_ROOT / project["readme"]).read_text(encoding="utf-8")
    pair = readme.split("Release pair declared by this source revision:", 1)[1].split("Optional features:", 1)[0]
    declared_versions = dict(re.findall(r"^\| `(quantbt-(?:engine|native))` \| `([^`]+)` \|", pair, re.M))
    assert declared_versions == {"quantbt-engine": project["version"], "quantbt-native": native_version}
    release_notes = sections[project["version"]]
    assert f"### Core {project['version']} / Native {native_version}\n" in release_notes
    assert "Local qualification alone is not evidence of publication." in pair
    assert "## [1.1.1]" in changelog
    assert "Historical1.1.2receipts retain their original scope" in release_notes
    assert metadata["project"]["optional-dependencies"]["native"] == []


def test_phase46f_testpypi_workflow_has_manual_and_rc_tag_oidc_paths() -> None:
    payload = _load_yaml(PROJECT_ROOT / ".github" / "workflows" / "publish-testpypi.yml")
    events = _event_block(payload)
    assert "workflow_dispatch" in events
    assert events["push"]["tags"] == ["v*rc*"]
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
    assert "inputs.ref || github.ref_name" in workflow_text


def test_phase46f_production_publish_rejects_prereleases() -> None:
    payload = _load_yaml(PROJECT_ROOT / ".github" / "workflows" / "publish.yml")
    assert _event_block(payload) == {"release": {"types": ["published"]}}
    assert "github.event.release.prerelease" in payload["jobs"]["publish"]["if"]
    assert "github.event.release.draft" in payload["jobs"]["publish"]["if"]


def test_phase55a_linux_native_companion_is_an_exact_core_dependency() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    registry = json.loads(
        (PROJECT_ROOT / "contracts" / "native_event_product_registry.json").read_text(encoding="utf-8")
    )
    native_version = str(registry["versions"]["native_package"]["version"])
    dependencies = metadata["project"]["dependencies"]
    native_dependency = next(item for item in dependencies if item.startswith("quantbt-native=="))
    assert native_dependency.startswith(f"quantbt-native=={native_version};")
    assert "sys_platform == 'linux'" in native_dependency
    assert "platform_machine == 'x86_64'" in native_dependency
    assert "implementation_name == 'cpython'" in native_dependency
    assert metadata["project"]["optional-dependencies"]["native"] == []
