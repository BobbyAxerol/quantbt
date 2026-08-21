from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src" / "quantbt"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            values.append("." * node.level + (node.module or ""))
    return tuple(values)


def _python_files(relative: str) -> tuple[Path, ...]:
    return tuple(sorted((SOURCE / relative).rglob("*.py")))


def test_p1_dependency_direction_is_enforced_by_ast_contract():
    rules = {
        "planning": ("reporting", "endpoint", "_quantbt_native", "pandas"),
        "engine_spi": ("reporting", "endpoint", "pandas"),
        "results": ("backends", "endpoint", "pandas"),
    }
    violations = []
    for package, forbidden in rules.items():
        for path in _python_files(package):
            for imported in _imports(path):
                if any(name in imported for name in forbidden):
                    violations.append((str(path.relative_to(ROOT)), imported))
    assert violations == []


def test_planning_and_core_imports_do_not_eagerly_load_native_extension():
    script = """
import sys
import quantbt.planning
import quantbt.engine_spi.protocol
import quantbt.results.raw
assert '_quantbt_native' not in sys.modules
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_p1_modules_import_in_both_orders_without_a_cycle():
    orders = (
        "import quantbt.planning, quantbt.preparation, quantbt.engine_spi, quantbt.results",
        "import quantbt.results, quantbt.engine_spi, quantbt.preparation, quantbt.planning",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    for script in orders:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
