from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tomllib

import numpy as np
import pytest

import quantbt
from quantbt.core.native_event_capabilities import (
    NATIVE_EVENT_CAPABILITY_MATRIX,
    NATIVE_EVENT_CAPABILITY_MATRIX_VERSION,
    capability_matrix_fingerprint,
    normalize_native_event_capabilities,
    validate_native_event_capability_matrix,
)
from quantbt.core.native_event_parity import (
    NativeEventParityError,
    assert_native_event_full_parity,
)
from quantbt.backends._native_event_rust import probe_native_event_rust_extension


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _audit_fixture(seed: int = 42) -> SimpleNamespace:
    rng = np.random.default_rng(seed)
    bars = 18
    equity = 10_000.0 + np.cumsum(rng.normal(0.0, 0.25, bars))
    positions = rng.choice((-1.0, 0.0, 1.0), size=(bars, 1)).astype(np.float64)
    fees = np.abs(rng.normal(0.02, 0.005, bars))
    funding = rng.normal(0.0, 0.01, bars)
    turnover = np.abs(rng.normal(100.0, 2.0, bars))
    initial_margin = np.abs(positions[:, 0]) * 20.0
    maintenance_margin = np.abs(positions[:, 0]) * 1.0
    return SimpleNamespace(
        equity=equity,
        positions=positions,
        fees=fees,
        funding=funding,
        turnover=turnover,
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        liquidated=False,
        liquidation_bar=-1,
        fill_bar=np.array([2, 7, 11], dtype=np.int64),
        fill_order_id=np.array([0, 1, 2], dtype=np.int64),
        fill_side=np.array([1, -1, 1], dtype=np.int64),
        fill_qty=np.array([1.0, 0.5, 0.5], dtype=np.float64),
        fill_price=np.array([100.0, 101.0, 102.0], dtype=np.float64),
        fill_fee=np.array([0.02, 0.01, 0.01], dtype=np.float64),
        event_bar=np.array([1, 2, 7, 11], dtype=np.int64),
        event_kind=np.array([0, 4, 4, 4], dtype=np.int64),
        event_status=np.array([0, 1, 1, 1], dtype=np.int64),
        event_order_id=np.array([0, 0, 1, 2], dtype=np.int64),
        event_target_id=np.array([-1, -1, -1, -1], dtype=np.int64),
    )


def test_phase46a_capability_matrix_is_canonical_and_fingerprinted() -> None:
    assert NATIVE_EVENT_CAPABILITY_MATRIX_VERSION == "full-contract-v2-0.4"
    assert NATIVE_EVENT_CAPABILITY_MATRIX["single_symbol"] is True
    assert NATIVE_EVENT_CAPABILITY_MATRIX["market"] is True
    assert NATIVE_EVENT_CAPABILITY_MATRIX["stop_limit"] is True
    assert NATIVE_EVENT_CAPABILITY_MATRIX["funding"] is True
    assert NATIVE_EVENT_CAPABILITY_MATRIX["liquidation"] is True
    assert NATIVE_EVENT_CAPABILITY_MATRIX["multi_symbol"] is True
    assert len(capability_matrix_fingerprint()) == 64
    validate_native_event_capability_matrix(NATIVE_EVENT_CAPABILITY_MATRIX)
    with pytest.raises(ValueError, match="unknown"):
        validate_native_event_capability_matrix({"future_feature": True})


def test_phase46a_rust_raw_flags_normalize_without_overclaiming() -> None:
    capabilities = normalize_native_event_capabilities(
        {
            "reactive_session": True,
            "r1_place_cancel_market_limit_gtc": True,
            "r2_stop_amend_replace_reduce_only_constraints": True,
            "rust_batched_tape_audit": True,
            "future_unreviewed_feature": True,
        }
    )
    assert capabilities["single_symbol"] is True
    assert capabilities["amend"] is True
    assert capabilities["quantity_constraints"] is True
    assert capabilities["oco"] is False
    assert capabilities["funding"] is False
    assert capabilities["multi_symbol"] is False
    assert "future_unreviewed_feature" not in capabilities


