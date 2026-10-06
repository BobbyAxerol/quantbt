"""E04 original aggregate labels, independent accounting and causal admission."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from examples.wfo_meta_portfolio import SYMBOLS, PARAM_RANGES, execute, make_endpoint, market, strategy
from quantbt import QuantBTEndpoint
from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.domains import route_metadata
from quantbt.optimization.meta_selection.domains.portfolio_contract import (
    portfolio_execution_contract, validate_portfolio_market, validate_portfolio_payload)
from quantbt.optimization.meta_selection.domains.portfolio_witness import PortfolioMetricWitness
from quantbt.optimization.meta_selection.observer import ResultMetricAdapter, canonical_metric_contract, economics_identity, market_signature


def meta(result):
    return result.metadata["walk_forward"]["meta_selection"]


@pytest.fixture(scope="module")
def runs():
    return {mode: execute(mode, support=1) for mode in ("off", "shadow", "active")}


def exact_accounts(a, b):
    for key in ("equity", "returns", "positions", "fees", "funding", "margin", "diagnostics"):
        np.testing.assert_array_equal(getattr(a, key), getattr(b, key))
    for key in ("target_units_report", "accepted_units_report", "turnover_series", "slippage_series"):
        np.testing.assert_array_equal(a.metadata[key], b.metadata[key])


def test_e04_t01_capability_is_software_opt_in_not_economic_or_w3_promotion():
    row = route_metadata("portfolio")
    assert row["meta_route_activated"] and row["meta_software_status"] == "SOFTWARE_VALIDATED_OPT_IN"
    assert row["meta_empirical_status"] == "REAL_ALPHA_OWNER_REVIEW_PENDING"
    assert row["meta_optimization_modes"] == ("mode_4_is_only_robust",)
    assert row["meta_optimization_schedules"] == ("per_fold_causal",)


def test_e04_t04_off_shadow_exact_rng_pool_params_and_continuous_account(runs):
    _, off, _ = runs["off"]
    _, shadow, _ = runs["shadow"]
    a, b = (r.metadata["walk_forward"] for r in (off, shadow))
    assert a["params_by_fold"] == b["params_by_fold"]
    pd.testing.assert_frame_equal(a["trial_table"], b["trial_table"])
    exact_accounts(off, shadow)
    for mode in ("shadow", "active"):
        side = meta(runs[mode][1])
        d = side["domain_adapter"]
        assert side["observer_failures"] == 0
        assert d["financial_delegate_calls"] == d["original_observations"] == side["observer_attempts"]
        assert d["input_bindings"] == side["observer_attempts"]
        assert d["financial_replays"] == 0 and d["closed"]
        assert d["symbol_average_metrics"] is False and d["empirical_promotion"] is False
        assert all(not r["current_outer_oos_used_for_selection"] for r in side["records"])
        assert len({t.family.family_id for t in side["tasks"]}) == 1


def test_e04_t04_final_account_is_original_stitched_position_run_not_fold_equity(runs):
    endpoint, result, _ = runs["active"]
    stitched = result.metadata["walk_forward_result"].oos_output
    original = QuantBTEndpoint(replace(endpoint.config, mode="portfolio"))
    rebuilt = original.backtest(data=market(), positions=stitched, symbols=list(SYMBOLS))
    exact_accounts(result, rebuilt)


def test_e04_t03_every_is_and_forward_observation_uses_original_aggregate_report(runs):
    endpoint, result, context = runs["shadow"]
    diagnostic = QuantBTEndpoint(replace(endpoint.config, mode="portfolio"))
    data = market()
    first = meta(result)["tasks"][0]
    candidate = first.candidates[0]
    # Candidate capture records the original full IS diagnostic (not symbol averages).
    index = pd.date_range(first.is_start, first.is_end, freq="D")
    output = strategy(data, candidate.effective_params, index, index, None)
    reference = diagnostic.backtest(data={s: f.loc[index] for s, f in data.items()}, positions=output)
    assert candidate.observation.raw_sharpe == reference.full_report(trading_days=365, scope="full")["sharpe"]
    revision = next(r for r in context.history._revisions.values() if r.task.task_id == first.task_id)
    outcome = revision.outcomes[0]
    forward_candidate = next(c for c in first.candidates if c.evaluation_id == outcome.evaluation_id)
    forward_index = pd.date_range(first.forward_start, first.forward_end, freq="D")
    positions = strategy(data, forward_candidate.effective_params, index, forward_index, None)
    forward = diagnostic.backtest(data={s: f.loc[forward_index] for s, f in data.items()}, positions=positions)
    assert outcome.observation.raw_sharpe == forward.full_report(trading_days=365, scope="full")["sharpe"]
    # All public observer calls are original results; no invented proxy support.
    assert all(c.observation.verification == "original_result" for t in meta(result)["tasks"] for c in t.candidates)


@pytest.mark.parametrize("sizing", ["signal", "signal_notional", "notional", "unit", "%_equity",
    "target_weight", "target_notional", "target_units", "fixed_notional", "gross_exposure", "net_exposure"])
def test_e04_t02_all_original_sizing_dispatches_off_shadow(sizing):
    a = execute("off", sizing=sizing)[1]
    b = execute("shadow", sizing=sizing)[1]
    exact_accounts(a, b)
    assert a.metadata["walk_forward"]["params_by_fold"] == b.metadata["walk_forward"]["params_by_fold"]
    assert meta(b)["observer_failures"] == 0


@pytest.mark.parametrize("mode", ["longshort", "market_neutral", "directional", "equal_weight", "risk_parity", "beta_neutral"])
def test_e04_t02_all_original_modes_off_shadow(mode):
    kwargs = dict(portfolio_mode=mode, sizing="signal_notional", risk_lookback=10)
    if mode == "beta_neutral":
        kwargs["betas"] = dict(zip(SYMBOLS, (1., 1.3)))
    a = execute("off", **kwargs)[1]
    b = execute("shadow", **kwargs)[1]
    exact_accounts(a, b)
    assert meta(b)["observer_failures"] == 0


@pytest.mark.parametrize("representation", ["frame", "mapping"])
def test_e04_t01_exact_position_matrix_or_series_mapping(representation):
    idx = market()[SYMBOLS[0]].index[:3]
    output = pd.DataFrame({s: [0., 1., -1.] for s in SYMBOLS}, index=idx)
    if representation == "mapping":
        output = {s: output[s] for s in SYMBOLS}
    validate_portfolio_payload(output, idx, SYMBOLS)
    bad = output.iloc[::-1] if isinstance(output, pd.DataFrame) else {s: v.iloc[::-1] for s, v in output.items()}
    with pytest.raises(MetaRecordError, match="exact ordered"):
        validate_portfolio_payload(bad, idx, SYMBOLS)


@pytest.mark.parametrize("change", ["order", "missing", "extra", "nan", "infinite"])
def test_e04_t01_invalid_targets_fail_closed(change):
    idx = market()[SYMBOLS[0]].index[:3]
    frame = pd.DataFrame(1., index=idx, columns=SYMBOLS)
    if change == "order": frame = frame.loc[:, list(reversed(SYMBOLS))]
    if change == "missing": frame = frame.drop(columns=SYMBOLS[0])
    if change == "extra": frame["EXTRA"] = 1.
    if change in {"nan", "infinite"}: frame.iloc[0, 0] = np.nan if change == "nan" else np.inf
    with pytest.raises(MetaRecordError, match="META_DOMAIN_INPUT_MISMATCH"):
        validate_portfolio_payload(frame, idx, SYMBOLS)


@pytest.mark.parametrize("change", ["naive", "async", "extra", "bad_high", "infinite"])
def test_e04_t01_bad_market_fails_before_first_optuna_trial(change, monkeypatch):
    import optuna
    calls = []
    monkeypatch.setattr(optuna, "create_study", lambda *a, **k: calls.append(True))
    data = market()
    if change == "naive":
        for f in data.values(): f.index = f.index.tz_localize(None)
    if change == "async": data[SYMBOLS[1]] = data[SYMBOLS[1]].iloc[1:]
    if change == "extra": data["EXTRA"] = data[SYMBOLS[0]]
    if change == "bad_high": data[SYMBOLS[0]].iloc[0, data[SYMBOLS[0]].columns.get_loc("high")] = 1.
    if change == "infinite": data[SYMBOLS[0]].iloc[0, 0:4] = np.inf
    with pytest.raises(ValueError): execute("shadow", data=data)
    assert not calls


@pytest.mark.parametrize("backend", ["legacy_portfolio", "nautilus", "rust"])
def test_e04_t01_mismatched_execution_authority_is_rejected(backend):
    endpoint = make_endpoint()
    with pytest.raises(MetaRecordError, match="final and IS authority"):
        portfolio_execution_contract(replace(endpoint.config, backend=backend), endpoint.config.walkforward_config)


def test_e04_t01_raw_async_rejected_but_explicit_union_nan_is_not_resampled():
    data = market()
    index = data[SYMBOLS[0]].index
    data[SYMBOLS[1]].loc[index[::5], ["close", "high", "low"]] = np.nan
    _, a, _ = execute("off", data=data)
    _, b, _ = execute("shadow", data=data)
    exact_accounts(a, b)
    assert meta(b)["observer_failures"] == 0


def test_e04_t04_prepared_arrays_and_witness_reference_exact(runs):
    _, reference, _ = execute("shadow", cache=False, witness=False, support=1)
    prepared = runs["shadow"][1]
    pd.testing.assert_frame_equal(reference.metadata["walk_forward"]["trial_table"],
                                  prepared.metadata["walk_forward"]["trial_table"])
    for a, b in zip(meta(reference)["tasks"], meta(prepared)["tasks"], strict=True):
        assert replace(a, wall_generated_at=b.wall_generated_at) == b
    for a, b in zip(meta(reference)["records"], meta(prepared)["records"], strict=True):
        for key in ("selected_params", "selected_evaluation_id", "native_selected_evaluation_id",
                    "final_selection_reason", "matured_origins"):
            assert a[key] == b[key]
        # Revisions bind measured wall-generation clocks, even on unchanged runs.
        assert len(a["training_revision_ids"]) == len(b["training_revision_ids"])
        assert a["proposal"].predictions == b["proposal"].predictions
    exact_accounts(reference, prepared)
    assert meta(reference)["witness_reuse"] is None
    assert meta(prepared)["witness_reuse"]["owned_row_hash_bytes"] == 2*730*8


def test_e04_t04_future_market_funding_suffix_cannot_change_first_decision(runs):
    data = market()
    index = data[SYMBOLS[0]].index
    rates = {s: pd.Series(.0001, index=index) for s in SYMBOLS}
    original = QuantBTEndpoint(replace(make_endpoint("active", support=1).config,
                                      use_funding=True, funding_rate=rates))
    from quantbt.optimization.meta_selection.history import MetaHistory
    def run(frame, funding):
        context = replace(runs["active"][2], history=MetaHistory())
        return QuantBTEndpoint(replace(original.config, funding_rate=funding)).backtest(
            data=frame, param_ranges=PARAM_RANGES, meta_history=context)
    a = run(data, rates)
    changed = {s: f.copy() for s, f in data.items()}
    altered = {s: r.copy() for s, r in rates.items()}
    for s in SYMBOLS:
        changed[s].loc[index >= "2021-04-01", ["open", "high", "low", "close", "volume"]] *= 2
        altered[s].loc[index >= "2021-04-01"] *= 3
    b = run(changed, altered)
    assert meta(a)["tasks"][0].candidates == meta(b)["tasks"][0].candidates
    for key in ("family_id", "selected_params", "selected_evaluation_id", "training_snapshot_id"):
        assert meta(a)["records"][0][key] == meta(b)["records"][0][key]


@pytest.mark.parametrize("field", ["risk_lookback", "betas", "qty_step", "portfolio_mode", "funding", "universe"])
def test_e04_t04_family_isolates_financial_policies(field):
    cfg = make_endpoint().config
    a = portfolio_execution_contract(cfg, cfg.walkforward_config)
    changes = dict(risk_lookback=cfg.risk_lookback+1) if field == "risk_lookback" else {
        "betas":dict(betas={SYMBOLS[0]: 1., SYMBOLS[1]:1.3}),
        "qty_step":dict(qty_step=.01), "portfolio_mode":dict(portfolio_mode="equal_weight"),
        "funding":dict(use_funding=True), "universe":dict(symbols=list(reversed(SYMBOLS)))}[field]
    other = replace(cfg, **changes)
    b = portfolio_execution_contract(other, cfg.walkforward_config)
    assert (a.semantic_id, economics_identity(cfg, symbols=list(SYMBOLS))) != (
        b.semantic_id, economics_identity(other, symbols=list(SYMBOLS)))


def short_account(*, fee=.001, slip=2., funding=False, capital=20000., leverage=3.):
    idx = pd.date_range("2024-01-01", periods=5, freq="8h", tz="UTC")
    prices = np.array([[100., 50.], [100., 50.], [110., 45.], [90., 55.], [100., 50.]])
    data = {s: pd.DataFrame({c: prices[:, j] for c in ("open", "high", "low", "close")}, index=idx)
            for j, s in enumerate(SYMBOLS)}
    target = pd.DataFrame([[0.,0.], [1.,-2.], [1.,-2.], [-1.,2.], [0.,0.]], index=idx, columns=SYMBOLS)
    bt = QuantBTEndpoint.portfolio(symbols=list(SYMBOLS), portfolio_mode="longshort", hedge_type="target_units",
        initial_capital=capital, leverage=leverage, fee_rate=fee, slippage_bps=slip,
        use_funding=funding, funding_rate={SYMBOLS[0]: .001, SYMBOLS[1]: .002})
    return bt, bt.backtest(data=data, positions=target), data, target


@pytest.mark.parametrize("funding", [False, True])
def test_e04_t03_independent_shared_account_reversal_delta_cost_margin_and_funding(funding):
    bt, result, data, target = short_account(funding=funding)
    qty = target.to_numpy()
    price = np.column_stack([data[s].close for s in SYMBOLS])
    previous = np.vstack([np.zeros(2), qty[:-1]])
    delta = qty-previous
    turnover = (np.abs(delta)*price*(1+np.sign(delta)*.0002)).sum(axis=1)
    fees = turnover*.001
    slippage = (np.abs(delta)*price).sum(axis=1)*.0002
    marks = (previous*np.vstack([np.zeros(2), np.diff(price, axis=0)])).sum(axis=1)
    fund = (previous*price*np.array([.001, .002])).sum(axis=1) if funding else np.zeros(5)
    expected = 20000+np.cumsum(marks-fees-slippage-fund)
    np.testing.assert_array_equal(result.positions, qty)
    np.testing.assert_allclose(result.fees, fees, atol=1e-12)
    np.testing.assert_allclose(result.funding, fund, atol=1e-12)
    np.testing.assert_allclose(result.metadata["turnover_series"], turnover, atol=1e-12)
    np.testing.assert_allclose(result.metadata["slippage_series"], slippage, atol=1e-12)
    np.testing.assert_allclose(result.equity, expected, atol=1e-10)
    np.testing.assert_allclose(result.margin.iloc[:, 0], (np.abs(qty)*price).sum(axis=1)/3., atol=1e-10)


def test_e04_t03_post_cost_margin_is_shared_not_independent_symbol_buying_power():
    _, result, _, _ = short_account(capital=200., leverage=1.)
    assert result.positions.iloc[1].eq(0.).all()
    assert result.diagnostics.rejected_rebalances.iloc[1]
    assert result.fees.iloc[1] == 0.


@pytest.mark.parametrize("field", ["volume", "funding", "replace_frame"])
def test_e04_t06_witness_exact_reuse_mutation_release_and_bounded_retention(field):
    cfg = replace(make_endpoint().config, mode="portfolio")
    data = market()
    idx = data[SYMBOLS[0]].index
    cfg = replace(cfg, funding_rate={s: pd.Series(.0001, index=idx) for s in SYMBOLS})
    witness = PortfolioMetricWitness(data, config=cfg, max_entries=2, max_bytes=1500)
    for stop in (100, 101, 102, 103):
        prefix = {s: f.iloc[:stop] for s, f in data.items()}
        index = idx[50:stop]
        assert witness.market_signature(prefix, index) == market_signature(prefix, index, config=cfg)
        assert witness.market_signature(prefix, index) == witness.market_signature(prefix, index)
    assert witness.metadata["retained_bytes"] <= 1500 and witness.metadata["entries"] <= 2
    assert witness.metadata["owned_row_hash_bytes"] == 2*730*8
    if field == "volume": data[SYMBOLS[1]].iloc[0, -1] *= 2
    if field == "funding": cfg.funding_rate[SYMBOLS[1]].iloc[0] *= 2
    if field == "replace_frame": data[SYMBOLS[1]] = data[SYMBOLS[1]].copy()*2
    with pytest.raises(MetaRecordError, match="MUTATED"): witness.validate_source()
    witness.close()
    assert witness.closed and witness.metadata["owned_row_hash_bytes"] == 0
    assert not witness.children and witness.source is None
    with pytest.raises(MetaRecordError, match="CLOSED"): witness.market_signature(data, idx)


def test_e04_t06_accounting_witness_rejects_unbound_and_detects_cost_only_changes():
    bt, result, data, _ = short_account()
    adapter = ResultMetricAdapter(canonical_metric_contract())
    def observe(r):
        return adapter.observe(r, expected_index=result.equity.index,
            economics_id=economics_identity(bt.config), input_signature=market_signature(data, result.equity.index, config=bt.config))
    a = observe(result)
    altered = replace(result, fees=result.fees+1.)
    assert a.output_ref != observe(altered).output_ref
    broken = replace(result, metadata={k:v for k,v in result.metadata.items() if k != "target_units_report"})
    with pytest.raises(MetaRecordError, match="accounting buffers missing"): observe(broken)


def test_e04_t06_exact_source_guard_still_rejects_unreviewed_bytes():
    from tools.qms_e04_source_guard import ALLOW, ROOT, verify, without_e04_portfolio
    assert verify()["financial_numeric_source_unchanged"]
    for name in ALLOW:
        with pytest.raises(AssertionError, match="unreviewed"):
            without_e04_portfolio((ROOT/name).read_bytes()+b"\n# unreviewed\n", name)


def mapping_strategy(data, params, train_index, test_index, fold):
    frame = strategy(data, params, train_index, test_index, fold)
    return {s: frame[s] for s in SYMBOLS}


def test_e04_t01_public_mapping_positions_match_dataframe_account(runs):
    from quantbt.optimization.meta_selection.history import MetaHistory
    bt = QuantBTEndpoint(replace(make_endpoint().config, strategy_class=mapping_strategy))
    ctx = replace(runs["shadow"][2], history=MetaHistory())
    result = bt.backtest(data=market(), param_ranges=PARAM_RANGES, meta_history=ctx)
    exact_accounts(result, runs["shadow"][1])
    assert meta(result)["observer_failures"] == 0


def test_e04_t04_active_uses_actual_learned_params_and_excludes_other_family(runs):
    from tests.meta_selection.test_qms05_public import reviewed_history
    history, revision = reviewed_history(meta(runs["shadow"][1])["tasks"][0], positive=None)
    _, learned, _ = execute("active", history=history, support=1)
    records = meta(learned)["records"]
    assert records[0]["matured_origins"] == 1
    assert any(r["selected_evaluation_id"] != r["native_selected_evaluation_id"] for r in records)
    assert learned.metadata["walk_forward"]["params_by_fold"] == {
        r["fold_id"]: r["selected_params"] for r in records}
    # Same-symbol but different economics/financial family cannot enter this fit.
    from quantbt.optimization.meta_selection.history import MetaHistory
    from quantbt.optimization.meta_selection.history import SealedTaskRevision
    altered = replace(revision.task, family=replace(revision.task.family, scorer_contract_id="different-shared-account-policy"))
    other = SealedTaskRevision(altered, replace(revision.panel, task_id=altered.task_id),
        tuple(replace(o, task_id=altered.task_id) for o in revision.outcomes),
        revision.revision_available_at, verification="reviewed_import")
    wrong = MetaHistory()
    wrong.append(other)
    result = execute("active", history=wrong, support=1, observer=False)[1]
    assert all(r["matured_origins"] == 0 for r in meta(result)["records"])


def test_e04_t03_risk_parity_warmup_no_future_or_implicit_backward_fill():
    data = {s: f.iloc[:30].copy() for s, f in market().items()}
    idx = data[SYMBOLS[0]].index
    target = pd.DataFrame(1., index=idx, columns=SYMBOLS)
    bt = QuantBTEndpoint.portfolio(symbols=list(SYMBOLS), portfolio_mode="risk_parity",
        hedge_type="gross_exposure", risk_lookback=10, alloc_per_trade=.5,
        initial_capital=20000., leverage=3., fee_rate=.001, use_funding=False)
    a = bt.backtest(data=data, positions=target)
    altered = {s: f.copy() for s, f in data.items()}
    for f in altered.values(): f.iloc[20:, 0:4] *= 2.
    b = bt.backtest(data=altered, positions=target)
    np.testing.assert_array_equal(a.positions.iloc[:20], b.positions.iloc[:20])
    assert not a.positions.iloc[:10].to_numpy().any()
    assert not a.fees.iloc[:10].to_numpy().any()
