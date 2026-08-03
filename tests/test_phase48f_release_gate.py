from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib
import zipfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    payload = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def _load_yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _event_block(payload: dict) -> dict:
    return payload.get("on", payload.get(True, {}))


def test_phase48f_testpypi_workflow_has_pre_upload_clean_artifact_gate() -> None:
    path = PROJECT_ROOT / ".github/workflows/publish-testpypi.yml"
    payload = _load_yaml(path)
    events = _event_block(payload)
    assert "workflow_dispatch" in events
    assert events["push"]["tags"] == ["v*rc*"]
    text = path.read_text(encoding="utf-8")
    for expected in (
        "pip install dist/quantbt_engine-*.whl",
        "pip install dist/quantbt_engine-*.tar.gz",
        "pip check",
        'tools/check_release_artifacts.py" --dist "$GITHUB_WORKSPACE/dist',
        "tools/create_release_manifest.py",
        "uv run twine check --strict dist/*",
    ):
        assert expected in text
    assert "gh-action-pypi-publish" in text
    assert "PYPI_API_TOKEN" not in text
    assert payload["jobs"]["publish"]["environment"]["name"] == "testpypi"
    assert payload["jobs"]["publish"]["permissions"]["id-token"] == "write"
    assert "inputs.ref || github.ref_name" in text


def test_phase48f_production_workflow_is_release_only_and_manifested() -> None:
    path = PROJECT_ROOT / ".github/workflows/publish.yml"
    payload = _load_yaml(path)
    assert _event_block(payload) == {"release": {"types": ["published"]}}
    text = path.read_text(encoding="utf-8")
    assert "tools/create_release_manifest.py" in text
    assert "github.event.release.prerelease" in str(payload["jobs"]["publish"]["if"])
    assert "github.event.release.draft" in str(payload["jobs"]["publish"]["if"])
    assert payload["jobs"]["publish"]["environment"]["name"] == "pypi"
    assert payload["jobs"]["publish"]["permissions"]["id-token"] == "write"


def test_phase48f_release_manifest_contains_sha_and_backend_policy(tmp_path: Path) -> None:
    version = _project_version()
    artifact = tmp_path / f"quantbt_engine-{version}-py3-none-any.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("quantbt/__init__.py", f"__version__ = '{version}'\n")
        archive.writestr(f"quantbt_engine-{version}.dist-info/METADATA", "Name: quantbt-engine\n")
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact.rename(dist / artifact.name)
    sdist = dist / f"quantbt_engine-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo(f"quantbt_engine-{version}/pyproject.toml")
        payload = (
            "[project]\nname = 'quantbt-engine'\nversion = "
            f"'{version}'\n"
        ).encode()
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools.create_release_manifest import build_manifest

    manifest = build_manifest(dist)
    assert manifest["schema"] == "quantbt-release-manifest-v1"
    assert manifest["distribution"] == "quantbt-engine"
    assert manifest["version"] == version
    assert len(manifest["git_sha"]) == 40
    assert {item["kind"] for item in manifest["artifacts"]} == {"wheel", "sdist"}
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert manifest["backend_policy"] == {
        "auto": "python",
        "native_extra": "empty",
        "rust": "explicit_experimental",
    }

    (dist / "quantbt_engine-0.0.0-py3-none-any.whl").write_bytes(b"wrong version")
    with pytest.raises(RuntimeError, match="does not match"):
        build_manifest(dist)


def test_phase48f_release_manifest_allows_detached_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import create_release_manifest

    calls = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        if args[1:3] == ["symbolic-ref", "--short"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[1:] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", "")
        raise AssertionError(args)

    monkeypatch.setattr(create_release_manifest.subprocess, "run", fake_run)

    version = _project_version()
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / f"quantbt_engine-{version}-py3-none-any.whl", "w"):
        pass
    with tarfile.open(dist / f"quantbt_engine-{version}.tar.gz", "w:gz"):
        pass

    manifest = create_release_manifest.build_manifest(dist)

    assert manifest["git_sha"] == "a" * 40
    assert manifest["git_ref"] is None
    assert any(call[1] == "symbolic-ref" for call in calls)


def test_phase48f_archive_gate_rejects_private_and_build_members(tmp_path: Path) -> None:
    from tools.check_release_artifacts import inspect_artifact

    version = _project_version()
    wheel = tmp_path / f"quantbt_engine-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("quantbt/__init__.py", "")
        archive.writestr(f"quantbt_engine-{version}.dist-info/METADATA", "")
        archive.writestr("quantbt/.env", "PYPI_TOKEN=pypi-" + "A" * 40)
        archive.writestr("quantbt/local.prof", "profile")
    findings = inspect_artifact(wheel)
    assert any("secret-like archive path" in finding for finding in findings)
    assert any("build/profiling artifact" in finding for finding in findings)
    assert any("credential-like content" in finding for finding in findings)

    sdist = tmp_path / f"quantbt_engine-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo(f"quantbt_engine-{version}/data/private/secret.csv")
        payload = b"profile"
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    findings = inspect_artifact(sdist)
    assert any("private/local archive path" in finding for finding in findings)


def test_phase48f_version_gate_is_exact_for_current_release() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    script = PROJECT_ROOT / "tools/check_release_version.py"
    accepted = subprocess.run(
        [sys.executable, str(script)],
        cwd=PROJECT_ROOT,
        env={"GITHUB_REF_NAME": f"v{version}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
