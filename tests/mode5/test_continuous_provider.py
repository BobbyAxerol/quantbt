"""Bounded continuous attribution; no private alpha, search or new engine."""

from copy import deepcopy
from dataclasses import replace
import pickle
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt.mode5.continuous import (
    CONTINUOUS_POLICY, DAY_NS, ContinuousAccountContract, ContinuousAccountReducer,
    ContinuousExecutionWitness,
)
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.evaluation import Mode5MetricPolicy
from quantbt.mode5.geometry.schema import EffectiveGeometry, OrderedConstraint

HOUR = DAY_NS // 24


def fixture(*, marks=(105., 100., 120., 108., 130.), metrics=None, geometry=None, purpose="selection", start="2020-12-30"):
    index = pd.date_range(start, periods=len(marks)*24, freq="h", tz="UTC")
    start, stop = int(index[0].value), int(index[-1].value)+HOUR
    preload = pd.date_range(index[0]-pd.Timedelta(days=1), index[-1], freq="h")
    data = pd.DataFrame({"close": 100.+np.arange(len(preload))*.01, "volume": 10.}, index=preload)
    p = dict(bar_interval_ns=HOUR, currency="USD", annual_periods=365., dd_weight=1., tail_weight=1.,
        tail_confidence=.95, min_daily_returns=1, min_closed_records=0, max_drawdown=1., min_utility=-10.)
    p.update(metrics or {})
    binding = Record.of(dict(metrics=p))
    policy = Mode5MetricPolicy(SimpleNamespace(binding=binding))
    execution = Record.of(dict(route="synthetic_account_fixture", backend="python",
        clock=dict(id="synthetic_bar_close", equity_clock="bar_close"),
        initial_state=dict(equity=100., position_policy="flat"), terminal_policy=dict(id="mark_only"),
        economics=dict(one_way_fee_rate=.0005, funding_rate=0.)))
    contract = ContinuousAccountContract(start, stop, geometry or EffectiveGeometry.from_ranges({"period": (2, 20, 1)}),
        Record.of(p), binding.identity, Record.of(dict(alpha=digest("public_fixture"), financial_provider=digest("original_fixture"))),
        execution, AccessPolicy("selection-rights", ("synthetic",), ("market-1",), stop+HOUR, purpose),
        AccessWitness("market-1", "synthetic", int(preload[0].value), stop, stop))
    result = SimpleNamespace(equity=pd.Series(np.repeat(marks, 24), index=index), initial_capital=100.,
        positions=pd.Series(np.ones(len(index)), index=index), fees=pd.Series(np.ones(len(index))*.001, index=index),
        funding=pd.Series(np.ones(len(index))*.002, index=index), margin=pd.Series(np.ones(len(index))*10., index=index),
        turnover=pd.Series(np.ones(len(index))*2., index=index), trades=(), liquidated=False,
        metadata=dict(backend="python", execution_contract="synthetic_bar_close"))
    role = "held_local_validation" if purpose == "diagnostic" else "formal_search"
    request = contract.request(data, {"period": 4}, role=role, scenario_seed=731)
    return contract, policy, data, index, result, request


def witness(contract, request, result, **changes):
    e = contract.execution.data
    return ContinuousExecutionWitness(request.identity, contract.source.identity, request.data_identity,
        request.point.identity, "actual-account-1", e["backend"], Record.of(e["clock"]), Record.of(e["initial_state"]),
        Record.of(dict(equity=float(result.equity.iloc[-1]), liquidated=bool(result.liquidated),
                       terminal_policy=e["terminal_policy"], **changes)))


def observe(f, **kwargs):
    c, p, data, index, result, request = f
    return ContinuousAccountReducer(c, p).observe(result, index, request=request,
        execution_witness=witness(c, request, result), **kwargs)


