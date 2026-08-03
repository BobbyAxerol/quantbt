from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_phase42_distribution_name_preserves_import_module() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert metadata["project"]["name"] == "quantbt-engine"
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert "quantbt*" in metadata["tool"]["setuptools"]["packages"]["find"]["include"]


def test_phase42_src_quantbt_layout_exists() -> None:
    package_root = PROJECT_ROOT / "src" / "quantbt"

    assert (package_root / "__init__.py").is_file()
    assert (package_root / "endpoint.py").is_file()
    assert (package_root / "core").is_dir()
    assert (package_root / "backends").is_dir()
    assert (package_root / "py.typed").is_file()


def test_phase42_root_source_kept_during_migration() -> None:
    assert (PROJECT_ROOT / "__init__.py").is_file()
    assert (PROJECT_ROOT / "endpoint.py").is_file()
