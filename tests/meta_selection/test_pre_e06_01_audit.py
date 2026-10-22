"""PRE-E06-01 inventory/preflight only: no financial simulation or alpha work."""

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import optuna
import pytest

from quantbt import QuantBTEndpoint
from quantbt.walkforward import WalkForwardConfig
from quantbt.optimization.meta_selection.config import MetaSelectionConfig, validate_meta_route
from quantbt.optimization.meta_selection.domains.registry import adapter_for, capability, route_metadata
from tools.check_docs_links import validate_links
from tools import qms_pre_e06_inventory as audit
from tools.qms_pre02_source_guard import verify_pre01_archive, verify_pre01_patch


ACTIVE = tuple(r for r in audit.OWNERS if audit.OWNERS[r][0] is not None)


@pytest.fixture(scope="module")
def inventory():
    return json.loads((audit.ROOT / audit.MANIFEST).read_text())


def config(route="signal_notional", **changes):
    values = dict(target_mode=route, optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", scoring_backend="endpoint", optuna_trials=1,
        meta_selection=MetaSelectionConfig(mode="active"),
        metadata={"use_scalar_trial_scoring": False})
    if route == "reactive_reset":
        values.update(target_mode="signal_notional", fold_account_policy="reset_flat")
    return WalkForwardConfig(**{**values, **changes})


def test_pre01_t01_complete_source_bound_discovery_and_retained_receipts(inventory):
    # Subsequent phases preserve this historical receipt; it is not a live-source certificate.
    assert verify_pre01_archive(inventory) is inventory
    assert len(inventory["routes"]) == 15
    assert len(ACTIVE) == 13
    assert inventory["protected"]["retained_artifacts"] == 50
    assert not inventory["release"] and not inventory["empirical_promotion"]


@pytest.mark.parametrize("violation", ["missing_row", "activation", "metric", "source", "test_owner"])
def test_pre01_t01_inventory_cannot_certify_missing_or_tampered_contract(inventory, violation):
    payload = deepcopy(inventory)
    if violation == "missing_row":
        payload["routes"].pop()
    elif violation == "activation":
        payload["routes"][-1]["meta"]["meta_route_activated"] = True
    elif violation == "metric":
        payload["metric_contract_365"]["sample_policy"] = "alternate"
    elif violation == "source":
        payload["protected"]["runtime_sha256"] = "0" * 64
    else:
        payload["routes"][0]["existing_test_owners"] = []
    with pytest.raises(ValueError, match="incomplete, tampered or stale"):
        verify_pre01_archive(payload)


@pytest.mark.parametrize("route", ACTIVE)
def test_pre01_t02_discovery_matches_actual_adapter_and_method_guard(route):
    row = capability(route, require_active=True)
    metadata = route_metadata(route)
    modes = ("mode_4_is_only_robust", "mode_1_decay") if metadata["meta_domain"] == "scalar" else ("mode_4_is_only_robust",)
    assert metadata["meta_optimization_modes"] == modes
    assert metadata["meta_optimization_schedules"] == ("per_fold_causal",)
    kind, *_ = audit.OWNERS[route]
    scorer_id = "reactive-native-original-reset-v1" if route == "reactive_reset" else "original-endpoint-reset-v1"
    endpoint = None
    if kind == "scalar":
        from examples.wfo_meta_scalar import make_scalar_endpoint
        endpoint = make_scalar_endpoint(route,
            backend="legacy" if route in {"pct_equity", "dca_ladder"} else "native_vectorized")
    elif kind == "portfolio":
        from examples.wfo_meta_portfolio import make_endpoint
        endpoint = make_endpoint()
    elif kind == "package":
        from examples.wfo_meta_package import make_endpoint
        endpoint = make_endpoint(kind="basket" if route == "basket" else "basis")
    runtime = SimpleNamespace(engine=SimpleNamespace(config=config(route),
        scorer=SimpleNamespace(meta_route_id=scorer_id,
            config=endpoint.config if endpoint is not None else None,
            symbols=endpoint.config.symbols if endpoint is not None else None)))
    adapter = adapter_for(runtime)
    assert type(adapter).__name__ == audit.SOURCES[kind][1]
    assert adapter.domain == row.domain
    assert adapter.stats["financial_delegate_calls"] == 0
    validate_meta_route(config(route), route="reactive_reset" if route == "reactive_reset" else "target_series")


