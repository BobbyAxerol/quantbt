"""Phase 78 route-scoped public Rust-promotion contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from quantbt.core.native_event_promotion import NativePromotionContext, resolve_native_event_promotion


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "contracts" / "native_event_product_registry.json"
EVIDENCE_PATH = ROOT / "benchmarks" / "native_event" / "results" / "phase78_public_promotion.json"
CERTIFIER_PATH = ROOT / "tools" / "certify_phase78_public_promotion.py"
PUBLIC_PROMOTION_DOC = ROOT / "docs" / "native" / "public_rust_promotion.md"
BASELINE_INVENTORY_PATH = ROOT / "benchmarks" / "baselines" / "v1_1_endpoint_inventory.json"

_IR_CAPABILITIES = (
    "native_event_v2_full_contract",
    "native_strategy_ir_v1",
    "native_strategy_ir_signal_target",
    "native_strategy_ir_grid_level",
    "native_strategy_ir_dca_periodic",
    "native_strategy_ir_fixed_bracket",
    "native_strategy_ir_batch_v1",
)


def _certifier_module():
    spec = importlib.util.spec_from_file_location("phase78_public_promotion", CERTIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _context(**updates: object) -> NativePromotionContext:
    values: dict[str, object] = {
        "requested_backend": "auto",
        "backend_policy": "certified_only",
        "workload_id": "native_strategy_ir_v1",
        "execution_contract_id": "event_lifecycle_v2_next_bar_close",
        "strategy_mode": "ir_v1",
        "profile": "score",
        "account_model": "linear_quote_settled_gross_cross",
        "bars": 2_000,
        "symbol_count": 1,
        "native_available": True,
        "native_compatible": True,
        "native_executable": True,
        "native_capabilities": _IR_CAPABILITIES,
        "platform_tags": ("cpython-3.12+", "linux-x86_64-local"),
    }
    values.update(updates)
    return NativePromotionContext(**values)


def test_phase78_checked_certificate_matches_exact_ir_registry_summary() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    certifier = _certifier_module()

    assert certifier.validate_checked_evidence(payload, registry=registry) == []
    assert payload["scope"]["auto_promotion_workloads"] == ["native_strategy_ir_v1"]
    assert payload["scope"]["non_promotion_observations"] == {
        "event_static_tape_v2_v3": "public_score_performance_not_stable_enough_for_auto"
    }
    assert registry["performance_evidence"]["native_strategy_ir_v1"] == payload["routes"]["native_strategy_ir_v1"]
    # The admission artifact predates the policy flip by design. Otherwise its
    # registry and extension fingerprints would recursively hash themselves.
    assert payload["routes"]["native_strategy_ir_v1"]["measurement"]["parity"]["auto_backend"] == "python"


def test_phase78_auto_policy_is_score_only_and_preserves_static_hold() -> None:
    promoted = resolve_native_event_promotion(_context(), environment={})
    assert (promoted.resolved_backend, promoted.reason, promoted.minimum_bars) == (
        "rust",
        "auto_rust_certified",
        2_000,
    )

    below_threshold = resolve_native_event_promotion(_context(bars=1_999), environment={})
    assert (below_threshold.resolved_backend, below_threshold.reason, below_threshold.minimum_bars) == (
        "python",
        "below_promotion_min_bars",
        2_000,
    )

    audit = resolve_native_event_promotion(_context(profile="audit"), environment={})
    assert (audit.resolved_backend, audit.reason) == ("python", "workload_shape_not_certified")

    static = resolve_native_event_promotion(
        _context(
            workload_id="event_static_tape_v2_v3",
            strategy_mode="static_commands",
            profile="score",
            bars=10_000,
            native_capabilities=("native_event_v2_full_contract",),
        ),
        environment={},
    )
    assert (static.resolved_backend, static.reason) == (
        "python",
        "public_score_performance_not_stable_enough_for_auto",
    )


def test_phase78_kill_switch_and_explicit_rust_contract_remain_fail_closed() -> None:
    disabled = resolve_native_event_promotion(
        _context(), environment={"QUANTBT_DISABLE_NATIVE": "1"}
    )
    assert (disabled.resolved_backend, disabled.reason) == ("python", "emergency_native_disabled")

    capped = resolve_native_event_promotion(
        _context(), environment={"QUANTBT_NATIVE_PROMOTION_MAX": "explicit_only"}
    )
    assert (capped.resolved_backend, capped.reason) == ("python", "promotion_stage_limited")

    explicit = resolve_native_event_promotion(
        _context(requested_backend="rust"), environment={}
    )
    assert (explicit.resolved_backend, explicit.reason) == ("rust", "explicit_rust_certified")


def test_phase78_core_only_wheel_probe_exercises_the_promoted_ir_score_shape() -> None:
    """A missing companion must be tested against a route eligible for auto Rust."""

    from tools.certify_native_release import _installed_core_script

    script = _installed_core_script("1.1.0")
    assert 'workload_id="native_strategy_ir_v1"' in script
    assert 'strategy_mode="ir_v1"' in script
    assert 'profile="score"' in script
    assert "bars=2_000" in script
    assert 'selection.promotion.reason == "native_unavailable"' in script
    assert 'disabled.promotion.reason == "emergency_native_disabled"' in script


def test_phase78_installed_static_parity_uses_the_public_result_equity_series() -> None:
    """The endpoint facade returns BacktestResultV2, not a scalar native result."""

    from tools.certify_native_release import _installed_native_script

    script = _installed_native_script("1.1.0", "0.4.1")
    assert "static_rust_result.equity.iloc[-1]" in script
    assert "static_result.equity.iloc[-1]" in script
    assert "static_rust_result.final_equity" not in script


def test_phase78_public_docs_and_inventory_describe_the_same_narrow_route() -> None:
    document = PUBLIC_PROMOTION_DOC.read_text(encoding="utf-8")
    assert "`score` only" in document
    assert "2,000 bars" in document
    assert "Static command tapes" in document
    assert "A4 route promotion, not A5" in document

    inventory = json.loads(BASELINE_INVENTORY_PATH.read_text(encoding="utf-8"))
    row = next(
        item
        for item in inventory["rows"]
        if item["id"] == "native_workload::native_strategy_ir_v1"
    )
    assert row["auto_promotion"] is True
    assert row["runtime_class"] == "WholeRunNative"
    assert "one-symbol score requests at 2,000+ bars" in row["resolved_backend_baseline"]
