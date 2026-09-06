"""Phase 72 measurement, evidence, and withdrawn-promotion regression gates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantbt.core.generated_product_contracts import NATIVE_EVENT_PRODUCT_REGISTRY
from quantbt.core.native_event_promotion import NativePromotionContext, resolve_native_event_promotion
from tools.measurement_contract import (
    CURRENT_CANDIDATE_VERIFIED,
    IDENTITY_REQUIRED_FIELDS,
    build_work_counters,
    capture_measurement_identity,
    current_candidate_evidence_violations,
    load_measurement_contract,
    throughput_per_second,
    typed_array_sha256,
    validate_measurement_contract,
)


CONTRACT_PATH = ROOT / "benchmarks" / "native_event" / "manifests" / "phase72_measurement_contract_v1.json"


def _governance_module():
    path = ROOT / "tools" / "check_benchmark_governance.py"
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    specification = importlib.util.spec_from_file_location("phase72_governance", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _current_candidate_evidence(contract: dict[str, object]) -> dict[str, object]:
    """Build a self-contained valid candidate record for gate-negative tests."""

    digest = "a" * 64
    identity = {
        "git_commit": "b" * 40,
        "git_dirty": False,
        "git_status_sha256": digest,
        "canonical_source_sha256": digest,
        "product_registry_sha256": digest,
        "lifecycle_registry_sha256": digest,
        "core_distribution": {"distribution": "quantbt-engine", "version": "1.1.0"},
        "native_distribution": {"distribution": "quantbt-native", "version": "0.4.1"},
        "native_extension": {
            "available": True,
            "module_sha256": digest,
            "version": "0.4.1",
            "api_version": "0.4",
            "capability_sha256": digest,
        },
        "python": "CPython 3.12",
        "platform": "linux-x86_64",
        "cpu_count": 4,
        "thread_environment": {"OPENBLAS_NUM_THREADS": "1"},
        "data_sha256": digest,
        "intent_sha256": digest,
        "measurement_contract_sha256": digest,
        "warmup_procedure": "fresh process then repeated paired timing",
    }
    pair = next(item for item in contract["profile_pairs"] if item["id"] == "score_to_score_v1")
    comparator = {
        "timing_scope": pair["timing_scope"],
        "result_contract": pair["result_contract"],
        "metric_contract_id": "metric-contract-v2-365",
        "annualization_days": 365,
        "fee_contract_id": "canonical-one-way-fee-v1",
        "account_contract_id": "linear-quote-gross-cross-v1",
    }
    return {
        "status": "pass",
        "end_to_end_faster_than_python": True,
        "rss_plateau": True,
        "measurement_contract_id": contract["measurement_contract_id"],
        "route_id": "public_event_static",
        "profile_pair": pair["id"],
        "measurement_status": CURRENT_CANDIDATE_VERIFIED,
        "identity_status": "current_candidate",
        "promotion_eligible": True,
        "candidate_identity": identity,
        "comparator_contract": {"python": dict(comparator), "native": dict(comparator)},
        "measurement": {
            "sample_count": 9,
            "median_seconds": 0.01,
            "p95_seconds": 0.02,
            "cold_rss_mb": 100.0,
            "warm_rss_mb": 104.0,
            "parity": {"passed": True},
            "artifact_sha256": digest,
        },
    }


def test_work_counters_use_actual_unequal_test_windows_not_full_input_volume() -> None:
    counters = build_work_counters(
        supplied_market_bars=100,
        candidate_count=2,
        scenario_count=3,
        symbol_count=2,
        folds=(
            {"fold_id": 7, "test_start": 10, "test_end": 20},
            {"fold_id": 9, "test_start": 40, "test_end": 55},
        ),
        warmup_bar_visits=8,
    )

    # (10 + 15) test bars x 2 candidates x 3 scenarios, never 100 x 2 folds.
    assert counters["planned_simulation_bar_visits"] == 150
    assert counters["actual_simulation_bar_visits"] == 150
    assert counters["actual_simulation_symbol_bar_visits"] == 300
    assert counters["logical_full_tape_candidate_fold_bar_visits"] == 1_200
    assert counters["actual_visit_basis"] == "derived_exhaustive_test_windows"
    assert throughput_per_second(150, 0.5) == 300.0


def test_work_counters_require_observed_visits_for_skips_or_early_termination() -> None:
    kwargs = dict(
        supplied_market_bars=80,
        candidate_count=2,
        scenario_count=1,
        symbol_count=1,
        folds=(
            {"fold_id": 0, "test_start": 20, "test_end": 30},
            {"fold_id": 1, "test_start": 30, "test_end": 45},
        ),
    )
    with pytest.raises(ValueError, match="actual_simulation_bar_visits"):
        build_work_counters(
            **kwargs,
            skipped_candidate_fold_scenario_tasks=1,
        )
    with pytest.raises(ValueError, match="actual_simulation_bar_visits"):
        build_work_counters(
            **kwargs,
            early_terminated_candidate_fold_scenario_tasks=1,
        )

    counters = build_work_counters(
        **kwargs,
        early_terminated_candidate_fold_scenario_tasks=1,
        actual_simulation_bar_visits=31,
    )
    assert counters["planned_simulation_bar_visits"] == 50
    assert counters["actual_simulation_bar_visits"] == 31
    assert counters["actual_visit_basis"] == "observed_executor_counter"


def test_work_counters_handle_zero_candidate_tasks_and_partial_final_fold() -> None:
    counters = build_work_counters(
        supplied_market_bars=101,
        candidate_count=0,
        scenario_count=1,
        symbol_count=8,
        folds=(
            {"fold_id": 0, "test_start": 50, "test_end": 75},
            {"fold_id": 1, "test_start": 75, "test_end": 101},
        ),
    )
    assert counters["planned_candidate_fold_scenario_tasks"] == 0
    assert counters["actual_simulation_bar_visits"] == 0
    assert counters["actual_simulation_symbol_bar_visits"] == 0
    assert counters["folds"][-1]["planned_test_bar_visits"] == 26


def test_measurement_contract_locks_route_matrix_and_historical_raw_manifests() -> None:
    contract = load_measurement_contract(CONTRACT_PATH, root=ROOT)
    assert contract["measurement_contract_id"] == "quantbt-phase72-measurement-contract-v1"
    assert {route["id"] for route in contract["routes"]} >= {
        "public_generic_walk_forward",
        "prepared_native_signal_wfo",
        "reactive_event_strategies",
        "single_symbol_intrabar",
    }
    assert contract["required_matrix"]["bars"] == [1_000, 10_000, 100_000]
    assert contract["required_matrix"]["candidates"] == [16, 64, 256, 1_000]
    assert len(contract["historical_manifests"]) == 11

    invalid = deepcopy(contract)
    invalid["profile_pairs"][0]["native_profile"] = "compact"
    with pytest.raises(ValueError, match="like-for-like"):
        validate_measurement_contract(invalid, root=ROOT)


def test_measurement_identity_captures_source_dirty_state_and_optional_native_abi() -> None:
    native = ModuleType("_quantbt_native")
    native.version = lambda: "test-native"
    native.api_version = lambda: "0.4"
    native.capabilities = lambda: {"typed_request": True}
    identity = capture_measurement_identity(
        root=ROOT,
        warmup_procedure="unit-test warmup declaration",
        native_module=native,
    )
    assert set(identity) == IDENTITY_REQUIRED_FIELDS
    assert identity["native_extension"]["version"] == "test-native"
    assert identity["native_extension"]["api_version"] == "0.4"
    assert len(identity["canonical_source_sha256"]) == 64
    assert len(identity["git_status_sha256"]) == 64
    assert identity["data_sha256"] is None
    assert identity["intent_sha256"] is None


def test_typed_data_and_intent_hashes_are_shape_dtype_and_value_sensitive() -> None:
    import numpy as np

    close = np.array([100.0, 101.0], dtype=np.float64)
    target = np.array([0.0, 1.0], dtype=np.float64)
    baseline = typed_array_sha256(close, target)
    assert baseline != typed_array_sha256(close.astype(np.float32), target.astype(np.float32))
    assert baseline != typed_array_sha256(close, np.array([0.0, -1.0], dtype=np.float64))
    assert baseline != typed_array_sha256(close.reshape(2, 1), target.reshape(2, 1))


def test_historical_evidence_cannot_be_promoted_by_manually_asserting_pass() -> None:
    contract = load_measurement_contract(CONTRACT_PATH, root=ROOT)
    governance = _governance_module()
    registry = deepcopy(NATIVE_EVENT_PRODUCT_REGISTRY)
    evidence = registry["performance_evidence"]["event_static_tape_v2_v3"]
    evidence["status"] = "pass"
    evidence["promotion_eligible"] = True
    violations = governance._validate_registry_evidence(registry, contract)
    assert any("non-current evidence cannot be promotion eligible" in item for item in violations)

    evidence["measurement_status"] = CURRENT_CANDIDATE_VERIFIED
    evidence["identity_status"] = "current_candidate"
    evidence["end_to_end_faster_than_python"] = True
    evidence["rss_plateau"] = True
    violations = governance._validate_registry_evidence(registry, contract)
    assert any("candidate_identity" in item for item in violations)


def test_current_candidate_evidence_requires_matching_comparator_hashes_and_wheel() -> None:
    contract = load_measurement_contract(CONTRACT_PATH, root=ROOT)
    evidence = _current_candidate_evidence(contract)
    assert current_candidate_evidence_violations(evidence, contract) == []

    annualization_mismatch = deepcopy(evidence)
    annualization_mismatch["comparator_contract"]["native"]["annualization_days"] = 252
    assert any(
        "annualization_days differs" in item
        for item in current_candidate_evidence_violations(annualization_mismatch, contract)
    )

    timing_mismatch = deepcopy(evidence)
    timing_mismatch["comparator_contract"]["native"]["timing_scope"] = "wrong_scope"
    assert any(
        "timing_scope differs" in item
        for item in current_candidate_evidence_violations(timing_mismatch, contract)
    )

    wheel_mismatch = deepcopy(evidence)
    wheel_mismatch["candidate_identity"]["native_extension"]["module_sha256"] = "not-a-digest"
    assert any(
        "module_sha256" in item
        for item in current_candidate_evidence_violations(wheel_mismatch, contract)
    )

    data_mismatch = deepcopy(evidence)
    data_mismatch["candidate_identity"]["data_sha256"] = "missing"
    assert any(
        "data_sha256" in item
        for item in current_candidate_evidence_violations(data_mismatch, contract)
    )


def test_runtime_auto_gate_rejects_structurally_incomplete_current_evidence() -> None:
    contract = load_measurement_contract(CONTRACT_PATH, root=ROOT)
    registry = deepcopy(NATIVE_EVENT_PRODUCT_REGISTRY)
    evidence = _current_candidate_evidence(contract)
    registry["performance_evidence"]["event_static_tape_v2_v3"] = evidence
    for workload in registry["workloads"]:
        if workload["id"] == "event_static_tape_v2_v3":
            workload["maturity"] = "promoted"
            workload["auto_promotion"] = True
    for rule in registry["promotion_policy"]["rules"]:
        if rule["workload_id"] == "event_static_tape_v2_v3":
            rule["enabled"] = True

    context = NativePromotionContext(
        requested_backend="auto",
        backend_policy="certified_only",
        workload_id="event_static_tape_v2_v3",
        execution_contract_id="event_lifecycle_v3_next_open",
        strategy_mode="static_commands",
        profile="score",
        account_model="linear_quote_settled_gross_cross",
        bars=10_000,
        symbol_count=1,
        native_available=True,
        native_compatible=True,
        native_executable=True,
        native_capabilities=("native_event_v2_full_contract",),
        platform_tags=("cpython-3.12+", "linux-x86_64-local"),
    )
    accepted_structure = resolve_native_event_promotion(
        context,
        environment={},
        registry=registry,
        policy_table=registry["promotion_policy"],
    )
    assert accepted_structure.reason != "measurement_evidence_not_current"

    registry["performance_evidence"]["event_static_tape_v2_v3"]["candidate_identity"]["git_dirty"] = True
    rejected = resolve_native_event_promotion(
        context,
        environment={},
        registry=registry,
        policy_table=registry["promotion_policy"],
    )
    assert rejected.resolved_backend == "python"
    assert rejected.reason == "measurement_evidence_not_current"


def test_auto_static_route_holds_but_explicit_rust_remains_available() -> None:
    context = NativePromotionContext(
        requested_backend="auto",
        backend_policy="certified_only",
        workload_id="event_static_tape_v2_v3",
        execution_contract_id="event_lifecycle_v3_next_open",
        strategy_mode="static_commands",
        profile="score",
        account_model="linear_quote_settled_gross_cross",
        bars=10_000,
        symbol_count=1,
        native_available=True,
        native_compatible=True,
        native_executable=True,
        native_capabilities=("native_event_v2_full_contract",),
        platform_tags=("cpython-3.12+", "linux-x86_64-local"),
    )
    auto = resolve_native_event_promotion(context, environment={})
    assert auto.resolved_backend == "python"
    assert auto.reason == "measurement_evidence_not_current"

    explicit = resolve_native_event_promotion(
        replace(
            context,
            requested_backend="rust",
            required_capabilities=("native_event_v2_full_contract",),
        ),
        environment={},
    )
    assert explicit.resolved_backend == "rust"
    assert explicit.reason == "explicit_rust_certified"
    assert CURRENT_CANDIDATE_VERIFIED == "current_candidate_verified"


def test_governance_accepts_only_checked_historical_manifests() -> None:
    governance = _governance_module()
    assert governance.main([]) == 0
    payload = json.loads(
        (ROOT / "benchmarks" / "native_event" / "manifests" / "phase71_runtime_productization_v1.json").read_text()
    )
    payload["product_registry_fingerprint"] = "not-a-known-historical-fingerprint"
    path = ROOT / ".pytest_phase72_unknown_manifest.json"
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
        violations = governance.validate_manifest(path)
        assert any("product registry fingerprint drift" in item for item in violations)
    finally:
        path.unlink(missing_ok=True)
