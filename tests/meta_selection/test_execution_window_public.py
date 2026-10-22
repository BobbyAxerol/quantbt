"""Public financial owners and the shared meta boundary, not scalar proxies."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantbt.wfo_execution import execute_window
from examples.wfo_meta_execution import execute, market, make_endpoint, generate


@pytest.fixture(scope="module", params=("intrabar", "event_driven", "order_commands", "delivery_arbitrage"))
def runs(request):
    return request.param, {m: execute(request.param, mode=m, support=1)
                           for m in ("off", "shadow", "active")}


def assert_account(a, b):
    for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(a, name), getattr(b, name))


def test_shadow_pool_params_and_original_account_are_exact(runs):
    _, values = runs
    a, b = values["off"][1], values["shadow"][1]
    assert_account(a, b)
    wa, wb = (r.metadata["walk_forward"] for r in (a, b))
    assert wa["params_by_fold"] == wb["params_by_fold"]
    pd.testing.assert_frame_equal(wa["trial_table"], wb["trial_table"])
    meta = wb["meta_selection"]
    assert meta["observer_attempts"] > 0 and meta["observer_failures"] == 0
    assert meta["domain_adapter"]["financial_replays"] == 0
    assert all(not r["current_outer_oos_used_for_selection"] for r in meta["records"])


def test_active_final_rebuild_uses_actual_fold_intent_in_one_account(runs):
    route, values = runs
    endpoint, result, _ = values["active"]
    output = result.metadata["walk_forward_result"].oos_output
    rebuilt = execute_window(endpoint.config.wfo_execution_config, market(route), output)
    assert_account(result, rebuilt)
    assert result.metadata["wfo_execution_window"]["financial_replays"] == 0
    boundaries = result.metadata["walk_forward"]["fold_boundary_table"]
    assert boundaries.changed_targets.isna().all()
    assert boundaries.target_before.isna().all()


def test_original_is_and_forward_metrics_not_proxy(runs):
    route, values = runs
    endpoint, result, history = values["shadow"]
    task = result.metadata["walk_forward"]["meta_selection"]["tasks"][0]
    candidate = task.candidates[0]
    index = pd.date_range(task.is_start, task.is_end, freq="D")
    data = market(route)
    out = generate(route, data, candidate.effective_params, index)
    original = execute_window(endpoint.config.wfo_execution_config, data, out)
    assert candidate.observation.raw_sharpe == original.full_report(scope="full", trading_days=365)["sharpe"]
    revision = next(r for r in history.history._revisions.values() if r.task.task_id == task.task_id)
    outcome = revision.outcomes[0]
    candidate = next(c for c in task.candidates if c.evaluation_id == outcome.evaluation_id)
    index = pd.date_range(task.forward_start, task.forward_end, freq="D")
    original = execute_window(endpoint.config.wfo_execution_config, data,
        generate(route, data, candidate.effective_params, index))
    assert outcome.observation.raw_sharpe == original.full_report(scope="full", trading_days=365)["sharpe"]


@pytest.mark.parametrize("route", ("intrabar", "event_driven", "order_commands", "delivery_arbitrage"))
def test_future_prices_do_not_change_first_causal_selection(route):
    data = market(route)
    a = execute(route, mode="shadow", data=data, support=1)[1]
    frames = data.values() if isinstance(data, dict) else (data,)
    for frame in frames:
        frame.loc[frame.index >= "2021-04-01", ["open", "high", "low", "close"]] *= 1.3
    b = execute(route, mode="shadow", data=data, support=1)[1]
    ma, mb = (r.metadata["walk_forward"]["meta_selection"] for r in (a, b))
    for field in ("family_id", "selected_params", "selected_evaluation_id", "training_snapshot_id"):
        assert ma["records"][0][field] == mb["records"][0][field]
    assert ma["tasks"][0].candidates == mb["tasks"][0].candidates


@pytest.mark.parametrize("route", ("intrabar", "event_driven", "order_commands", "delivery_arbitrage"))
def test_unsupported_proxy_and_account_policy_fail_before_search(route):
    endpoint = make_endpoint(route)
    cfg = endpoint.config
    with pytest.raises(NotImplementedError):
        from quantbt.wfo_execution import validate_execution_route
        validate_execution_route(cfg, replace(cfg.walkforward_config, fold_account_policy="reset_flat"))


@pytest.mark.parametrize("route", ("intrabar", "event_driven", "order_commands", "delivery_arbitrage"))
def test_prepared_witness_and_reference_have_identical_decisions_and_account(route):
    _, a, ca = execute(route, mode="shadow", support=1, witness=True)
    _, b, cb = execute(route, mode="shadow", support=1, witness=False)
    assert_account(a, b)
    ma, mb = (r.metadata["walk_forward"]["meta_selection"] for r in (a, b))
    for ra, rb in zip(ma["records"], mb["records"]):
        for key in ("family_id", "selected_params", "selected_evaluation_id"):
            assert ra[key] == rb[key]
    assert ma["records"][0]["training_snapshot_id"] == mb["records"][0]["training_snapshot_id"]
    for ta, tb in zip(ma["tasks"], mb["tasks"], strict=True):
        assert replace(ta, wall_generated_at=tb.wall_generated_at) == tb
    # Independent wall/publication receipts differ; bound metric labels do not.
    for ra, rb in zip(ca.history._revisions.values(), cb.history._revisions.values(), strict=True):
        assert ra.panel == rb.panel
        assert [(o.evaluation_id, o.observation) for o in ra.outcomes] == [
            (o.evaluation_id, o.observation) for o in rb.outcomes]


@pytest.mark.parametrize("route", ("intrabar", "event_driven", "order_commands", "delivery_arbitrage"))
def test_existing_rust_financial_owner_parity(route):
    a = execute(route, mode="off", backend="python", trials=2)[1]
    b = execute(route, mode="off", backend="rust", trials=2)[1]
    for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_allclose(getattr(a, name), getattr(b, name), rtol=1e-11, atol=1e-9)
    assert a.metadata["walk_forward"]["params_by_fold"] == b.metadata["walk_forward"]["params_by_fold"]