def test_whole_and_carried_annual_baselines_wealth_cost_conservation():
    f = fixture()
    c, p, _, _, result, _ = f
    actual = observe(f)
    assert p.evaluations == 1
    assert actual.execution.financial_execution_count == 1
    a, b = (r.data for r in actual.annual_views)
    assert (a["environment_id"], b["environment_id"]) == ("2020", "2021")
    assert a["baseline_equity"] == 100.
    assert b["baseline_equity"] == 100.
    assert b["baseline_source"] == "prior_actual_close"
    assert b["carried_watermark_equity"] == 105.
    assert (1+a["net_return"])*(1+b["net_return"])-1 == pytest.approx(actual.whole.data["net_return"])
    assert a["money_pnl"]+b["money_pnl"] == result.equity.iloc[-1]-100.
    for key in ("fees", "funding", "turnover"):
        assert a["stream_sums"][key]+b["stream_sums"][key] == pytest.approx(getattr(result, key).sum())
    assert actual.whole.data["net_return"] == pytest.approx(.30)
    assert actual.raw_whole_sharpe != np.mean([a["raw_sharpe"] or 0., b["raw_sharpe"] or 0.])
    assert actual.to_metadata()["annual_account_resets"] == 0
    assert actual.to_metadata()["public_v1_reset_behavior_changed"] is False


def test_annual_true_prior_close_differs_from_reset_initial_capital():
    f = fixture(marks=(110., 120., 126., 114., 138.))
    actual = observe(f)
    annual = actual.annual_views[1].data
    assert annual["baseline_equity"] == 120.
    assert annual["net_return"] == pytest.approx(138./120.-1)
    assert annual["net_return"] != pytest.approx(138./100.-1)
    assert annual["daily_returns"][0] == pytest.approx(126./120.-1)


def test_reuse_original_whole_policy_observation_without_calling_it_again():
    f = fixture()
    _, policy, _, index, result, _ = f
    row = policy.observe(result, index)
    actual = observe(f, whole_observation=row)
    assert policy.evaluations == 1
    assert actual.raw_whole_sharpe == row["raw_sharpe"]
    assert actual.whole.data["utility"] == Record.of(row).data["utility"]


def test_original_mode5_metric_units_and_component_semantics_are_unchanged():
    f = fixture()
    c, policy, _, index, result, _ = f
    actual = observe(f)
    prior = 100.
    for year, view in zip((2020, 2021), actual.annual_views, strict=True):
        selected = result.equity[index.year == year]
        oracle = Mode5MetricPolicy(policy.calibration).observe(SimpleNamespace(
            equity=selected, initial_capital=prior, trades=(), liquidated=False,
            metadata=result.metadata), selected.index)
        oracle = Record.of(oracle).data
        for key in ("raw_sharpe", "utility", "psr", "net_return", "max_drawdown", "daily_loss_es",
                    "daily_returns", "support_pass", "risk_pass", "quality_pass", "closed_record_unit"):
            assert view.data[key] == oracle[key]
        assert view.data["utility"]["unit"] == "decimal_return"
        prior = float(selected.iloc[-1])


@pytest.mark.parametrize("operation", [deepcopy, lambda x: pickle.loads(pickle.dumps(x, protocol=4)),
                                       lambda x: pickle.loads(pickle.dumps(x, protocol=5))])
def test_immutable_evidence_copy_pickle_and_result_mutation(operation):
    f = fixture()
    actual = observe(f)
    expected = actual.identity
    copy = operation(actual)
    f[4].equity.iloc[-1] = 80.
    assert actual.identity == copy.identity == expected
    with pytest.raises(ValueError):
        copy.observations.equity[-1] = 80.
    with pytest.raises(ValueError):
        copy.streams[0].values[0] = 0.
    detached = actual.whole.data
    detached["raw_sharpe"] = 999.
    assert actual.raw_whole_sharpe != 999.


@pytest.mark.parametrize("marks", [(100.,)*5, (100., 100., 0., 0., 0.), (100., 100., -10., -10., -10.)])
def test_undefined_zero_variance_and_bankrupt_marks_do_not_become_zero_score(marks):
    actual = observe(fixture(marks=marks))
    assert actual.raw_whole_sharpe is None
    assert actual.whole.data["psr"]["value"] is None
    if min(marks) <= 0:
        assert actual.whole.data["utility"]["status"] == "BANKRUPT"
        assert actual.whole.data["risk_pass"] is False
        assert actual.annual_views[1].data["utility"]["value"] is None


