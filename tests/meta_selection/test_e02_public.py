"""Full-pool, prepared, future-label and public original-work conformance."""

from dataclasses import replace
from pathlib import Path
import json

import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError
from tests.meta_selection.test_qms06_prepared import (
    PreparedSMAStrategy, assert_pools, context, endpoint, execute, sidecar,
)
from tools.qms_e02_audit import compare
from tools.qms_e02_source_guard import ALLOW, ENTRY, ROOT, checked_source, verify


@pytest.mark.parametrize("protocol", ["W0", "W1", "W2"])
def test_e02_t02_existing_prepared_protocol_full_pool_anchor_account_parity(protocol):
    strategy = None if protocol == "W0" else PreparedSMAStrategy(batch=protocol == "W2")
    ordinary, _ = execute(endpoint("active", strategy=strategy))
    prepared, _ = execute(endpoint("active", prepared="require", strategy=strategy,
        strategy_policy="off" if protocol == "W0" else "require"))
    assert_pools(ordinary, prepared)
    for result in (ordinary, prepared):
        meta = sidecar(result)
        counters = meta["domain_adapter"]
        assert counters["input_bindings"] == counters["financial_delegate_calls"] == meta["observer_attempts"]
        assert counters["original_observations"] == meta["observer_attempts"]
        assert counters["financial_replays"] == counters["adapter_market_array_copies"] == 0
        assert counters["market_validations"] == 1
        assert counters["market_binding"]["compatibility"]["domain"] == "scalar"


def test_e02_t02_w3_original_observer_and_reset_account_contract_remain_separate():
    from tests.meta_selection.test_local_reactive import execute as run
    result, _, runtime = run("shadow")
    try:
        meta = result.metadata["meta_selection"]
        counters = meta["domain_adapter"]
        assert counters["domain"] == "reactive"
        assert counters["financial_delegate_calls"] == counters["original_observations"] == meta["observer_attempts"]
        assert meta["witness_transport"]["financial_replays"] == 0
        assert counters["market_binding"]["compatibility"]["final_account"] == "reset_flat"
        assert result.metadata["continuous_equity_available"] is False
    finally:
        runtime.close()


def test_e02_t03_actual_future_labels_and_market_suffix_do_not_change_earlier_decision():
    from tests.meta_selection.test_qms05_public import run, sidecar as meta, native_digest
    from tools.qms01_baseline import market
    a = run("active", observer=True)
    future = market()
    future.loc[future.index >= "2022-01-01", "close"] *= 1.6
    b = run("active", observer=True, data=future)
    first_a, first_b = meta(a[1])["records"][0], meta(b[1])["records"][0]
    for field in ("family_id", "selected_evaluation_id", "native_selected_evaluation_id", "selected_params"):
        assert first_a[field] == first_b[field]
    assert first_a["current_outer_oos_used_for_selection"] is False


def test_e02_t03_unavailable_or_other_domain_labels_cannot_enter_actual_public_fit():
    from tests.meta_selection.test_qms05_public import run, sidecar as meta, reviewed_history
    from quantbt.optimization.meta_selection.history import MetaHistory, SealedTaskRevision
    cold = run("shadow")
    task = meta(cold[1])["tasks"][0]
    _, revision = reviewed_history(task)
    future = task.forward_end + __import__("pandas").Timedelta(days=1000)
    unavailable = replace(revision, revision_available_at=future,
        outcomes=tuple(replace(o, label_available_at=future) for o in revision.outcomes))
    other_task = replace(revision.task, family=replace(revision.task.family, scorer_contract_id="portfolio-domain-v1"))
    other = SealedTaskRevision(other_task, replace(revision.panel, task_id=other_task.task_id),
        tuple(replace(o, task_id=other_task.task_id) for o in revision.outcomes),
        revision.revision_available_at, verification="reviewed_import")
    for row in (unavailable, other):
        history = MetaHistory()
        history.append(row)
        result = run("active", history=history)[1]
        assert all(r["matured_origins"] == 0 for r in meta(result)["records"])
        assert all(r["selected_evaluation_id"] == r["native_selected_evaluation_id"] for r in meta(result)["records"])


@pytest.mark.parametrize("field", ["funding", "volume", "constraints", "universe"])
def test_e02_t04_actual_market_funding_constraints_and_universe_change_binding(field):
    from quantbt import QuantBTEndpoint
    from examples.wfo_meta_selection import market
    a = endpoint("shadow")
    data = market()
    if field == "funding":
        a = QuantBTEndpoint(replace(a.config, use_funding=True, funding_rate=data.close*.00001))
        b = QuantBTEndpoint(replace(a.config, funding_rate=a.config.funding_rate*.5))
    elif field == "constraints":
        b = QuantBTEndpoint(replace(a.config, qty_step=.01))
    else:
        b = a
    x, _ = execute(a, data=data)
    ydata = data.copy()
    if field == "volume":
        ydata["volume"] *= 2
    if field == "universe":
        b = QuantBTEndpoint(replace(b.config, symbols=["BTC"]))
    y, _ = execute(b, data=ydata)
    assert sidecar(x)["domain_adapter"]["market_binding"] != sidecar(y)["domain_adapter"]["market_binding"]


def test_e02_t06_exact_review_guard_rejects_any_extra_adapter_or_financial_byte():
    assert verify()["financial_numeric_source_unchanged"]
    for name in ALLOW:
        with pytest.raises(AssertionError, match="unreviewed"):
            checked_source((ROOT/name).read_bytes()+b"\n# unreviewed\n", name)


@pytest.mark.parametrize("field", ["native", "scalar", "reactive"])
def test_e02_t06_before_after_gate_rejects_changed_search_account_or_decisions(field):
    old = dict(schema="qms-e02-baseline-v1", native=dict(lanes=[dict(identity="exact")],
        guide_sha256="same-guide", historical_receipts={}),
        scalar={"off-False":dict(scientific_signature="exact", decisions=[])},
        reactive={"None":dict(account="exact")})
    new = json.loads(json.dumps(old))
    if field == "native":
        new["native"]["lanes"][0]["identity"] = "wrong"
    elif field == "scalar":
        new["scalar"]["off-False"]["scientific_signature"] = "wrong"
    else:
        new["reactive"]["None"]["account"] = "wrong"
    with pytest.raises(AssertionError):
        compare(old,new)