@pytest.mark.parametrize("route", ACTIVE)
@pytest.mark.parametrize("field,value", [
    ("scoring_backend", "proxy"), ("calendar_contract", "legacy_v1"),
    ("strategy_lifecycle_policy", "legacy_reuse_v1"),
    ("fold_account_policy", "close_at_boundary"),
])
def test_pre01_t02_unqualified_account_calendar_or_scorer_is_rejected(route, field, value):
    cfg = config(route)
    change = {field: value}
    if field == "fold_account_policy":
        change["fold_boundary_position_policy"] = "carry"
    with pytest.raises(ValueError, match="META_ROUTE_UNSUPPORTED"):
        validate_meta_route(replace(cfg, **change),
            route="reactive_reset" if route == "reactive_reset" else "target_series")


@pytest.mark.parametrize("mode,schedule,extra", [
    ("mode_1_decay", "per_fold_decay", {}),
    ("mode_2_sbb", "global", {}), ("mode_3_flat_minima", "global", {}),
    ("mode_4_is_only_robust", "global", {}), ("mode_5_full_robust", "global", {}),
])
def test_pre01_t03_unactivated_method_rejected_at_public_boundary_before_search(monkeypatch, mode, schedule, extra):
    def forbidden(*args, **kwargs):
        pytest.fail("unactivated methodology reached search/strategy")
    monkeypatch.setattr(optuna, "create_study", forbidden)
    with pytest.raises((ValueError, NotImplementedError), match="META_|meta|endpoint"):
        QuantBTEndpoint.walk_forward(strategy_class=forbidden,
            optimization_mode=mode, optimization_schedule=schedule, optuna_trials=1,
            optimization_config={"meta_selection": {"mode": "active"},
                "use_scalar_trial_scoring": False, **extra})


@pytest.mark.parametrize("route", ["options", "nautilus_validation", "new_domain"])
def test_pre01_t03_future_admission_not_promoted_by_inventory(route):
    with pytest.raises(ValueError, match="META_ROUTE_UNSUPPORTED"):
        capability(route, require_active=True)


def test_pre01_t04_source_symbols_links_and_current_state_are_consistent(inventory):
    assert validate_links(audit.ROOT, check_anchors=True,
        files=[audit.ROOT / n for n in audit.DOCS]) == []
    for row in inventory["routes"]:
        for ref in row["existing_test_owners"]:
            audit.check_symbol(ref)
        if row["adapter_owner"]:
            audit.check_symbol(row["adapter_owner"])
            assert row["next_required_gate"] == "PRE02-MATURED-" + row["route"]
    plan = (audit.ROOT / "upgrade/implement.md").read_text()
    current = plan.split("Previous performance and package closure:", 1)[0]
    assert "E06-E08 remain **PLANNED_NOT_AUTHORIZED_FOR_EXECUTION**" not in current
    assert "Current local package qualification" in current
    phase = plan.split("### Phase M5-12 -", 1)[1].split("### Mode 5 Planning Verification", 1)[0]
    assert "**Status:**" in phase and "local" in phase.lower()
    assert "No automatic version bump or native/public package promotion" in phase
    handoff = (audit.ROOT / "handoff/WFO_META_CURRENT.md").read_text().split("## Historical Local Debt Closure", 1)[0]
    assert "E06-E08 are unapproved" not in handoff
    assert "C01 additional methods | Nested scalar runtime implemented PRE-E06-03" in handoff
    assert "C05 geometry | Reviewed implementation approved" in handoff
    baseline = (audit.ROOT / "docs/meta_selection/PRE_E06_BASELINE.md").read_text()
    assert all(token in baseline for token in (
        "REGISTERED_NOT_EXECUTED", "2022-04-30", "2023-04-30", "2024-04-30",
        ">=12 unique permitted VALID-labeled origins", "M01", "M07", "Private by default"))


def test_pre01_t05_staged_scope_secret_and_artifact_safety():
    assert verify_pre01_patch()
    for name in (".env", "private_alpha.py", "dist/new.whl", "src/quantbt/endpoint.py"):
        with pytest.raises(ValueError, match="non-phase"):
            audit.check_patch_safety([name])


@pytest.mark.parametrize("secret", [
    "ghp_" + "a" * 30, "pypi-" + "a" * 40,
    "-----BEGIN " + "PRIVATE KEY-----",
    "/root/bobby/pool_alpha/" + "alphas_storage/private.py",
])
def test_pre01_t05_secret_or_private_path_cannot_be_exported(secret):
    with pytest.raises(ValueError, match="private path or credential"):
        audit.check_public_text(secret)


def test_pre01_t05_missing_test_owner_is_not_silently_accepted():
    with pytest.raises(ValueError, match="missing inventory"):
        audit.check_symbol("tests/meta_selection/test_pre_e06_01_audit.py::not_a_test")
