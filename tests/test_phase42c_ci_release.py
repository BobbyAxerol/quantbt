from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _event_block(payload: dict) -> dict:
    # YAML 1.1 treats the key "on" as a boolean. PyYAML still follows that
    # behavior, while GitHub Actions treats it as a string.
    return payload.get("on", payload.get(True, {}))


def test_phase42c_ci_uses_uv_matrix_and_installed_package_smoke() -> None:
    payload = _load_yaml(PROJECT_ROOT / ".github" / "workflows" / "ci.yml")

    versions = payload["jobs"]["package"]["strategy"]["matrix"]["python-version"]
    assert versions == ["3.11", "3.12", "3.13"]

    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv sync --all-extras --dev" in workflow_text
    assert "uv run pytest -q" in workflow_text
    assert "uv build" in workflow_text
    assert "pip install dist/quantbt_engine-*.whl" in workflow_text
    assert "from quantbt import QuantBTEndpoint" in workflow_text
    assert "PYTHONPATH" not in workflow_text


def test_phase42c_publish_requires_release_event_oidc_and_pypi_environment() -> None:
    payload = _load_yaml(PROJECT_ROOT / ".github" / "workflows" / "publish.yml")

    events = _event_block(payload)
    assert events == {"release": {"types": ["published"]}}

    publish_job = payload["jobs"]["publish"]
    assert publish_job["environment"]["name"] == "pypi"
    assert publish_job["permissions"]["id-token"] == "write"
    assert publish_job["permissions"]["contents"] == "read"

    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "gh-action-pypi-publish" in workflow_text
    assert "PYPI_API_TOKEN" not in workflow_text


def test_phase42c_version_gate_accepts_matching_tag_and_rejects_mismatch() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    script = PROJECT_ROOT / "tools" / "check_release_version.py"

    env = {**os.environ, "GITHUB_REF_NAME": f"v{version}"}
    accepted = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr

    env = {**os.environ, "GITHUB_REF_NAME": f"v{version}.broken"}
    rejected = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, check=False)
    assert rejected.returncode == 1
    assert "release tag mismatch" in rejected.stderr
