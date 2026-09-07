"""Phase 56 locks for the Rust-primary V1.1 baseline evidence.

These tests are intentionally repository-contract tests. They do not execute a
backtest or import an optional native wheel, so they can catch documentation,
authority, corpus, and measurement drift before a later native implementation
change obscures the baseline.
"""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_endpoint_inventory.json"
CORPUS_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_corpus_manifest.json"
MEASUREMENT_PATH = ROOT / "contracts" / "v1_1_measurement_contract.json"
WHEEL_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_installed_wheel_baseline.json"
MEASUREMENT_MODULE_PATH = ROOT / "src" / "quantbt" / "benchmarks" / "v1_1_measurement.py"
GENERATOR_PATH = ROOT / "tools" / "generate_v1_1_baseline.py"

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


def test_phase56_generated_baseline_artifacts_are_current() -> None:
    outputs = _load_generator_module().generated_outputs()
    assert set(outputs) == {
        INVENTORY_PATH,
        ROOT / "docs" / "generated" / "v1_1_endpoint_inventory.md",
        CORPUS_PATH,
        ROOT / "docs" / "generated" / "v1_1_corpus_manifest.md",
        MEASUREMENT_PATH,
        ROOT / "docs" / "generated" / "v1_1_measurement_contract.md",
    }
    for path, expected in outputs.items():
        assert path.read_text(encoding="utf-8") == expected


def test_phase56_inventory_covers_every_public_factory_and_separates_authority() -> None:
    generator = _load_generator_module()

    inventory = _load_json(INVENTORY_PATH)
    factories = set(generator._endpoint_factories())
    coverage = inventory["endpoint_factory_coverage"]

    assert inventory["schema"] == "quantbt-rust-primary-v1_1-endpoint-inventory-v1"
    assert set(coverage) == factories
    assert all(coverage[factory] for factory in factories)

    public_rows = [row for row in inventory["rows"] if row["surface_type"] == "public_endpoint"]
    assert {row["factory"] for row in public_rows} == factories
    for row in inventory["rows"]:
        assert set(row["authority"]) == set(generator.AUTHORITY_FIELDS)
        assert row["fallback"]["auto"]
        assert row["fallback"]["explicit"]
        assert row["package_versions"]["quantbt_engine"] == "1.1.0"
        assert row["package_versions"]["quantbt_native"] == "0.4.1"

    by_id = {row["id"]: row for row in inventory["rows"]}
    assert by_id["event_driven_strategy"]["runtime_class"] == "PythonCompatibility"
    assert by_id["event_driven_orders"]["maturity"] == "certified_explicit_rust"
    assert by_id["portfolio_generic"]["resolved_backend_baseline"] == "Python/NumPy/Numba native_portfolio backend"
    assert by_id["native_workload::event_static_tape_v2_v3"]["auto_promotion"] is False
    assert by_id["native_workload::portfolio_target_market_v1"]["auto_promotion"] is False


def test_phase56_corpus_hashes_and_measurements_are_complete() -> None:
    corpus = _load_json(CORPUS_PATH)
    measurement = _load_measurement_module()

    assert corpus["schema"] == "quantbt-rust-primary-v1_1-corpus-manifest-v1"
    assert {case["id"] for case in corpus["cases"]} == EXPECTED_CORPUS_CASES
    for case in corpus["cases"]:
        for artifact in case["artifacts"]:
            path = ROOT / artifact["path"]
            assert path.is_file()
            assert artifact["bytes"] == path.stat().st_size
            assert artifact["sha256"] == sha256(path.read_bytes()).hexdigest()
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
    # This artifact is immutable evidence for the released 1.1.0 wheel pair,
    # not a hash lock on every later V1.1 source change. A current-tree hash
    # comparison here would make every post-baseline phase fail before its own
    # installed-wheel release gate can generate fresh evidence.
    for fingerprint in payload["source_fingerprints"].values():
        path = ROOT / fingerprint["path"]
        assert path.is_file()
        assert len(fingerprint["sha256"]) == 64
        assert all(character in "0123456789abcdef" for character in fingerprint["sha256"])
    assert len(payload["source_revision"]["git_sha"]) == 40
    assert payload["route_observations"]["core_only_auto_backend"] == "native_unavailable"
    assert payload["route_observations"]["exact_pair_static_auto_backend"] == "auto_rust_certified"
    assert payload["route_observations"]["exact_pair_native_api"] == "0.4"
    assert payload["tested_contract"]["import_boundary"].startswith("fresh venvs")
