"""E02 typed contracts and pending route admission, no simulated economic claim."""

from dataclasses import replace

import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.domains import (
    DOMAIN_ABI, DomainCompatibility, EvaluationBinding, EvaluationStage, InputKind,
    MarketBinding, capability, check_route_inventory, route_metadata,
)


def compatibility(**kwargs):
    values = dict(domain="portfolio", input_kind=InputKind.POSITION_MATRIX,
        universe=("BTC", "ETH"), calendar_policy="exact-v2", instrument_contract="linear-v2",
        funding_policy="position-at-event-v1", economics_id="costs-v1", metric_id="metric-v1",
        execution_timing="next-open-v3", diagnostic_account="reset-flat", final_account="carry",
        witness_abi="original-result-v1")
    return DomainCompatibility(**{**values, **kwargs})


def request(**kwargs):
    index = pd.date_range("2024-01-01", periods=3, tz="UTC")
    return EvaluationBinding(**{**dict(domain="scalar", input_kind=InputKind.SCALAR_TARGET,
        stage=EvaluationStage.CURRENT_IS, index=index, params={"x": 2},
        payload=pd.Series([0., 1., 0.], index=index), input_signature="input",
        information_as_of=index[-1]), **kwargs})


def test_e02_t01_binding_preserves_payload_and_actual_params_without_array_copy():
    old = request()
    assert old.payload.index is old.index
    assert dict(old.params) == {"x": 2}
    with pytest.raises(TypeError):
        old.params["x"] = 9
    assert isinstance(old.stage, EvaluationStage)


@pytest.mark.parametrize("field", ["index", "abi", "information_as_of", "decision_sealed_at"])
def test_e02_t01_abi_calendar_and_unsealed_future_fail_closed(field):
    old = request()
    change = {"index": old.index.tz_localize(None), "abi": "unknown",
              "information_as_of": old.index[0], "decision_sealed_at": old.index[-1]}[field]
    with pytest.raises((MetaRecordError, ValueError, TypeError)):
        replace(old, **{field: change}, **({"stage": EvaluationStage.FINAL_OOS} if field == "decision_sealed_at" else {}))


@pytest.mark.parametrize("field,value", [
    ("domain", "package"), ("input_kind", InputKind.PACKAGE), ("universe", ("ETH", "BTC")),
    ("calendar_policy", "union-v2"), ("instrument_contract", "inverse-v2"),
    ("funding_policy", "close-approx"), ("economics_id", "fees-v2"), ("metric_id", "metric-v2"),
    ("execution_timing", "same-close"), ("diagnostic_account", "carry"),
    ("final_account", "reset"), ("witness_abi", "prepared-v2"),
])
def test_e02_t03_family_isolates_domain_universe_funding_costs_metrics_and_account(field, value):
    old = compatibility()
    new = replace(old, **{field: value})
    assert new.compatibility_id != old.compatibility_id


@pytest.mark.parametrize("field", ["source_signature", "calendar_signature", "instrument_signature", "funding_signature", "run_id"])
def test_e02_t04_market_mutation_changes_exact_binding_but_not_nominal_family(field):
    old = MarketBinding("run", "data", "calendar", "instrument", "funding", compatibility())
    new = replace(old, **{field: "changed"})
    assert new.binding_id != old.binding_id
    assert new.compatibility.compatibility_id == old.compatibility.compatibility_id


@pytest.mark.parametrize("route", ["basket", "arbitrage",
                                  "intrabar", "order_commands", "options", "nautilus_validation"])
def test_e02_t05_pending_entries_are_not_activated(route):
    assert not route_metadata(route)["meta_route_activated"]
    with pytest.raises(MetaRecordError, match="META_ROUTE_UNSUPPORTED"):
        capability(route, require_active=True)


def test_e02_t05_future_dispatch_requires_explicit_route_or_pending_gate():
    assert check_route_inventory(["signal_notional", "portfolio", "intrabar"])
    with pytest.raises(MetaRecordError, match="unregistered"):
        check_route_inventory(["unregistered-new-public-dispatch"])
    with pytest.raises(MetaRecordError, match="DUPLICATE"):
        check_route_inventory(["portfolio", "portfolio"])
    with pytest.raises(MetaRecordError, match="ABI"):
        capability("signal_notional", abi=DOMAIN_ABI + "-next")
