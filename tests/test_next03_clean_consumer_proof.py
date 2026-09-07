"""NEXT-03 installed-consumer proof construction locks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "verify_wheels.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("verify_wheels", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_next03_public_consumer_smoke_uses_isolated_wfo_extra_and_preflight_gate() -> None:
    tool = _load_tool()

    source = tool._installed_script(
        "1.1.0",
        expect_native=True,
        direct_target_smoke=True,
        public_surface_smoke=True,
    )
    compile(source, "<next03-installed-consumer>", "exec")
    for expected in (
        "_InstalledReactiveStrategy",
        "mode_4_is_only_robust",
        "per_fold_causal",
        "next03_intentionally_unsupported_capability",
        "failed before preparation",
    ):
        assert expected in source

    editable = tool._editable_developer_script("1.1.0")
    compile(editable, "<next03-editable-consumer>", "exec")
    assert 'repository / "src" / "quantbt" / "__init__.py"' in editable

    with pytest.raises(ValueError, match="staged native wheel"):
        tool._installed_script("1.1.0", expect_native=False, public_surface_smoke=True)

    verifier_source = TOOL_PATH.read_text(encoding="utf-8")
    assert '"-I"' in verifier_source
    assert 'f"{core_artifact}[optimization]"' in verifier_source