def test_future_bankrupt_suffix_does_not_change_prior_annual_measurement():
    positive = observe(fixture(marks=(110., 120., 126., 114., 138.)))
    bankrupt = observe(fixture(marks=(110., 120., 0., 0., 0.)))
    assert positive.annual_views[0] == bankrupt.annual_views[0]
    assert positive.whole != bankrupt.whole


def test_nonpositive_annual_entry_uses_original_empty_return_psr_contract():
    from quantbt.mode5.statistics.moments import classical_psr, moments

    actual = observe(fixture(marks=(100., 0., 0., 0., 0.)))
    annual = actual.annual_views[1].data
    assert annual["baseline_equity"] == 0.
    assert annual["raw_sharpe"] is None
    assert annual["metric_contract"] is None
    assert annual["daily_returns"] == []
    assert annual["daily_count"] == annual["utility"]["sample_count"] == 0
    assert annual["utility"]["status"] == "BANKRUPT"
    assert annual["psr"] == Record.of(classical_psr(moments([], backend="python")).to_metadata()).data
    assert annual["support_pass"] is False
    assert annual["risk_pass"] is False
    assert annual["quality_pass"] is False


def test_future_liquidation_event_does_not_mark_prior_annual_view_liquidated():
    f = fixture()
    c, p, _, index, result, request = f
    result.liquidated = True
    actual = ContinuousAccountReducer(c, p).observe(result, index, request=request,
        execution_witness=witness(c, request, result, liquidated_at_ns=int(index[48].value)))
    assert actual.annual_views[0].data["liquidated"] is False
    assert actual.annual_views[1].data["liquidated"] is True


def test_missing_campaign_and_fill_ledgers_are_not_zero_or_trade_regimes():
    actual = observe(fixture(metrics=dict(min_closed_records=2)))
    for view in (actual.whole, *actual.annual_views):
        assert view.data["closed_campaigns"] is None
        assert view.data["fills"] is None
        assert view.data["campaign_support_status"] == "UNAVAILABLE"
        assert view.data["support_pass"] is False
    zero = observe(fixture(marks=(100.,)*5),
        campaign_ledger=Record.of(dict(closed=[], open=[])), fill_ledger=Record.of(dict(rows=[])))
    assert zero.whole.data["fills"] == zero.whole.data["closed_campaigns"] == 0
    assert zero.whole.data["campaign_support_status"] == "RECORDED"


def test_actual_campaign_crossing_year_and_dated_fill_support():
    f = fixture()
    c, _, _, index, _, _ = f
    campaign = Record.of(dict(closed=[dict(start=index[0].isoformat(), end=index[-1].isoformat(), net_pnl=30.)], open=[]))
    fill = Record.of(dict(rows=[dict(timestamp=index[0].isoformat()), dict(timestamp=index[-1].isoformat())]))
    actual = observe(f, campaign_ledger=campaign, fill_ledger=fill)
    a, b = (v.data for v in actual.annual_views)
    assert a["closed_campaigns"] == 0 and a["open_campaigns"] == 1
    assert b["closed_campaigns"] == 1 and b["open_campaigns"] == 0
    assert a["fills"] == b["fills"] == 1
    assert a["money_pnl"]+b["money_pnl"] == 30.


@pytest.mark.parametrize("change", ["source", "data", "candidate", "clock", "initial", "terminal", "reset", "count"])
def test_execution_request_witness_mismatch_fails_closed(change):
    f = fixture()
    c, p, _, index, result, request = f
    w = witness(c, request, result)
    updates = dict(source=dict(source_identity=digest("other_source")), data=dict(data_identity=digest("other_data")),
        candidate=dict(effective_params_identity=digest("other_candidate")), clock=dict(clock=Record.of(dict(id="other_clock"))),
        initial=dict(initial_state=Record.of(dict(equity=50.))), terminal=dict(terminal_state=Record.of(dict(equity=999.))),
        reset=dict(account_policy="reset_flat"), count=dict(financial_execution_count=2))
    with pytest.raises(ValueError):
        ContinuousAccountReducer(c, p).observe(result, index, request=request, execution_witness=replace(w, **updates[change]))
    assert p.evaluations == 0