def test_phase46a_rust_probe_exposes_canonical_capabilities() -> None:
    class FakeNative:
        @staticmethod
        def api_version() -> str:
            return "0.3"

        @staticmethod
        def version() -> str:
            return "0.3.0"

        @staticmethod
        def capabilities() -> dict[str, bool]:
            return {
                "reactive_session": True,
                "r1_place_cancel_market_limit_gtc": True,
                "r2_stop_amend_replace_reduce_only_constraints": True,
            }

    status = probe_native_event_rust_extension(module=FakeNative())
    assert status.canonical_capabilities["single_symbol"] is True
    assert status.canonical_capabilities["amend"] is True
    assert status.canonical_capabilities["funding"] is False


def test_phase46a_full_parity_compares_accounting_and_lifecycle() -> None:
    candidate = _audit_fixture()
    oracle = _audit_fixture()
    command_tape = (
        {"effective_bar": np.array([1, 2, 7, 11]), "sequence": np.array([0, 1, 2, 3])},
        {"effective_bar": np.array([1, 2, 7, 11]), "sequence": np.array([0, 1, 2, 3])},
    )
    certificate = assert_native_event_full_parity(candidate, oracle, command_tape=command_tape)
    assert certificate["passed"] is True
    assert certificate["candidate_fingerprint"] == certificate["oracle_fingerprint"]
    assert set(("equity", "positions", "fees", "turnover", "fills", "events")) <= set(
        certificate["compared_fields"]
    )


def test_phase46a_numeric_tolerance_does_not_change_discrete_decisions() -> None:
    candidate = _audit_fixture()
    oracle = _audit_fixture()
    candidate.equity = candidate.equity.copy()
    candidate.equity[5] += 5e-13
    assert_native_event_full_parity(candidate, oracle)

    candidate.equity[5] += 5e-12
    with pytest.raises(NativeEventParityError, match="equity mismatch"):
        assert_native_event_full_parity(candidate, oracle)

    candidate = _audit_fixture()
    candidate.event_status = candidate.event_status.copy()
    candidate.event_status[1] = 2
    with pytest.raises(NativeEventParityError, match="events lifecycle"):
        assert_native_event_full_parity(candidate, oracle)


def test_phase46a_strict_mode_rejects_minimal_artifacts() -> None:
    candidate = _audit_fixture()
    oracle = _audit_fixture()
    for result in (candidate, oracle):
        for name in (
            "fill_bar", "fill_order_id", "fill_side", "fill_qty", "fill_price", "fill_fee",
            "event_bar", "event_kind", "event_status", "event_order_id", "event_target_id",
        ):
            delattr(result, name)
    with pytest.raises(NativeEventParityError, match="artifacts missing"):
        assert_native_event_full_parity(candidate, oracle)
    certificate = assert_native_event_full_parity(candidate, oracle, require_full=False)
    assert certificate["passed"] is True


def test_phase46a_seeded_randomized_differential_fingerprints() -> None:
    for seed in range(32):
        candidate = _audit_fixture(seed)
        oracle = _audit_fixture(seed)
        certificate = assert_native_event_full_parity(candidate, oracle)
        assert certificate["candidate_fingerprint"] == certificate["oracle_fingerprint"]


def test_phase46a_public_import_and_package_metadata_baseline() -> None:
    assert quantbt.assert_native_event_full_parity is assert_native_event_full_parity
    assert quantbt.NATIVE_EVENT_CAPABILITY_MATRIX_VERSION == NATIVE_EVENT_CAPABILITY_MATRIX_VERSION

    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    assert project["name"] == "quantbt-engine"
    assert project["version"] == "1.0.7"
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert "quantbt*" in metadata["tool"]["setuptools"]["packages"]["find"]["include"]


def test_phase46a_capability_fingerprint_is_stable() -> None:
    payload = {
        "version": NATIVE_EVENT_CAPABILITY_MATRIX_VERSION,
        "capabilities": dict(sorted(NATIVE_EVENT_CAPABILITY_MATRIX.items())),
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert capability_matrix_fingerprint() == expected
