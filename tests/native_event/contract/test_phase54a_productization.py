"""Phase 54A product-registry, source-layout, and release-evidence gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import ModuleType
import zipfile

import pytest

from quantbt.core.native_event_capabilities import native_event_semantic_descriptor
from quantbt.core.product_contracts import (
    NativePackageCompatibilityError,
    find_native_package_pair,
    native_runtime_product_descriptor,
    require_native_package_pair,
    workload_capabilities,
)


ROOT = Path(__file__).resolve().parents[3]


def _run_tool(name: str, *arguments: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / name), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_generated_product_and_lifecycle_artifacts_are_clean() -> None:
    _run_tool("sync_source_mirror.py", "--check")
    _run_tool("generate_native_event_contracts.py", "--check")
    _run_tool("generate_product_contracts.py", "--check")
    _run_tool("generate_public_api_inventory.py", "--check")
    _run_tool("check_module_architecture.py")
    _run_tool("check_benchmark_governance.py")
    _run_tool("check_docs_links.py")


def test_product_registry_preserves_the_frozen_api_04_semantic_descriptor() -> None:
    assert native_event_semantic_descriptor() == {
        "descriptor_version": "native-event-semantics-v1",
        "native_api": "0.4",
        "core_protocol_min": 1,
        "core_protocol_max": 1,
        "contract_registry_fingerprint": "601d639f1c398ac81f3c8231c30d067372c80e71ae4e5f097182f00c5c91f05d",
        "trace_schema": "canonical-execution-trace-v1",
        "command_abi": "full-command-v1",
        "contracts": [
            "event_lifecycle_v2_next_bar_close",
            "event_lifecycle_v3_next_open",
        ],
        "orders": {
            "types": ["market", "limit", "stop_market", "stop_limit"],
            "partial_fill": False,
            "volume_model": "infinite_bar_liquidity",
            "gap_policy": ["legacy_trigger", "open_worse_than_trigger"],
        },
        "account": {
            "pnl_models": ["linear_quote_settled"],
            "margin_models": ["gross_cross"],
            "liquidation_models": ["zero_equity_legacy"],
        },
        "portfolio": {
            "target_execution": "target_units_market_v1_all_or_none_v2",
            "package_atomicity": "bar_transaction_atomic_market_v1",
        },
    }


def test_product_registry_has_exact_pairing_and_generated_corpus() -> None:
    registry = json.loads((ROOT / "contracts" / "native_event_product_registry.json").read_text())
    canonical = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    manifest = json.loads((ROOT / "contracts" / "generated_product_manifest.json").read_text())
    corpus = json.loads((ROOT / "tests" / "corpus" / "generated" / "product_contract_cases.json").read_text())

    assert manifest["product_registry_fingerprint"] == hashlib.sha256(canonical).hexdigest()
    assert manifest["lifecycle_registry_fingerprint"] == registry["lifecycle_registry"]["fingerprint"]
    assert corpus["registry_fingerprint"] == manifest["product_registry_fingerprint"]
    assert require_native_package_pair("1.0.8", "0.4.0").status == "exact_staged_pair"
    assert find_native_package_pair("1.0.8", "0.4.1") is None
    with pytest.raises(NativePackageCompatibilityError, match="unsupported quantbt-engine/quantbt-native pair"):
        require_native_package_pair("1.0.8", "0.4.1")

    workloads = {str(item["id"]): item for item in workload_capabilities()}
    assert workloads["event_static_tape_v2_v3"]["maturity"] == "promoted"
    assert workloads["native_strategy_ir_v1"]["maturity"] == "promoted"
    assert workloads["event_static_tape_v2_v3"]["auto_promotion"] is True
    assert workloads["native_strategy_ir_v1"]["auto_promotion"] is True
    assert workloads["portfolio_target_market_v1"]["maturity"] == "certified"
    assert workloads["package_atomic_market_v1"]["maturity"] == "certified"
    assert workloads["portfolio_target_market_v1"]["auto_promotion"] is False
    assert workloads["package_atomic_market_v1"]["auto_promotion"] is False
    assert workloads["portfolio_target_preflight_v1"]["auto_promotion"] is False
    assert workloads["package_transaction_preflight_v1"]["auto_promotion"] is False


def test_supply_chain_report_records_locked_sources_and_forbidden_unsafe_code() -> None:
    sys.path.insert(0, str(ROOT))
    from tools.create_supply_chain_report import build_supply_chain_report

    report = build_supply_chain_report()
    assert report["schema"] == "quantbt-supply-chain-report-v1"
    assert report["core"]["distribution"] == "quantbt-engine"
    assert report["native"]["distribution"] == "quantbt-native"
    assert report["rust_workspace"]["unsafe_code_policy"] == "forbid"
    assert report["rust_workspace"]["unsafe_inventory"] == []
    assert {item["path"] for item in report["lockfiles"]} == {"uv.lock", "rust/Cargo.lock"}
    assert len(str(report["build_provenance"]["cargo_lock_sha256"])) == 64
    assert len(str(report["build_provenance"]["product_registry_fingerprint"])) == 64


def test_native_wheel_allowlist_allows_only_extension_and_native_metadata(tmp_path: Path) -> None:
    from tools.check_release_artifacts import inspect_artifact

    wheel = tmp_path / "quantbt_native-0.4.0-cp312-cp312-manylinux_2_17_x86_64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("_quantbt_native/__init__.py", "")
        archive.writestr("_quantbt_native/_quantbt_native.cpython-312-x86_64-linux-gnu.so", b"native")
        archive.writestr("quantbt_native-0.4.0.dist-info/METADATA", "Name: quantbt-native\n")
        archive.writestr("quantbt_native-0.4.0.dist-info/RECORD", "")
    assert inspect_artifact(wheel) == []


def test_api_04_probe_rejects_an_undeclared_core_native_pair_before_execution() -> None:
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension

    module = ModuleType("_quantbt_native")
    module.version = lambda: "0.4.99"
    module.api_version = lambda: "0.4"
    module.capabilities = lambda: {"reactive_session": True, "semantic_descriptor_v1": True}
    module.semantic_descriptor = native_event_semantic_descriptor

    status = probe_native_event_rust_extension(module=module)
    assert status.available
    assert not status.compatible
    assert not status.executable
    assert status.reason is not None
    assert "unsupported quantbt-engine/quantbt-native pair" in status.reason


def test_api_04_probe_rejects_a_pair_without_the_product_abi_descriptor() -> None:
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension

    module = ModuleType("_quantbt_native")
    module.version = lambda: "0.4.0"
    module.api_version = lambda: "0.4"
    module.capabilities = lambda: {"reactive_session": True, "semantic_descriptor_v1": True}
    module.semantic_descriptor = native_event_semantic_descriptor

    status = probe_native_event_rust_extension(module=module)
    assert status.available
    assert not status.compatible
    assert not status.executable
    assert status.reason is not None
    assert "native product descriptor mismatch" in status.reason


def test_runtime_product_descriptor_has_one_exact_staged_pair() -> None:
    descriptor = native_runtime_product_descriptor()
    assert descriptor["core_package_version"] == "1.0.8"
    assert descriptor["native_package_version"] == "0.4.0"
    assert descriptor["command_abi"] == "full-command-v1"
    assert descriptor["result_abi"] == "native-event-result-v1"


def test_release_manifest_binds_product_contract_and_supply_chain_evidence(tmp_path: Path) -> None:
    from tools.create_release_manifest import build_manifest
    from tools.create_sbom import build_sbom
    from tools.create_supply_chain_report import build_supply_chain_report

    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "quantbt_engine-1.0.8-py3-none-any.whl", "w"):
        pass
    with tarfile.open(dist / "quantbt_engine-1.0.8.tar.gz", "w:gz"):
        pass
    with zipfile.ZipFile(
        dist / "quantbt_native-0.4.0-cp312-cp312-manylinux_2_17_x86_64.whl", "w"
    ):
        pass
    supply = tmp_path / "supply-chain.json"
    supply.write_text(json.dumps(build_supply_chain_report()), encoding="utf-8")
    sbom = tmp_path / "sbom.cdx.json"
    sbom.write_text(json.dumps(build_sbom()), encoding="utf-8")

    manifest = build_manifest(dist, supply_chain_report=supply, sbom=sbom)
    assert len(manifest["product_contract"]["product_registry_fingerprint"]) == 64
    assert manifest["product_contract"]["lifecycle_registry_fingerprint"] == (
        "601d639f1c398ac81f3c8231c30d067372c80e71ae4e5f097182f00c5c91f05d"
    )
    assert manifest["supply_chain_evidence"]["schema"] == "quantbt-supply-chain-report-v1"
    assert manifest["supply_chain_evidence"]["unsafe_code_policy"] == "forbid"
    assert manifest["supply_chain_evidence"]["build_provenance"]["native_profile"] == "release"
    assert manifest["sbom_evidence"] == {
        "path": str(sbom.resolve()),
        "sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        "bom_format": "CycloneDX",
        "spec_version": "1.5",
    }
    assert manifest["artifact_sets"]["quantbt-engine"] == {
        "version": "1.0.8",
        "kinds": ["sdist", "wheel"],
        "artifact_count": 2,
        "published": True,
    }
    assert manifest["artifact_sets"]["quantbt-native"] == {
        "version": "0.4.0",
        "kinds": ["wheel"],
        "artifact_count": 1,
        "published": False,
    }

    (dist / "quantbt_native-0.4.1-cp312-cp312-manylinux_2_17_x86_64.whl").write_bytes(
        b"wrong native version"
    )
    with pytest.raises(RuntimeError, match="does not match a declared product"):
        build_manifest(dist, supply_chain_report=supply, sbom=sbom)


def test_p3_workflows_execute_generated_and_staged_wheel_gates() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    native = (ROOT / ".github" / "workflows" / "native.yml").read_text(encoding="utf-8")
    nightly = (ROOT / ".github" / "workflows" / "native-nightly.yml").read_text(encoding="utf-8")
    security = (ROOT / ".github" / "workflows" / "native-security.yml").read_text(encoding="utf-8")
    for expected in (
        "tools/generate_product_contracts.py --check",
        "tools/generate_public_api_inventory.py --check",
        "tools/check_module_architecture.py",
        "tools/check_benchmark_governance.py",
        "tools/check_docs_links.py",
        "tools/verify_wheels.py --dist dist",
    ):
        assert expected in ci
    assert "tools/verify_wheels.py --dist dist/staged --require-native" in native
    assert "benchmark_phase53a_e0_profiles.py" in nightly
    assert "benchmark_phase53b_native_drivers.py" in nightly
    assert "native-nightly-e0-e3-e6" in nightly
    assert "cargo audit" in security