def test_future_suffix_market_mutation_and_attrs_change_request_identity():
    c, _, data, _, _, request = fixture()
    future = pd.concat([data, data.iloc[-1:].set_axis(pd.DatetimeIndex([pd.Timestamp(c.stop_ns, tz="UTC")]))])
    with pytest.raises(PermissionError, match="prefix"):
        c.request(future, {"period": 4})
    allowed = future.loc[future.index < pd.Timestamp(c.stop_ns, tz="UTC")]
    assert c.request(allowed, {"period": 4}, scenario_seed=731) == request
    future.iloc[-1, 0] = 99999.
    assert c.request(future.loc[future.index < pd.Timestamp(c.stop_ns, tz="UTC")], {"period": 4}, scenario_seed=731) == request
    changed = data.copy()
    changed.iloc[-1, 0] += 1
    assert c.request(changed, {"period": 4}).data_identity != request.data_identity
    changed = data.copy()
    changed.attrs["qty_step"] = .1
    assert c.request(changed, {"period": 4}).data_identity != request.data_identity


def test_role_and_cutoff_permissions_are_outside_mathematical_identity():
    c, _, data, _, _, _ = fixture()
    with pytest.raises(PermissionError):
        c.request(data, {"period": 4}, role="held_local_validation")
    with pytest.raises(PermissionError):
        replace(c, access=replace(c.access, cutoff_ns=c.stop_ns-1))
    with pytest.raises(PermissionError):
        replace(c, witness=AccessWitness("market-1", "synthetic", c.witness.start_ns, c.stop_ns, c.access.cutoff_ns+1))
    held = fixture(purpose="diagnostic")
    assert observe(held).request.role == "held_local_validation"
    with pytest.raises(PermissionError):
        held[0].request(held[2], {"period": 4}, role="formal_search")


def test_source_effective_geometry_cast_and_constraint_contract_preserved():
    geometry = EffectiveGeometry.from_ranges({"period": (2, 20, 1)}, casts=(("period", "truncate_integer_v1"),))
    f = fixture(geometry=geometry)
    c, p, data, index, result, _ = f
    request = c.request(data, {"period": 4.9})
    actual = ContinuousAccountReducer(c, p).observe(result, index, request=request, execution_witness=witness(c, request, result))
    assert actual.request.point.params == {"period": 4}
    assert actual.request.point.changes == (("period", "truncate_integer_v1"),)
    constrained = EffectiveGeometry.from_ranges({"period": (2, 20, 1), "slow": (2, 30, 1)},
        constraints=(OrderedConstraint(("period", "slow")),))
    c2 = replace(c, geometry=constrained)
    with pytest.raises(ValueError, match="INFEASIBLE"):
        c2.request(data, dict(period=10, slow=5))
    assert replace(c, source=Record.of(dict(alpha=digest("changed"), financial_provider=c.source.data["financial_provider"]))).identity != c.identity


@pytest.mark.parametrize("change", ["raw_sharpe", "utility", "daily_returns", "finance"])
def test_scalar_or_tampered_whole_observation_does_not_certify_actual_account(change):
    f = fixture()
    _, policy, _, index, result, _ = f
    row = policy.observe(result, index)
    if change == "raw_sharpe":
        row["raw_sharpe"] = 999.
    elif change == "utility":
        row["utility"]["value"] = 999.
    elif change == "daily_returns":
        row["daily_returns"][-1] = .99
    else:
        row["finance"]["equity"] = digest("other_account")
    with pytest.raises(ValueError):
        observe(f, whole_observation=row)


@pytest.mark.parametrize("change", ["empty", "scalar", "nonfinite", "clock", "reset", "liquidation_time", "stream_calendar"])
def test_missing_or_nonexecuted_account_cannot_be_admitted(change):
    f = fixture()
    c, p, _, index, result, request = f
    if change == "empty":
        index = index[:0]
        result.equity = result.equity.iloc[:0]
    elif change == "scalar":
        result.equity = 123.
    elif change == "nonfinite":
        result.equity.iloc[-1] = np.nan
    elif change == "clock":
        result.metadata["execution_contract"] = "next_open_instead"
    elif change == "reset":
        result.metadata["account_policy"] = "reset_flat"
    elif change == "liquidation_time":
        result.liquidated = True
    else:
        result.fees.index = result.fees.index+pd.Timedelta(hours=1)
    w = ContinuousExecutionWitness(request.identity, c.source.identity, request.data_identity, request.point.identity,
        "actual-1", "python", Record.of(c.execution.data["clock"]), Record.of(c.execution.data["initial_state"]),
        Record.of(dict(equity=130., liquidated=result.liquidated, terminal_policy=c.execution.data["terminal_policy"])))
    with pytest.raises((ValueError, TypeError)):
        ContinuousAccountReducer(c, p).observe(result, index, request=request, execution_witness=w)


