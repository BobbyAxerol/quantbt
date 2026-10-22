"""Phase 56 locks for the Rust-primary V1.1 baseline evidence.

These tests are intentionally repository-contract tests. They do not execute a
backtest or import an optional native wheel, so they can catch documentation,
authority, corpus, and measurement drift before a later native implementation
change obscures the baseline.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from support.historical_assets import GitSnapshot


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_endpoint_inventory.json"
CORPUS_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_corpus_manifest.json"
MEASUREMENT_PATH = ROOT / "contracts" / "v1_1_measurement_contract.json"
WHEEL_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_installed_wheel_baseline.json"
MEASUREMENT_MODULE_PATH = ROOT / "src" / "quantbt" / "benchmarks" / "v1_1_measurement.py"
GENERATOR_PATH = ROOT / "tools" / "generate_v1_1_baseline.py"
# The 1.1.1/0.4.2 baseline refresh, distinct from the 1.1.0 wheel receipt.
BASELINE_SNAPSHOT = "62b8ea1a5490fdea68940db3d40e431dcf9e7858"


@pytest.fixture(scope="module")
def historical_baseline(tmp_path_factory):
    snapshot = GitSnapshot(BASELINE_SNAPSHOT)
    outputs = {
        INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "docs/generated/v1_1_endpoint_inventory.md",
        CORPUS_PATH.relative_to(ROOT).as_posix(),
        "docs/generated/v1_1_corpus_manifest.md",
        MEASUREMENT_PATH.relative_to(ROOT).as_posix(),
        "docs/generated/v1_1_measurement_contract.md",
    }
    paths = outputs | {GENERATOR_PATH.relative_to(ROOT).as_posix()}
    for relative in outputs:
        snapshot.assert_retained(relative)
    for relative in (INVENTORY_PATH, CORPUS_PATH):
        payload = snapshot.read_json(relative.relative_to(ROOT).as_posix())
        records = list(payload["source_fingerprints"].values())
        for case in payload.get("cases", []):
            records.extend(case["artifacts"])
        for record in records:
            snapshot.assert_record(record)
            paths.add(record["path"])
    destination = tmp_path_factory.mktemp("phase56-snapshot")
    snapshot.materialize(destination, paths)
    return snapshot, snapshot.load_module(destination, "tools/generate_v1_1_baseline.py")

EXPECTED_CORPUS_CASES = {
    "atomic_package",
    "fill_replay",
    "intrabar_bracket",
    "intrabar_rust_explicit",
    "options_basic_european",
    "pct_equity",
    "portfolio",
    "reactive_grid_mrs_like",
    "signal_notional",
    "static_v2_v3_orders",
    "wfo_engine_enforced_nested",
    "wfo_global",
    "wfo_per_fold_causal",
    "wfo_per_fold_decay",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_measurement_module():
    specification = importlib.util.spec_from_file_location("phase56_measurement", MEASUREMENT_MODULE_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_generator_module():
    specification = importlib.util.spec_from_file_location("phase56_generator", GENERATOR_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_phase56_generated_baseline_artifacts_match_their_git_snapshot(historical_baseline) -> None:
    snapshot, generator = historical_baseline
    outputs = generator.generated_outputs()
    assert {path.relative_to(generator.ROOT).as_posix() for path in outputs} == {
        INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "docs/generated/v1_1_endpoint_inventory.md",
        CORPUS_PATH.relative_to(ROOT).as_posix(),
        "docs/generated/v1_1_corpus_manifest.md",
        MEASUREMENT_PATH.relative_to(ROOT).as_posix(),
        "docs/generated/v1_1_measurement_contract.md",
    }
    for path, expected in outputs.items():
        relative = path.relative_to(generator.ROOT).as_posix()
        assert snapshot.read_bytes(relative).decode("utf-8") == expected
        assert (ROOT / relative).read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("historical", [True, False], ids=["frozen-1.1.1", "current-source"])
def test_phase56_inventory_covers_every_public_factory_and_separates_authority(
    historical_baseline, historical: bool,
) -> None:
    snapshot, historical_generator = historical_baseline
    generator = historical_generator if historical else _load_generator_module()
    inventory = _load_json(INVENTORY_PATH) if historical else generator.build_endpoint_inventory()
    factories = set(generator._endpoint_factories())
    coverage = inventory["endpoint_factory_coverage"]

    assert inventory["schema"] == "quantbt-rust-primary-v1_1-endpoint-inventory-v1"
    assert set(coverage) == factories
    assert all(coverage[factory] for factory in factories)

    public_rows = [row for row in inventory["rows"] if row["surface_type"] == "public_endpoint"]
    assert {row["factory"] for row in public_rows} == factories
    product_path = "contracts/native_event_product_registry.json"
    product = snapshot.read_json(product_path) if historical else _load_json(ROOT / product_path)
    expected_core_version = str(product["versions"]["core_package"]["version"])
    expected_native_version = str(product["versions"]["native_package"]["version"])
    for row in inventory["rows"]:
        assert set(row["authority"]) == set(generator.AUTHORITY_FIELDS)
        assert row["fallback"]["auto"]
        assert row["fallback"]["explicit"]
        assert row["package_versions"]["quantbt_engine"] == expected_core_version
        assert row["package_versions"]["quantbt_native"] == expected_native_version

    by_id = {row["id"]: row for row in inventory["rows"]}
    assert by_id["event_driven_strategy"]["runtime_class"] == "PythonCompatibility"
    assert by_id["event_driven_orders"]["maturity"] == "certified_explicit_rust"
    assert by_id["portfolio_generic"]["resolved_backend_baseline"] == "Python/NumPy/Numba native_portfolio backend"
    assert by_id["native_workload::event_static_tape_v2_v3"]["auto_promotion"] is False
    assert by_id["native_workload::portfolio_target_market_v1"]["auto_promotion"] is False


def test_phase56_corpus_hashes_and_measurements_are_complete(historical_baseline) -> None:
    snapshot, _ = historical_baseline
    corpus = _load_json(CORPUS_PATH)
    measurement = _load_measurement_module()

    assert corpus["schema"] == "quantbt-rust-primary-v1_1-corpus-manifest-v1"
    assert {case["id"] for case in corpus["cases"]} == EXPECTED_CORPUS_CASES
    for case in corpus["cases"]:
        for artifact in case["artifacts"]:
            snapshot.assert_record(artifact)
        assert measurement.validate_measurement_record_v1(case["measurement"]) == []
        if case["status"] == "baseline_available":
            assert case["measurement"]["measurement_status"] == "historical_artifact"
        else:
            assert case["id"] == "wfo_engine_enforced_nested"
            assert case["measurement"]["measurement_status"] == "not_applicable"


def test_phase56_measurement_contract_is_engine_independent_and_versioned() -> None:
    module = _load_measurement_module()
    payload = _load_json(MEASUREMENT_PATH)
    source = MEASUREMENT_MODULE_PATH.read_text(encoding="utf-8")

    assert payload == module.measurement_contract_definition_v1()
    assert "import pandas" not in source
    assert "import quantbt" not in source
    assert "import _quantbt_native" not in source
    record = module.build_measurement_record_v1(
        workload_id="test",
        route_id="test-route",
        profile="score",
        requested_backend="auto",
        resolved_backend="python",
        runtime_class="PythonCompatibility",
        measurement_status="measured",
        boundary_counters={"native_entry_calls": 0, "python_callback_calls": 1},
        memory_bytes={"warm_steady_rss_bytes": 0},
    )
    assert record["boundary_counters"]["native_entry_calls"] == 0
    assert record["boundary_counters"]["market_copy_bytes"] is None
    assert record["memory_bytes"]["warm_steady_rss_bytes"] == 0


def test_phase56_adrs_are_indexed_and_state_reversible_decisions() -> None:
    adr_index = (ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    adr_files = sorted((ROOT / "docs" / "adr").glob("ADR-RP-*.md"))

    assert len(adr_files) == 5
    for path in adr_files:
        source = path.read_text(encoding="utf-8")
        assert path.name in adr_index
        for heading in ("**Status:**", "## Context", "## Decision", "## Consequences", "## Rollback"):
            assert heading in source


def test_phase56_installed_wheel_baseline_is_clean_pair_evidence() -> None:
    payload = _load_json(WHEEL_PATH)

    assert payload["schema"] == "quantbt-rust-primary-v1_1-installed-wheel-baseline-v1"
    assert payload["core_distribution"] == {"name": "quantbt-engine", "version": "1.1.0"}
    assert payload["native_distribution"] == {"name": "quantbt-native", "version": "0.4.1"}
    assert payload["wheel_verification"]["source_hash_parity"] is True
    assert payload["wheel_verification"]["clean_install"] is True
    # Verify the actual released 1.1.0 source, not the later inventory refresh.
    snapshot = GitSnapshot(payload["source_revision"]["git_sha"])
    receipt = GitSnapshot("7d8bc8ff68ddc8a61aaaa1fb78d30f9d1641d1d4")
    receipt.assert_retained(WHEEL_PATH.relative_to(ROOT).as_posix())
    assert receipt._git("rev-parse", f"{receipt.commit}^").decode().strip() == snapshot.commit
    for name, fingerprint in payload["source_fingerprints"].items():
        if name == "measurement_contract_module":
            # This adapter was added with the receipt, not shipped in the
            # preceding wheel source. Verify it there without claiming parity.
            receipt.assert_record(fingerprint)
            continue
        snapshot.assert_record(fingerprint)
    assert len(payload["source_revision"]["git_sha"]) == 40
    assert payload["route_observations"]["core_only_auto_backend"] == "native_unavailable"
    assert payload["route_observations"]["exact_pair_static_auto_backend"] == "auto_rust_certified"
    assert payload["route_observations"]["exact_pair_native_api"] == "0.4"
    assert payload["tested_contract"]["import_boundary"].startswith("fresh venvs")
