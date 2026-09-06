"""Release-contract locks for the Phase 54B.4 native handoff.

These tests intentionally inspect only deterministic repository artifacts.
The expensive clean-wheel behavior is exercised by ``certify_native_release``
locally and by the tagged release workflow.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[3]


def _declared_product_versions() -> tuple[str, str]:
    registry = json.loads((ROOT / "contracts" / "native_event_product_registry.json").read_text())
    versions = registry["versions"]
    return (
        str(versions["core_package"]["version"]),
        str(versions["native_package"]["version"]),
    )


def _write_core_artifacts(dist: Path, core_version: str) -> None:
    """Create structurally sufficient artifacts for manifest-only tests."""

    with zipfile.ZipFile(dist / f"quantbt_engine-{core_version}-py3-none-any.whl", "w"):
        pass
    with tarfile.open(dist / f"quantbt_engine-{core_version}.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo(f"quantbt_engine-{core_version}/pyproject.toml")
        payload = f"[project]\nname = 'quantbt-engine'\nversion = '{core_version}'\n".encode()
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def test_phase54b4_deletion_manifest_retains_every_compatibility_surface() -> None:
    from tools.check_native_release_handoff import validate_migration_audit

    assert validate_migration_audit() == []
    payload = json.loads(
        (ROOT / "contracts" / "native_event_deletion_manifest.json").read_text(encoding="utf-8")
    )
    root = next(item for item in payload["candidates"] if item["id"] == "root_python_mirror")
    assert root["state"] == "retained"
    assert root["deletion_approved"] is False
    assert {"__init__.py", "endpoint.py", "walkforward.py", "backends", "core"}.issubset(
        root["paths"]
    )
    assert root["replacement_paths"] == ["src/quantbt"]
    assert all(item["deletion_approved"] is False for item in payload["candidates"])


def test_phase54b4_release_manifest_derives_native_surface_from_registry(tmp_path: Path) -> None:
    from tools.create_release_manifest import build_manifest

    dist = tmp_path / "dist"
    dist.mkdir()
    core_version, native_version = _declared_product_versions()
    _write_core_artifacts(dist, core_version)
    with zipfile.ZipFile(
        dist / f"quantbt_native-{native_version}-cp312-cp312-manylinux_2_17_x86_64.whl", "w"
    ):
        pass

    surface = build_manifest(dist)["native_product_surface"]
    assert surface["core_only_auto_backend"] == "python"
    assert surface["native_companion_published"] is True
    assert surface["supported_linux_auto_backend"] == "python_explicit_rust_only"
    assert surface["automatic_rust_workloads_with_exact_companion"] == []
    assert set(surface["explicit_certified_native_workloads"]) == {
        "event_static_tape_v2_v3",
        "intrabar_bracket_rust_v1",
        "native_strategy_ir_v1",
        "native_wfo_prepared_signal_v2",
        "package_atomic_market_v1",
        "package_market_v2",
        "package_market_v2_scenario_batch",
        "portfolio_target_market_v1",
        "shared_portfolio_target_units_v1",
        "shared_portfolio_target_wfo_v1",
    }


def test_phase54b4_release_workflow_certifies_the_installed_exact_pair() -> None:
    workflow = (ROOT / ".github" / "workflows" / "native-release.yml").read_text(
        encoding="utf-8"
    )
    for expected in (
        'python-version: ["3.11", "3.12", "3.13"]',
        "tools/certify_native_release.py",
        "tools/check_native_release_handoff.py",
        "tools/run_test_shards.py --profile release",
        "benchmark_phase54b2_public_routes.py",
        "benchmark_phase54b3_portfolio_package.py",
        "native-release-certification-cpython-",
        "cargo audit",
    ):
        assert expected in workflow


def test_phase54b4_certifier_forbids_repository_import_shortcuts_and_checks_oracles() -> None:
    source = (ROOT / "tools" / "certify_native_release.py").read_text(encoding="utf-8")
    for expected in (
        'for name in ("PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "POETRY_ACTIVE")',
        "environment.pop(name, None)",
        'environment["PYTHONNOUSERSITE"] = "1"',
        '"site-packages" in value.parts',
        "verify_staged_wheels(dist, require_native=True, install=True)",
        "native_backend=\"python\"",
        "target_python_oracle_parity",
        "package_python_oracle_parity",
        'native_static_abi_resolved',
        'native_result_v2',
    ):
        assert expected in source
