"""Phase 55A release-candidate packaging locks.

These checks intentionally validate package metadata and wheel boundaries only;
they do not repeat the already-certified execution-domain corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
import tomllib
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _native_versions() -> tuple[str, str]:
    registry = json.loads((ROOT / "contracts" / "native_event_product_registry.json").read_text())
    versions = registry["versions"]
    return str(versions["core_package"]["version"]), str(versions["native_package"]["version"])


def _write_native_wheel(path: Path, *, version: str, python_tag: str = "cp312") -> None:
    dist_info = f"quantbt_native-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("_quantbt_native/__init__.py", "")
        archive.writestr(
            f"_quantbt_native/_quantbt_native.{python_tag}-x86_64-linux-gnu.so", b"native"
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.4\nName: quantbt-native\nVersion: {version}\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
            f"Tag: {python_tag}-{python_tag}-manylinux_2_17_x86_64\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")


def _write_core_wheel(path: Path, *, core_version: str, native_version: str) -> None:
    dist_info = f"quantbt_engine-{core_version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: quantbt-engine\n"
            f"Version: {core_version}\n"
            "Requires-Dist: "
            f"quantbt-native=={native_version}; sys_platform == \"linux\" and "
            "platform_machine == \"x86_64\" and implementation_name == \"cpython\" and "
            "python_version >= \"3.11\" and python_version < \"3.14\"\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")


def test_phase55a_core_declares_exact_linux_native_dependency() -> None:
    core = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    core_version, native_version = _native_versions()
    requirement = next(item for item in core["project"]["dependencies"] if item.startswith("quantbt-native=="))

    assert core["project"]["version"] == core_version == "1.0.10"
    assert requirement.startswith(f"quantbt-native=={native_version};")
    for marker in ("sys_platform == 'linux'", "platform_machine == 'x86_64'", "implementation_name == 'cpython'"):
        assert marker in requirement
    assert core["project"]["optional-dependencies"]["native"] == []
    assert core["tool"]["uv"]["sources"]["quantbt-native"] == {"path": "rust/native_event"}


def test_phase55a_native_metadata_and_registry_are_exact_release_candidate_pair() -> None:
    registry = json.loads((ROOT / "contracts" / "native_event_product_registry.json").read_text())
    native_pyproject = tomllib.loads((ROOT / "rust" / "native_event" / "pyproject.toml").read_text())
    cargo = tomllib.loads((ROOT / "rust" / "native_event" / "Cargo.toml").read_text())
    core_version, native_version = _native_versions()

    assert native_pyproject["project"]["version"] == native_version == "0.4.1"
    assert cargo["package"]["version"] == native_version
    assert registry["versions"]["native_package"]["published"] is False
    assert registry["versions"]["native_package"]["release_policy"] == "public_linux_wheel_candidate_phase55a"
    assert registry["compatibility"] == [
        {
            "command_abis": ["full-command-v1"],
            "core_version": core_version,
            "fallback": "explicit_rust_fails_fast; auto_routes_certified_static_ir_or_python_with_reason",
            "native_protocol_max": 1,
            "native_protocol_min": 1,
            "native_version": native_version,
            "result_abis": ["native-event-result-v1"],
            "status": "exact_staged_pair",
        }
    ]


def test_phase55a_native_wheel_contract_accepts_exact_manylinux_artifact(tmp_path: Path) -> None:
    from tools.check_native_wheels import inspect_native_wheels

    core_version, native_version = _native_versions()
    wheel = tmp_path / f"quantbt_native-{native_version}-cp312-cp312-manylinux_2_17_x86_64.whl"
    _write_native_wheel(wheel, version=native_version)
    core_wheel = tmp_path / f"quantbt_engine-{core_version}-py3-none-any.whl"
    _write_core_wheel(core_wheel, core_version=core_version, native_version=native_version)

    report = inspect_native_wheels(tmp_path, expected_python_version="3.12", core_wheel=core_wheel)
    assert report["wheel_only"] is True
    assert report["manylinux_x86_64"] is True
    assert report["observed_python_tags"] == ["cp312"]
    assert report["core_native_dependency"]["native_version"] == native_version


def test_phase55a_native_wheel_contract_rejects_source_distribution(tmp_path: Path) -> None:
    from tools.check_native_wheels import inspect_native_wheels

    _, native_version = _native_versions()
    _write_native_wheel(
        tmp_path / f"quantbt_native-{native_version}-cp312-cp312-manylinux_2_17_x86_64.whl",
        version=native_version,
    )
    (tmp_path / f"quantbt_native-{native_version}.tar.gz").write_bytes(b"forbidden")

    with pytest.raises(ValueError, match="source distributions are forbidden"):
        inspect_native_wheels(tmp_path, expected_python_version="3.12")


def test_phase55a_native_wheel_contract_rejects_non_manylinux_tag(tmp_path: Path) -> None:
    from tools.check_native_wheels import inspect_native_wheels

    _, native_version = _native_versions()
    _write_native_wheel(
        tmp_path / f"quantbt_native-{native_version}-cp312-cp312-linux_x86_64.whl",
        version=native_version,
    )

    with pytest.raises(ValueError, match="missing manylinux"):
        inspect_native_wheels(tmp_path, expected_python_version="3.12")


def test_phase55a_native_release_workflow_builds_one_wheel_only_artifact_per_cpython() -> None:
    workflow = (ROOT / ".github" / "workflows" / "native-release.yml").read_text(encoding="utf-8")
    assert 'python-version: ["3.11", "3.12", "3.13"]' in workflow
    assert 'manylinux: "2014"' in workflow
    assert "tools/check_native_wheels.py" in workflow
    assert "native-wheel-cpython-" in workflow
