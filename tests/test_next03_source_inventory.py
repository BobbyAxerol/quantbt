from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "next03_source_inventory.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("next03_source_inventory", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_next03_inventory_locks_canonical_src_and_retired_mirror_provenance(tmp_path: Path) -> None:
    tool = _load_tool()
    baseline = tool._load_retirement_baseline()
    payload = tool.build_inventory(retirement_baseline=baseline)

    assert tool.validate_inventory(payload, retirement_baseline=baseline) == []
    assert payload["canonical_source"] == "src/quantbt"
    assert payload["build"]["package_find_where"] == ["src"]
    assert payload["mirror"]["state"] == "canonical_only"
    assert payload["mirror"]["drifted_files"] == []
    assert payload["mirror"]["present_entries"] == []
    assert payload["mirror"]["historical_verified_files"] == 182
    assert all(
        item["mirror_status"] == "retired"
        for item in payload["canonical_modules"]
        if item["mirror_status"] not in {"not_in_historical_mirror_scope"}
    )
    assert any(
        item["disposition"] == "canonical_package_only"
        for item in payload["canonical_modules"]
    )

    inventory = tmp_path / "inventory.json"
    document = tmp_path / "inventory.md"
    assert tool.main(["--inventory", str(inventory), "--doc", str(document)]) == 0
    assert tool.main(["--inventory", str(inventory), "--doc", str(document), "--check"]) == 0
