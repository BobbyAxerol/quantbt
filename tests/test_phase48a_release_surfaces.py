"""Phase 48A release-surface and Native Event API 0.4 locks."""

from __future__ import annotations

import re
from pathlib import Path
import json
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "native.yml"
LEGACY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "native-r0.yml"
PACKAGING_DOC = PROJECT_ROOT / "docs" / "release_packaging.md"
NATIVE_CARGO = PROJECT_ROOT / "rust" / "native_event" / "Cargo.toml"
NATIVE_PYPROJECT = PROJECT_ROOT / "rust" / "native_event" / "pyproject.toml"
NATIVE_LIB = PROJECT_ROOT / "rust" / "native_event" / "src" / "lib.rs"
NATIVE_GENERATED_CONTRACTS = (
    PROJECT_ROOT / "rust" / "crates" / "quantbt-domain" / "src" / "generated_product_contracts.rs"
)


REQUIRED_CAPABILITIES = (
    "native_event_v2_full_contract",
    "native_event_v2_multisymbol",
    "native_event_v2_funding",
    "native_event_v2_liquidation",
    "native_event_v2_cancel_all_oco",
    "native_event_v2_tif_expiry",
    "native_event_v2_relationships",
    "native_event_v2_quantity_preflight",
)


def test_native_workflow_is_api_04_and_not_the_r0_surface():
    text = WORKFLOW.read_text()

    assert WORKFLOW.is_file()
    assert not LEGACY_WORKFLOW.exists()
    assert "Native Event API 0.4 Gate" in text
    assert "api_version() == \"0.4\"" in text
    assert "api_version() == '0.3'" not in text
    assert "Native Event API 0.4 capabilities: PASS" in text
    for capability in REQUIRED_CAPABILITIES:
        assert capability in text


def test_native_distribution_metadata_matches_executable_version():
    cargo = NATIVE_CARGO.read_text()
    native_pyproject = NATIVE_PYPROJECT.read_text()
    native_lib = NATIVE_LIB.read_text()
    generated_contracts = NATIVE_GENERATED_CONTRACTS.read_text()
    registry = json.loads((PROJECT_ROOT / "contracts" / "native_event_product_registry.json").read_text())
    native_version = str(registry["versions"]["native_package"]["version"])

    assert tomllib.loads(NATIVE_CARGO.read_text())["package"]["version"] == native_version
    assert tomllib.loads(NATIVE_PYPROJECT.read_text())["project"]["version"] == native_version
    assert re.search(rf'^version\s*=\s*"{re.escape(native_version)}"', cargo, re.MULTILINE)
    assert re.search(rf'^version\s*=\s*"{re.escape(native_version)}"', native_pyproject, re.MULTILINE)
    assert f'pub const NATIVE_PACKAGE_VERSION: &str = "{native_version}";' in generated_contracts
    assert 'pub const NATIVE_API_VERSION: &str = "0.4";' in generated_contracts
    assert "const VERSION: &str = generated_product_contracts::NATIVE_PACKAGE_VERSION;" in native_lib
    assert "const API_VERSION: &str = generated_product_contracts::NATIVE_API_VERSION;" in native_lib


def test_release_packaging_docs_describe_current_api_04_policy():
    text = PACKAGING_DOC.read_text()

    current_section = text.split(
        "## Native Event Rust API 0.4",
        maxsplit=1,
    )[1].split(
        "### Historical R0/R1/R2 scaffold",
        maxsplit=1,
    )[0]

    assert "public Native Event V2" in current_section
    assert "native_backend=\"rust\"` is explicit and fail-fast" in current_section
    assert "native_backend=\"auto\"` uses the generated Stage-B static/IR/batch policy" in current_section
    assert "published core-only install remains Python" in current_section
    assert "one symbol, GTC, no funding" not in current_section
    assert "Parent/child, OCO, expiry, IOC/FOK" not in current_section
    assert "single- and multi-symbol execution" in current_section
    assert "funding, margin and liquidation" in current_section
    assert "parent/group/OCO and expiry" in current_section
