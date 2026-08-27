from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
FORBIDDEN_CORE_MODULES = (
    "matplotlib",
    "seaborn",
    "optuna",
    "nautilus_trader",
    "quantstats",
)


def _fresh_source_import(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(SOURCE_ROOT),
            "MPLCONFIGDIR": "/tmp",
        }
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd="/tmp",
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_phase46c_core_import_does_not_load_optional_modules() -> None:
    code = """
import json
import sys
import quantbt
from quantbt import QuantBTEndpoint

forbidden = ("matplotlib", "seaborn", "optuna", "nautilus_trader", "quantstats")
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)
print(json.dumps({"loaded": loaded, "endpoint_module": QuantBTEndpoint.__module__}))
assert not loaded, loaded
assert QuantBTEndpoint.__module__ == "quantbt.endpoint"
"""
    completed = _fresh_source_import(code)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    evidence = json.loads(completed.stdout.strip().splitlines()[-1])
    assert evidence["loaded"] == []
    assert evidence["endpoint_module"] == "quantbt.endpoint"


def test_phase46c_core_public_exports_remain_accessible() -> None:
    import quantbt

    for name in (
        "BacktestEngine",
        "MultiSymbolPortfolio",
        "QuantBTEndpoint",
        "BacktestResult",
        "NativeEventBackend",
        "NativeVectorizedBackend",
        "OptionBacktestEngine",
        "PortfolioBacktestEngine",
    ):
        assert getattr(quantbt, name).__name__ == name


def test_phase46c_lazy_export_identity() -> None:
    import quantbt
    from quantbt.optimization import OptunaOptimizer
    from quantbt.viz import quick_plot as direct_quick_plot
    from quantbt.walkforward import WalkForwardConfig

    assert quantbt.OptunaOptimizer is OptunaOptimizer
    assert quantbt.quick_plot is direct_quick_plot
    assert quantbt.WalkForwardConfig is WalkForwardConfig


def test_phase46c_lazy_export_access_is_thread_safe_after_resolution() -> None:
    import quantbt

    names = ("OptunaOptimizer", "WalkForwardConfig", "quick_plot", "tearsheet")
    expected = {name: getattr(quantbt, name) for name in names}
    with ThreadPoolExecutor(max_workers=len(names) * 2) as executor:
        resolved = list(
            executor.map(
                lambda name: getattr(quantbt, name),
                names * 4,
            )
        )

    for name, value in zip(names * 4, resolved):
        assert value is expected[name]


def test_phase46c_dependency_ownership_is_explicit() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    dependencies = list(project["dependencies"])
    dependency_names = {
        item.split(";", 1)[0].split(">", 1)[0].split("=", 1)[0].strip()
        for item in dependencies
    }
    assert dependency_names == {"numpy", "pandas", "numba", "quantbt-native"}

    native_dependency = next(item for item in dependencies if item.startswith("quantbt-native=="))
    assert native_dependency.startswith("quantbt-native==0.4.1;")
    for marker in (
        "sys_platform == 'linux'",
        "platform_machine == 'x86_64'",
        "implementation_name == 'cpython'",
        "python_version >= '3.11'",
        "python_version < '3.14'",
    ):
        assert marker in native_dependency

    optional = project["optional-dependencies"]
    assert any(item.startswith("matplotlib") for item in optional["viz"])
    assert any(item.startswith("seaborn") for item in optional["viz"])
    assert any(item.startswith("optuna") for item in optional["optimization"])
    assert any(item.startswith("quantstats") for item in optional["reports"])
    assert any(item.startswith("nautilus-trader") for item in optional["validation"])


@pytest.mark.parametrize("name", ("quick_plot", "tearsheet", "OptunaOptimizer", "WalkForwardConfig"))
def test_phase46c_lazy_export_is_listed_for_discovery(name: str) -> None:
    import quantbt

    assert name in dir(quantbt)
    assert name in quantbt.__all__
