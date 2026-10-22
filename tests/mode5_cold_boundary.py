"""Exercise historical cold-loader guards without loading a private driver."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def assert_cold_boundary(module_name, owner_name, blocked):
    code = """
import importlib
import sys
from types import ModuleType
from unittest.mock import patch

module = importlib.import_module(sys.argv[1])
owner = object()
# Only resolve the owner boundary here. Numeric behavior is tested separately
# against the real public implementations, not this sentinel.
with patch.object(module.importlib, 'import_module', return_value=owner) as load:
    assert module.numeric_owner() is owner
    load.assert_called_once_with(sys.argv[2])
assert any(isinstance(finder, module.ColdImports) for finder in sys.meta_path)
assert not any(module.forbidden(name) for name in sys.modules)
for name in sys.argv[3:]:
    try:
        importlib.import_module(name)
    except ImportError as exc:
        assert 'prohibit runtime import' in str(exc), (name, exc)
    else:
        raise AssertionError('financial import admitted: ' + name)
assert not any(module.forbidden(name) for name in sys.modules)

sys.modules['quantbt.core'] = ModuleType('quantbt.core')
with patch.object(module.importlib, 'import_module') as load:
    try:
        module.numeric_owner()
    except RuntimeError as exc:
        assert 'fresh cold process required' in str(exc)
    else:
        raise AssertionError('warm process admitted')
    load.assert_not_called()
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, module_name, owner_name, *blocked],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