def test_original_public_pct_equity_runs_once_then_reduces_without_replay():
    from quantbt import QuantBTEndpoint
    from quantbt.mode5.artifacts import file_identity
    from pathlib import Path
    f = fixture()
    c, p, data, index, _, request = f
    data = data.copy()
    data["open"] = data["close"]
    data["high"] = data["close"]+1.
    data["low"] = data["close"]-1.
    scored = data.loc[index].copy()
    signal = pd.Series(np.where(np.arange(len(index)) % 17 < 9, 1., -1.), index=index)
    endpoint = QuantBTEndpoint.pct_equity(initial_capital=100., leverage=1., alloc_per_trade=.1,
        fee_rate=.0005, slippage=.0001, use_funding=False, symbols=["PUBLIC_SYNTHETIC"])
    count = 0
    def original_execution():
        nonlocal count
        count += 1
        return endpoint.backtest(data=scored, signal=signal)
    result = original_execution()
    actual_backend = result.metadata.get("backend", endpoint.config.backend)
    clock = result.metadata.get("execution_contract")
    e = c.execution.data
    e["route"] = "pct_equity"
    e["backend"] = actual_backend
    e["economics"] = result.metadata["run_config"]
    e["clock"] = dict(id="original_pct_equity", equity_clock="bar_close", execution_contract=clock)
    e["terminal_policy"] = dict(id="original_endpoint_terminal")
    c = replace(c, execution=Record.of(e), source=Record.of(dict(
        alpha=file_identity(Path(__file__))["sha256"],
        financial_provider=file_identity(Path(__file__).parents[2]/"src/quantbt/endpoint.py")["sha256"])))
    request = c.request(data, {"period": 4}, scenario_seed=731)
    w = witness(c, request, result)
    row = p.observe(result, index)
    report = ContinuousAccountReducer(c, p).observe(result, index, request=request,
        execution_witness=w, whole_observation=row)
    assert count == p.evaluations == 1
    np.testing.assert_array_equal(report.observations.equity, result.equity.to_numpy())
    assert report.raw_whole_sharpe == row["raw_sharpe"]
    assert report.annual_views[1].data["baseline_equity"] == result.equity.loc[index[index.year == 2020]].iloc[-1]
    assert report.to_metadata()["financial_execution_count"] == 1


def test_recovery_verified_cell_annual_views_match_existing_account_authorities():
    from tools.mode5_diagnostics.evidence import FrozenBuffer
    from tools.mode5_research.panels import CandidateProvenance, UtilityPolicy, VerifiedCell, continuous_annual_rows
    f = fixture(marks=(105., 100., 110., 120., 108., 130.), start="2020-12-29")
    c, _, _, _, result, request = f
    actual = observe(f)
    reporting = ContinuousAccountReducer(c, f[1])._report_contract(c.start_ns, c.stop_ns, 100.)
    obs = actual.observations.with_derived_returns(reporting, partial_mask=np.zeros(6, dtype=bool), witness="actual UTC days")
    provenance = CandidateProvenance("study-1", "revision-1", "public-fixture", request.point.identity,
        digest(request.point.requested_json), digest(request.point.params), "branch-1", (0,), "actual-account-1",
        "design-1", "SYNTHETIC", "synthetic", "explicit analytic fixture, not alpha economic evidence",
        request.warmup_start_ns, c.stop_ns, c.access.cutoff_ns, c.access.cutoff_ns,
        "original-fixture", (("paths", digest("retained-fixture-path")),))
    cell = VerifiedCell(provenance, c.start_ns, c.stop_ns, reporting, obs,
        tuple(FrozenBuffer.from_array(n, getattr(result, n).to_numpy()) for n in ("positions", "fees", "funding", "turnover")),
        None, None, "{}", "PASS", None)
    rows = continuous_annual_rows(cell, utility_policy=UtilityPolicy(c.metric_binding_identity, 1., 1.))
    assert actual.whole.data["net_return"] == rows[0].metric("net_return").value
    assert actual.raw_whole_sharpe == pytest.approx(rows[0].metric("sharpe").value, abs=1e-12)
    for view, row in zip(actual.annual_views, rows[1:], strict=True):
        assert view.data["baseline_equity"] == row.environment_baseline.equity
        assert view.data["carried_watermark_equity"] == row.carried_watermark.equity
        assert view.data["money_pnl"] == row.money_pnl
        for name, value in (("net_return", view.data["net_return"]), ("sharpe", view.data["raw_sharpe"]),
                            ("drawdown", view.data["max_drawdown"]), ("daily_loss_es", view.data["daily_loss_es"]),
                            ("economic_utility", view.data["utility"]["value"]),
                            ("carried_watermark_drawdown", view.data["carried_watermark_drawdown"])):
            assert value == pytest.approx(row.metric(name).value, abs=1e-12)


