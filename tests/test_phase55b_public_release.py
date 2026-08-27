"""Phase 55B public native-release automation and Poetry-consumer locks.

The real index proof intentionally runs only after immutable TestPyPI/PyPI
artifacts exist. These fast tests keep its release order, isolated consumer
shape, and fail-closed route assertions from drifting before that handoff.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _event_block(payload: dict) -> dict:
    # PyYAML 1.1 treats GitHub's ``on`` key as a boolean.
    return payload.get("on", payload.get(True, {}))


def test_phase55b_native_publish_workflow_builds_complete_manylinux_matrix_before_oidc_upload() -> None:
    path = ROOT / ".github" / "workflows" / "publish-native.yml"
    payload = _load_yaml(path)
    events = _event_block(payload)
    assert set(events) == {"workflow_dispatch"}
    inputs = events["workflow_dispatch"]["inputs"]
    assert inputs["ref"]["required"] is True
    assert inputs["index"]["options"] == ["testpypi", "pypi"]

    build = payload["jobs"]["build-native"]
    assert build["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
    text = path.read_text(encoding="utf-8")
    for expected in (
        'manylinux: "2014"',
        "tools/check_native_wheels.py",
        "--require-full-matrix",
        "tools/certify_native_release.py",
        "packages-dir: dist/native",
        "gh-action-pypi-publish",
    ):
        assert expected in text
    assert "PYPI_API_TOKEN" not in text

    test_upload = payload["jobs"]["publish-testpypi"]
    prod_upload = payload["jobs"]["publish-pypi"]
    assert test_upload["environment"]["name"] == "testpypi"
    assert prod_upload["environment"]["name"] == "pypi"
    assert test_upload["permissions"]["id-token"] == "write"
    assert prod_upload["permissions"]["id-token"] == "write"


def test_phase55b_public_consumer_workflow_isolated_to_supported_linux_matrix() -> None:
    path = ROOT / ".github" / "workflows" / "public-native-consumer.yml"
    payload = _load_yaml(path)
    events = _event_block(payload)
    assert set(events) == {"workflow_dispatch"}
    matrix = payload["jobs"]["poetry-consumer"]["strategy"]["matrix"]
    assert matrix["runner"] == ["ubuntu-22.04", "ubuntu-24.04"]
    assert matrix["python-version"] == ["3.11", "3.12", "3.13"]
    text = path.read_text(encoding="utf-8")
    assert "pipx install \"poetry==2.3.4\"" in text
    assert "tools/verify_public_native_consumer.py" in text
    assert "public-native-consumer-" in text


def test_phase55b_workflow_dispatch_version_checks_scope_the_requested_tag_to_the_process() -> None:
    """Dispatch runs start from a branch, so protected GitHub env vars cannot be overridden via YAML ``env``."""

    native_publish = (ROOT / ".github" / "workflows" / "publish-native.yml").read_text(encoding="utf-8")
    native_certification = (ROOT / ".github" / "workflows" / "native-release.yml").read_text(encoding="utf-8")
    testpypi = (ROOT / ".github" / "workflows" / "publish-testpypi.yml").read_text(encoding="utf-8")
    consumer = (ROOT / ".github" / "workflows" / "public-native-consumer.yml").read_text(encoding="utf-8")

    assert 'GITHUB_REF_NAME="${{ inputs.ref }}" python tools/check_release_version.py' in native_publish
    assert 'GITHUB_REF_NAME="${{ inputs.ref }}" .venv/bin/python tools/check_release_version.py' in native_publish
    assert 'GITHUB_REF_NAME="${{ inputs.ref || github.ref_name }}" .venv/bin/python tools/check_release_version.py' in native_certification
    assert 'GITHUB_REF_NAME="${{ inputs.ref || github.ref_name }}" uv run python tools/check_release_version.py' in testpypi
    assert 'GITHUB_REF_NAME="${{ inputs.ref }}" python tools/check_release_version.py' in consumer


def test_phase55b_core_ci_builds_the_native_smoke_wheel_with_the_release_builder() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "PyO3/maturin-action@v1" in text
    assert "--manifest-path rust/native_event/Cargo.toml" in text
    assert '--interpreter python${{ matrix.python-version }}' in text
    assert "--out native-smoke" in text
    assert "native-smoke/quantbt_native-*.whl" in text
    assert 'manylinux: "2014"' in text
    assert "pip wheel --no-deps --wheel-dir" not in text
    assert "tools/verify_wheels.py --dist dist --skip-install" in text
    assert text.index("Verify source-to-wheel module parity") < text.index(
        "Build local native companion for dependency smoke"
    )


def test_phase55b_consumer_tool_keeps_the_normal_poetry_add_contract(monkeypatch) -> None:
    from tools import verify_public_native_consumer as consumer

    spec = consumer.ConsumerProofSpec(
        index="testpypi",
        core_version="1.1.0",
        native_version="0.4.1",
        poetry="poetry",
        python=Path("/usr/bin/python3"),
        timeout_seconds=30,
    )
    commands = consumer.poetry_install_commands(spec)
    assert ("poetry", "add", "quantbt-engine", "--no-interaction", "--no-ansi") in commands
    assert any(command[1:3] == ("source", "add") and "testpypi" in command for command in commands)
    assert any(command[1:3] == ("source", "add") and "PyPI" in command for command in commands)

    seen: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        command = tuple(command)
        seen.append(command)
        if command[1:3] == ("show", "quantbt-engine"):
            return "quantbt-engine 1.1.0"
        if command[1:3] == ("show", "quantbt-native"):
            return "quantbt-native 0.4.1"
        if command[1:3] == ("run", "python"):
            return json.dumps(
                {
                    "core_version": "1.1.0",
                    "native_version": "0.4.1",
                    "automatic_backend": "rust",
                    "explicit_disable_fails_closed": True,
                }
            )
        return ""

    monkeypatch.setattr(consumer, "_run", fake_run)
    report = consumer.run_consumer_proof(spec)
    assert report["requested_command"] == "poetry add quantbt-engine"
    assert report["probe"]["automatic_backend"] == "rust"
    assert any(command[1:3] == ("add", "quantbt-engine") for command in seen)

    probe = consumer.public_probe_script("1.1.0", "0.4.1")
    for expected in (
        "automatic.resolved == \"rust\"",
        "forced_python.resolved == \"python\"",
        "emergency_native_disabled",
        "explicit Rust unexpectedly fell back",
        "execution[\"backend\"] == \"rust\"",
    ):
        assert expected in probe


def test_phase55b_release_docs_describe_native_first_then_core_and_public_consumer_proof() -> None:
    for relative in (
        "docs/testpypi_release_checklist.md",
        "docs/migration/native_release_handoff.md",
        "docs/native/install.md",
        "docs/release_packaging.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "quantbt-native==0.4.1" in text
        assert "poetry add quantbt-engine" in text
    checklist = (ROOT / "docs" / "testpypi_release_checklist.md").read_text(encoding="utf-8")
    assert "Publish quantbt-native" in checklist
    assert "Public Native Consumer Proof" in checklist
    assert "Publish quantbt-engine" in checklist
