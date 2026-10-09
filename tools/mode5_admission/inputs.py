"""Load reviewed copies without importing raw research modules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from tools.mode5_baseline.isolation import file_identity


def load_package(name: str, root: Path) -> ModuleType:
    root = Path(root).resolve()
    if name in sys.modules:
        raise ValueError("isolated package name is already loaded")
    spec = importlib.util.spec_from_file_location(
        name, root / "__init__.py", submodule_search_locations=[str(root)]
    )
    if spec is None or spec.loader is None:
        raise ValueError("reviewed package has no import loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load_module(name: str, path: Path, expected_sha256: str) -> ModuleType:
    identity = file_identity(Path(path))
    if identity["sha256"] != expected_sha256:
        raise ValueError("reviewed source identity changed")
    if name in sys.modules:
        raise ValueError("isolated module name is already loaded")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("reviewed source has no import loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module