def test_record_wrapped_whole_observation_is_a_supported_cold_input():
    f = fixture()
    row = Record.of(f[1].observe(f[4], f[3]))
    assert observe(f, whole_observation=row).raw_whole_sharpe == row.data["raw_sharpe"]


@pytest.mark.parametrize("change", ["metrics", "economics", "cutoff", "seed", "role"])
def test_request_identity_distinguishes_all_execution_and_permission_changes(change):
    c, _, data, _, _, request = fixture()
    if change == "metrics":
        m = c.metrics.data | dict(dd_weight=2.)
        c = replace(c, metrics=Record.of(m))
    elif change == "economics":
        e = c.execution.data
        e["economics"]["one_way_fee_rate"] *= 2
        c = replace(c, execution=Record.of(e))
    elif change == "cutoff":
        c = replace(c, access=replace(c.access, cutoff_ns=c.access.cutoff_ns+HOUR))
    new = c.request(data, {"period": 4}, role="selection_probe" if change == "role" else "formal_search",
        scenario_seed=732 if change == "seed" else 731)
    assert new.identity != request.identity


def test_scorer_invocation_is_not_mislabeled_as_internal_native_pass_count():
    f = fixture()
    c, p, _, index, result, request = f
    result.metadata.update(native_feedback_calls=37, final_native_calls=2)
    counts = Record.of(dict(native_feedback_calls=37, final_native_calls=2))
    w = replace(witness(c, request, result), internal_execution_counts=counts)
    report = ContinuousAccountReducer(c, p).observe(result, index, request=request, execution_witness=w)
    m = report.to_metadata()
    assert m["financial_execution_count"] == 1
    assert m["execution_count_unit"] == "original_scorer_invocations_not_internal_native_feedback_or_owner_passes"
    assert m["internal_execution_counts"] == counts.data
    assert m["internal_execution_counts_status"] == "RECORDED"
    unknown = observe(f).to_metadata()
    assert unknown["internal_execution_counts"] is None
    assert unknown["internal_execution_counts_status"] == "UNAVAILABLE"
    with pytest.raises(ValueError, match="internal execution count"):
        ContinuousAccountReducer(c, p).observe(result, index, request=request,
            execution_witness=replace(w, internal_execution_counts=Record.of(dict(native_feedback_calls=1))))


@pytest.mark.parametrize("field", ["closed_records", "closed_record_unit", "risk_pass", "quality_pass", "support_pass"])
def test_tampered_support_population_and_gates_are_rejected(field):
    f = fixture()
    row = f[1].observe(f[4], f[3])
    row[field] = 9 if field == "closed_records" else "inferred_campaigns" if field == "closed_record_unit" else not row[field]
    with pytest.raises(ValueError):
        observe(f, whole_observation=row)


def test_original_metric_policy_change_is_not_an_implicit_contract_upgrade():
    f = fixture()
    f[1].policy["dd_weight"] = 2.
    with pytest.raises(ValueError, match="metric policy/binding"):
        observe(f)
