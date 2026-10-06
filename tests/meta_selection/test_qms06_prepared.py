"""Q6-T01..08: original prepared evidence and pure portable host boundaries."""

from dataclasses import replace
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import optuna

from examples.wfo_meta_selection import PARAM_RANGES, make_endpoint, market
from quantbt import QuantBTEndpoint
from quantbt.backends.native_prepared_evaluation import (
    NativePreparedEvaluationRuntimeV1,
)
from quantbt.backends.native_wfo_public import NativePreparedPublicWfoUnsupported
from quantbt.optimization.meta_selection.common import MetaRecordError, digest
from quantbt.optimization.meta_selection.config import MetaHistoryContext
from quantbt.optimization.meta_selection.handoff import (
    dumps_handoff,
    export_fold_handoff,
    loads_handoff,
)
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.preparation.native_execution import NativeExecutionPreparationCache
from quantbt.preparation.cache import CachePolicy
from tools.build_qms06_candidate import load


RTOL, ATOL = 1e-10, 1e-10
optuna.logging.set_verbosity(optuna.logging.WARNING)
EXTENSION = Path(
    os.environ.get(
        "QMS06_NATIVE_EXTENSION",
        Path(__file__).resolve().parents[2]
        / ".maturin/qms06/_quantbt_native.cpython-312-x86_64-linux-gnu.so",
    )
)


def endpoint(
    mode="shadow",
    *,
    prepared="off",
    target="signal_notional",
    runtime="rust",
    strategy=None,
    strategy_policy="off",
    **changes,
):
    old = make_endpoint(mode, observer=True, min_origins=1, policy="reference")
    wf = old.config.walkforward_config
    wf = replace(
        wf,
        target_mode=target,
        metadata={
            **wf.metadata,
            "native_prepared_wfo": prepared,
            "prepared_wfo_strategy": strategy_policy,
        },
        **changes,
    )
    config = replace(
        old.config,
        walkforward_config=wf,
        target_runtime=runtime,
        walkforward_target_mode=target,
    )
    if strategy is not None:
        config = replace(config, strategy_class=strategy)
    if target == "pct_equity":
        config = replace(
            config, sizing="%_equity", fee=0.001, fee_rate=0.0005, alloc_per_trade=0.5
        )
    return QuantBTEndpoint(config)


def context(module=None, run_id="qms06-test", timeframe="1D"):
    return MetaHistoryContext(
        MetaHistory(),
        "public-sma-demo",
        "SYNTHETICUSD-linear",
        timeframe,
        run_id,
        native_module=module,
        # Declared historical completion budget, not measured live readiness.
        clock=lambda fold, stage, elapsed: fold.train_index[-1]
        + pd.Timedelta(seconds={"search": 10, "fit": 20, "seal": 30}[stage]),
    )


def execute(bt, *, module=None, data=None, timeframe="1D"):
    ctx = context(module, timeframe=timeframe)
    result = bt.backtest(
        data=market() if data is None else data,
        param_ranges=PARAM_RANGES,
        meta_history=ctx,
    )
    return result, ctx


def sidecar(result):
    return result.metadata["walk_forward"]["meta_selection"]


@pytest.fixture(scope="module")
def native():
    assert EXTENSION.is_file(), (
        "Build isolated QMS06 candidate; no fake/skip native evidence"
    )
    return load(EXTENSION)


@pytest.fixture
def candidate_cache(native, monkeypatch):
    original = NativeExecutionPreparationCache.__init__

    def init(self, policy=CachePolicy(), *, module=None):
        original(self, policy, module=native if module is None else module)

    monkeypatch.setattr(NativeExecutionPreparationCache, "__init__", init)
    return native


@pytest.fixture(scope="module")
def reference():
    return execute(endpoint("active"))


def assert_pools(reference, prepared):
    a, b = sidecar(reference), sidecar(prepared)
    assert len(a["tasks"]) == len(b["tasks"])
    for ta, tb, ra, rb in zip(
        a["tasks"], b["tasks"], a["records"], b["records"], strict=True
    ):
        assert ta.family == tb.family
        assert ta.data_cutoff == tb.data_cutoff
        assert ta.forward_start == tb.forward_start
        for key in (
            "search_completed_at",
            "fit_completed_at",
            "decision_sealed_at",
            "ready_at",
        ):
            assert ra[key] == rb[key]
        # Numerical terminal hashes differ by implementation; logical candidates
        # and roles must be identical, not binary provenance artifact bytes.
        assert [c.candidate_id for c in ta.candidates] == [
            c.candidate_id for c in tb.candidates
        ]
        assert ta.anchor.candidate_id == tb.anchor.candidate_id
        for ca, cb in zip(ta.candidates, tb.candidates, strict=True):
            x, y = ca.observation, cb.observation
            assert x.status == y.status
            assert x.sample_count == y.sample_count
            assert x.activity_count == y.activity_count
            assert x.input_signature == y.input_signature
            assert x.economics_id == y.economics_id
            np.testing.assert_allclose(
                [x.raw_sharpe, x.sample_std, x.initial_mark_equity, ca.objective],
                [y.raw_sharpe, y.sample_std, y.initial_mark_equity, cb.objective],
                rtol=RTOL,
                atol=ATOL,
            )
        for key in (
            "native_selected_params",
            "selected_params",
            "final_selection_reason",
            "matured_origins",
            "past_matured_forward_used_for_selection",
        ):
            assert ra[key] == rb[key]
        ma, mb = ra["proposal"], rb["proposal"]
        assert ma.guard == mb.guard
        for pa, pb in zip(ma.predictions, mb.predictions, strict=True):
            assert pa["candidate_id"] == pb["candidate_id"]
            assert pa["eligible"] == pb["eligible"]
            if pa["yhat"] is not None:
                np.testing.assert_allclose(
                    [pa["yhat"], pa["qhat"], pa["distance"]],
                    [pb["yhat"], pb["qhat"], pb["distance"]],
                    rtol=RTOL,
                    atol=ATOL,
                )
    np.testing.assert_allclose(reference.equity, prepared.equity, rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(
        reference.positions, prepared.positions, rtol=RTOL, atol=ATOL
    )
    np.testing.assert_allclose(
        reference.returns, prepared.returns, rtol=RTOL, atol=ATOL
    )
    from quantbt.core.types import BacktestResult
    from quantbt.core.results import BacktestResultV2

    if isinstance(reference, BacktestResult):
        # This legacy schema intentionally has no per-cost/accepted-unit trace.
        assert reference.metadata["walk_forward"]["target_mode"] == "pct_equity"
        assert isinstance(prepared, (BacktestResult, BacktestResultV2))
        assert not hasattr(reference, "fees") and not hasattr(reference, "funding")
    else:
        assert isinstance(reference, BacktestResultV2)
        assert isinstance(prepared, BacktestResultV2)
        for name in ("fees", "funding"):
            np.testing.assert_allclose(
                getattr(reference, name), getattr(prepared, name), rtol=RTOL, atol=ATOL
            )
    if "pct_equity_transition" in reference.metadata:
        # Public pct_equity positions are weights; check actual accepted units too.
        np.testing.assert_allclose(
            reference.metadata["pct_equity_transition"]["accepted_positions"],
            prepared.metadata["pct_equity_transition"]["accepted_positions"],
            rtol=RTOL,
            atol=ATOL,
        )


def test_q6_t01_full_public_prepared_reference_decision_sequence(
    reference, candidate_cache
):
    result, _ = execute(endpoint("active", prepared="require"))
    assert_pools(reference[0], result)
    assert any(
        r["final_selection_reason"] == "META_MODEL_PROPOSAL"
        for r in sidecar(result)["records"]
    )
    cache = result.metadata["walk_forward"]["prepared_scoring_cache"][
        "native_prepared_wfo"
    ]
    assert cache["native_batches"] > 0
    assert cache["metric_witness_rows"] == cache["native_rows"]
    assert cache["execution_clock"] == "close_target_v2_same_close"


def test_q6_t01_pct_equity_fresh_account_parity(candidate_cache):
    a, _ = execute(endpoint("shadow", target="pct_equity"))
    b, _ = execute(endpoint("shadow", prepared="require", target="pct_equity"))
    assert_pools(a, b)


def test_q6_t01_pct_equity_existing_native_account_units_and_cost_parity(
    candidate_cache,
):
    bt = endpoint("shadow", prepared="require", target="pct_equity")
    bt = QuantBTEndpoint(replace(bt.config, use_funding=True, funding_rate=0.0001))
    prepared, _ = execute(bt)
    # Independent ordinary endpoint run, never execution replay in the adapter.
    ordinary = QuantBTEndpoint(
        replace(
            bt.config,
            mode="pct_equity",
            backend="legacy",
            sizing="%_equity",
        )
    ).backtest(data=market(), signal=prepared.positions.iloc[:, 0])
    for name in ("equity", "returns", "fees", "funding", "positions"):
        np.testing.assert_allclose(
            getattr(ordinary, name), getattr(prepared, name), rtol=RTOL, atol=ATOL
        )
    np.testing.assert_allclose(
        ordinary.metadata["pct_equity_transition"]["accepted_positions"],
        prepared.metadata["pct_equity_transition"]["accepted_positions"],
        rtol=RTOL,
        atol=ATOL,
    )


def test_q6_t01_reference_numba_matches_prepared_rust(candidate_cache):
    a, _ = execute(endpoint("active", runtime="numba"))
    b, _ = execute(endpoint("active", prepared="require"))
    assert_pools(a, b)


def test_q6_t01_hourly_daily_metric_reducer_parity(candidate_cache):
    data = market(850)
    data.index = pd.date_range("2020-01-01", periods=len(data), freq="1h", tz="UTC")
    results = []
    for policy, runtime in (("off", "numba"), ("require", "rust")):
        bt = endpoint(
            "active",
            prepared=policy,
            runtime=runtime,
            split_mode="2020-01-12",
            split_frequency="weekly",
            train_window="10D",
        )
        result, _ = execute(bt, data=data, timeframe="1h")
        results.append(result)
    assert_pools(*results)


def test_q6_t02_short_daily_metric_window_not_substituted(candidate_cache):
    # Each IS shard is less than three UTC days: the reference's bar-return
    # fallback is not the native daily metric contract, even with the same alpha.
    data = market(180)
    data.index = pd.date_range("2020-01-01", periods=len(data), freq="1h", tz="UTC")
    bt = endpoint(
        prepared="require",
        split_mode="2020-01-05",
        split_frequency="weekly",
        train_window="3D",
    )
    with pytest.raises(NativePreparedPublicWfoUnsupported, match="three UTC days"):
        execute(bt, data=data, timeframe="1h")


def test_q6_t01_cost_funding_quantity_constraints(candidate_cache):
    from quantbt.core.schema import ExecutionConfig

    data = market()
    data.index = data.index + pd.Timedelta(hours=8)
    for target in ("signal_notional", "pct_equity"):
        outputs = []
        for policy in ("off", "require"):
            bt = endpoint("shadow", prepared=policy, target=target)
            bt = QuantBTEndpoint(
                replace(
                    bt.config,
                    use_funding=True,
                    funding_rate=pd.Series(0.0001, index=data.index),
                    slippage=0.0002,
                    execution=ExecutionConfig(slippage_bps=2.0),
                    qty_step=0.001,
                    min_qty=0.001,
                    min_notional=5.0,
                )
            )
            result, _ = execute(bt, data=data)
            outputs.append(result)
        assert_pools(*outputs)


class PreparedSMAStrategy:
    causal_cache_contract = "causal_parameter_independent_v1"

    def __init__(self, batch=False):
        self.batch = batch

    def __call__(self, data, params, train_index, test_index, fold):
        from examples.wfo_meta_selection import strategy

        return strategy(data, params, train_index, test_index, fold)

    def prepare_wfo(self, *, data, folds, static_config):
        from types import SimpleNamespace

        close = data["close"].copy()

        def generate(*, params, fold_id):
            signal = (close > close.rolling(int(params["window"])).mean()).astype(float)
            return {"signal": signal.to_numpy()}

        prepared = SimpleNamespace(
            causal_cache_contract=self.causal_cache_contract, generate=generate
        )
        if self.batch:

            def generate_batch(*, params_matrix, fold_id):
                return {
                    "signal": np.ascontiguousarray(
                        [
                            generate(params=params, fold_id=fold_id)["signal"]
                            for params in params_matrix
                        ],
                        dtype=np.float64,
                    )
                }

            prepared.generate_batch = generate_batch
        return prepared


@pytest.mark.parametrize("batch", [False, True], ids=["W1", "W2"])
def test_q6_t01_prepared_strategy_protocol_same_pool(candidate_cache, batch):
    a, _ = execute(endpoint("active", strategy=PreparedSMAStrategy()))
    b, _ = execute(
        endpoint(
            "active",
            prepared="require",
            strategy=PreparedSMAStrategy(batch=batch),
            strategy_policy="require",
        )
    )
    assert_pools(a, b)


def test_q6_t02_next_open_not_relabelled(candidate_cache):
    from quantbt.core.schema import ExecutionConfig, FillPricePolicy

    bt = endpoint(prepared="require")
    bt = QuantBTEndpoint(
        replace(
            bt.config,
            execution=ExecutionConfig(fill_price_policy=FillPricePolicy.NEXT_OPEN),
        )
    )
    with pytest.raises(NotImplementedError, match="close_target_v2"):
        execute(bt)


def test_q6_t02_zero_variance_not_placeholder_inference(candidate_cache):
    def flat(data, params, train_index, test_index, fold):
        return pd.Series(0.0, index=test_index)

    result, _ = execute(endpoint(prepared="require", strategy=flat))
    meta = sidecar(result)
    for task in meta["tasks"]:
        assert all(c.observation.status.value == "NO_VARIANCE" for c in task.candidates)
        assert all(
            c.observation.sample_std == 0.0 and c.observation.sample_count > 2
            for c in task.candidates
        )
    assert all(
        r["final_selection_reason"] == "META_NOT_APPLICABLE_METRIC"
        for r in meta["records"]
    )


@pytest.mark.parametrize(
    "mutation,status",
    [
        ("zero", "NO_VARIANCE"),
        ("one", "OUTCOME_FAILED"),
        ("negative", "OUTCOME_FAILED"),
        ("censored", "CENSORED"),
        ("nonfinite", "OUTCOME_FAILED"),
    ],
)
def test_q6_t02_metric_validity_has_authoritative_support(mutation, status):
    from quantbt.optimization.meta_selection.observer import canonical_metric_contract
    from quantbt.optimization.meta_selection.prepared import observe_prepared_score

    index = pd.date_range("2020-01-01", periods=5, tz="UTC")
    support = {
        "sample_count": np.array([4]),
        "sample_variance": np.array([0.0001]),
        "initial_mark_equity": np.array([19999.0]),
        "liquidated": np.array([False]),
        "contract_version": np.array([2]),
        "annualization_factor": np.array([365.0]),
    }
    if mutation == "zero":
        support["sample_variance"][0] = 0
    if mutation == "one":
        support["initial_mark_equity"][0] = 0
    if mutation == "negative":
        support["sample_variance"][0] = -1
    if mutation == "censored":
        support["liquidated"][0] = True
    if mutation == "nonfinite":
        support["sample_variance"][0] = np.nan
    raw = SimpleNamespace(
        metric_support=support,
        status=np.array([0]),
        sharpe=np.array([1.0]),
        report_trade_count=np.array([1]),
    )
    obs = observe_prepared_score(
        raw,
        0,
        index=index,
        contract=canonical_metric_contract(),
        economics_id="e",
        input_signature="input",
        initial_capital=20000,
        request_signature="r",
    )
    assert obs.status.value == status


def legacy_witness_gate(monkeypatch):
    """Exercise the retained missing-capability guard with the installed engine."""
    module = importlib.import_module("_quantbt_native")

    class WithoutWitness:
        def __getattr__(self, name):
            if name == "QMS_PREPARED_METRIC_SUPPORT_V1":
                return None
            return getattr(module, name)

    original = NativeExecutionPreparationCache.__init__

    def init(self, policy=CachePolicy(), *, module=None):
        original(self, policy, module=WithoutWitness() if module is None else module)

    monkeypatch.setattr(NativeExecutionPreparationCache, "__init__", init)
    return module.version()


def test_q6_t03_native_meta_require_does_not_upgrade_financial_wheel(native, monkeypatch):
    installed_version = legacy_witness_gate(monkeypatch)
    bt = endpoint("active", prepared="auto")
    wf = replace(
        bt.config.walkforward_config,
        meta_selection=replace(
            bt.config.walkforward_config.meta_selection, native_batch_policy="require"
        ),
    )
    result, _ = execute(
        QuantBTEndpoint(replace(bt.config, walkforward_config=wf)), module=native
    )
    cache = result.metadata["walk_forward"]["prepared_scoring_cache"][
        "native_prepared_wfo"
    ]
    assert cache["resolved_policy"] == "fallback"
    assert cache["native_batches"] == 0
    assert (
        sidecar(result)["records"][-1]["numeric_backend"]["native"]["version"]
        == "0.4.3.dev2"
    )
    assert importlib.import_module("_quantbt_native").version() == installed_version


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_runtime", "numba"),
        ("symbols", ["A", "B"]),
        ("target_mode", "portfolio"),
        ("scoring_trading_days", 252),
    ],
)
def test_q6_t02_incompatible_route_fails_before_search(
    field, value, candidate_cache, monkeypatch
):
    import optuna

    monkeypatch.setattr(
        optuna, "create_study", lambda *a, **k: pytest.fail("search before preflight")
    )
    bt = endpoint(prepared="require")
    expected = ValueError if field == "target_mode" else (MetaRecordError, NativePreparedPublicWfoUnsupported)
    reason = "endpoint and walkforward_config target_mode differ" if field == "target_mode" else None
    with pytest.raises(expected, match=reason):
        if field in {"target_mode", "scoring_trading_days"}:
            bt = QuantBTEndpoint(
                replace(
                    bt.config,
                    walkforward_config=replace(
                        bt.config.walkforward_config, **{field: value}
                    ),
                )
            )
        else:
            bt = QuantBTEndpoint(replace(bt.config, **{field: value}))
        execute(bt)


@pytest.mark.parametrize("field,value", [("fee_rate", 0.0004), ("slippage", 0.001)])
def test_q6_t02_pct_equity_economics_guard(field, value, candidate_cache):
    bt = endpoint(prepared="require", target="pct_equity")
    from quantbt.core.schema import ExecutionConfig

    config = replace(
        bt.config, execution=ExecutionConfig(slippage_bps=2.0), **{field: value}
    )
    with pytest.raises(NativePreparedPublicWfoUnsupported):
        execute(QuantBTEndpoint(config))


def test_q6_t03_published_require_fails_auto_observable(reference, monkeypatch):
    installed_version = legacy_witness_gate(monkeypatch)
    with pytest.raises(
        NativePreparedPublicWfoUnsupported, match="META_METRIC_SUPPORT_MISSING"
    ):
        execute(endpoint(prepared="require"))
    b, _ = execute(endpoint("active", prepared="auto"))
    assert_pools(reference[0], b)
    cache = b.metadata["walk_forward"]["prepared_scoring_cache"]["native_prepared_wfo"]
    assert cache["resolved_policy"] == "fallback"
    assert "META_METRIC_SUPPORT_MISSING" in cache["reason"]
    assert cache["native_batches"] == 0
    assert importlib.import_module("_quantbt_native").version() == installed_version


def test_q6_t04_detached_witness_buffers_survive_reset_and_close(candidate_cache):
    cache = NativeExecutionPreparationCache()
    frame = market(12)
    m = cache.prepare_market(
        timestamps_ns=frame.index.asi8,
        opens=frame.open.to_numpy()[:, None],
        highs=frame.high.to_numpy()[:, None],
        lows=frame.low.to_numpy()[:, None],
        closes=frame.close.to_numpy()[:, None],
        volumes=frame.volume.to_numpy()[:, None],
        funding=np.zeros((12, 1)),
        funding_mask=np.zeros(12, dtype=bool),
        symbols=["DEFAULT"],
    )
    template = cache.prepare_template(
        m,
        contract_sizes=np.ones(1),
        leverages=np.ones(1),
        fee_rates=np.array([0.0005]),
        initial_capital=20000,
        event_contract_code=2,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
    )
    req = cache.transient_direct_target_request(
        template,
        targets=np.ones((12, 1)),
        target_kind="units",
        timing="close_target_v2_same_close",
        output_profile=0,
    )
    runtime = NativePreparedEvaluationRuntimeV1(cache)
    from quantbt.backends.native_prepared_evaluation import NativePreparedWorkloadV1

    binding = runtime.bind_request(
        req,
        workload=NativePreparedWorkloadV1.TARGET_UNITS,
        candidate_id=0,
        fold_id=0,
        scenario_id=0,
    )
    result = runtime.evaluate_score_columns([binding], metric_support=True)
    before = {k: a.copy() for k, a in result.metric_support.items()}
    assert all(not a.flags.writeable for a in result.metric_support.values())
    runtime.reset()
    with pytest.raises((RuntimeError, ValueError), match="stale|generation"):
        runtime.evaluate_score_columns([binding], metric_support=True)
    runtime.close()
    cache.clear(force=True)
    for k in before:
        np.testing.assert_array_equal(result.metric_support[k], before[k])


@pytest.mark.parametrize("violation", ["columns", "dtype", "shape", "missing"])
def test_q6_t04_witness_abi_fails_closed(violation):
    from quantbt.backends.native_metric_support import (
        extract_prepared_metric_support_v1,
    )

    arrays = (
        np.array([4], dtype="uint64"),
        np.array([0.01], dtype="float64"),
        np.array([20000.0], dtype="float64"),
        np.array([False], dtype="bool"),
        np.array([2], dtype="uint16"),
        np.array([365.0], dtype="float64"),
    )
    if violation == "columns":
        arrays = arrays[:-1]
    elif violation == "dtype":
        arrays = (arrays[0].astype("float64"), *arrays[1:])
    elif violation == "shape":
        arrays = (arrays[0].reshape(1, 1), *arrays[1:])
    matrix = (
        SimpleNamespace()
        if violation == "missing"
        else SimpleNamespace(qms_metric_support_columns_v1=lambda: arrays)
    )
    with pytest.raises(RuntimeError, match="META_METRIC_SUPPORT"):
        extract_prepared_metric_support_v1(matrix, 1)


def test_q6_t04_source_lock_allows_only_reviewed_additive_witness():
    from hashlib import sha256
    import subprocess
    from tools.qms06_source_guard import without_qms06_witness
    from tools.qms_g01_source_guard import without_g01, verify

    root = Path(__file__).resolve().parents[2]
    name = "rust/crates/quantbt-engine/src/metrics_v2.rs"
    current = (root / name).read_bytes()
    verify()
    prior = without_g01(current, name)
    baseline = subprocess.check_output(["git", "show", f"3c69cb8:{name}"], cwd=root)
    assert without_qms06_witness(prior, name) == baseline
    assert b"self.m2 / denominator as f64" in current
    changed = current.replace(
        b"self.m2 / denominator as f64", b"self.m2 / self.count as f64"
    )
    with pytest.raises(AssertionError, match="unreviewed G01"):
        without_g01(changed, name)
    changed_prior = prior.replace(b"self.m2 / denominator as f64", b"self.m2 / self.count as f64")
    assert (
        sha256(without_qms06_witness(changed_prior, name)).digest()
        != sha256(baseline).digest()
    )
    name = "rust/native_event/src/prepared_evaluation.rs"
    current = (root / name).read_bytes()
    with pytest.raises(AssertionError, match="getter"):
        without_qms06_witness(
            current.replace(
                b"fn qms_metric_support_columns_v1", b"fn broken_metric_support"
            ),
            name,
        )


def test_q6_t05_boundary_counts_and_copies(candidate_cache):
    b, _ = execute(endpoint(prepared="require"))
    meta = sidecar(b)
    cache = b.metadata["walk_forward"]["prepared_scoring_cache"]["native_prepared_wfo"]
    assert cache["native_boundary_calls"] == cache["native_batches"]
    assert cache["metric_witness_output_bytes"] > 0
    assert len(meta["records"]) == len(meta["tasks"]) == len(meta["snapshots"])
    assert meta["observer_failures"] == 0
    assert all(r["numeric_backend"]["ffi_calls"] == 0 for r in meta["records"])


def test_q6_t05_native_meta_independent_from_prepared_financial(
    reference, candidate_cache
):
    bt = endpoint("active", prepared="require")
    wf = replace(
        bt.config.walkforward_config,
        meta_selection=replace(
            bt.config.walkforward_config.meta_selection, native_batch_policy="require"
        ),
    )
    result, _ = execute(
        QuantBTEndpoint(replace(bt.config, walkforward_config=wf)),
        module=candidate_cache,
    )
    assert_pools(reference[0], result)
    meta = sidecar(result)
    assert meta["records"][-1]["numeric_backend"]["ffi_calls"] <= 4 * len(
        meta["records"]
    )
    assert meta["records"][-1]["numeric_backend"]["input_owned_copy_bytes"] > 0
    assert all(
        r["numeric_backend"]["selected_backend_by_block"]["rank"] == "rust"
        for r in meta["records"]
    )


def restore(bundle, **changes):
    observations = [
        o
        for r in bundle.snapshot.revisions
        for o in [
            *(c.observation for c in r.task.candidates),
            *(c.observation for c in r.outcomes),
        ]
    ]
    options = dict(
        expected_handoff_id=bundle.handoff_id,
        available_as_of=bundle.decision.ready_at,
        authorized_corpora=bundle.snapshot.authorized_corpora,
        expected_family_id=bundle.task.family.family_id,
        verified_output_witnesses={o.output_ref: digest(o) for o in observations},
        reviewed_revision_ids=tuple(r.revision_id for r in bundle.snapshot.revisions),
    )
    options.update(changes)
    return loads_handoff(dumps_handoff(bundle), **options)


def test_q6_t06_complete_handoff_roundtrip(reference):
    result = reference[0]
    for r in sidecar(result)["records"]:
        bundle = export_fold_handoff(result, fold_id=r["fold_id"])
        restored = restore(bundle)
        assert restored.handoff_id == bundle.handoff_id
        assert restored.selected_params == bundle.selected_params
        assert restored.snapshot == bundle.snapshot
        assert restored.effective_at is None  # export does not activate
        if bundle.model:
            assert restored.model.schema == bundle.model.schema
            assert restored.model.scaler == bundle.model.scaler
            assert restored.model.coefficients == bundle.model.coefficients


@pytest.mark.parametrize(
    "violation", ["not_ready", "corpus", "family", "witnesses", "review"]
)
def test_q6_t06_handoff_restore_rejects_unpermitted(reference, violation):
    row = next(r for r in sidecar(reference[0])["records"] if r["proposal"].model_id)
    bundle = export_fold_handoff(reference[0], fold_id=row["fold_id"])
    changes = {
        "not_ready": {"available_as_of": bundle.decision.information_as_of},
        "corpus": {"authorized_corpora": ("forbidden",)},
        "family": {"expected_family_id": "wrong"},
        "witnesses": {"verified_output_witnesses": {}},
        "review": {"expected_handoff_id": "wrong"},
    }[violation]
    with pytest.raises(MetaRecordError):
        restore(bundle, **changes)


def test_q6_t06_late_effect_never_backdated(reference):
    row = sidecar(reference[0])["records"][-1]
    late = pd.Timestamp(row["effective_at"]) + pd.Timedelta(days=7)
    bundle = export_fold_handoff(
        reference[0], fold_id=row["fold_id"], effective_at=late
    )
    assert restore(bundle).effective_at == late
    with pytest.raises(MetaRecordError, match="CLOCK"):
        replace(bundle, effective_at=bundle.decision.information_as_of)


def test_q6_t06_future_model_cannot_replace_earlier_snapshot(reference):
    rows = [r for r in sidecar(reference[0])["records"] if r["proposal"].model_id]
    earlier = export_fold_handoff(reference[0], fold_id=rows[0]["fold_id"])
    later = export_fold_handoff(reference[0], fold_id=rows[-1]["fold_id"])
    assert later.model.information_as_of > earlier.task.data_cutoff
    forged = replace(
        earlier.decision,
        model_id=later.model.model_id,
        training_snapshot_id=later.snapshot.snapshot_id,
    )
    with pytest.raises(MetaRecordError, match="FRONTIER|LINEAGE"):
        replace(earlier, model=later.model, snapshot=later.snapshot, decision=forged)


def test_q6_t06_cached_older_model_with_its_exact_snapshot_is_permitted(reference):
    from quantbt.optimization.meta_selection.handoff import DecisionHandoff
    from quantbt.optimization.meta_selection.model import (
        FitOutcome,
        schema_from_payload,
    )
    from quantbt.optimization.meta_selection.selection import MetaSelector

    rows = [r for r in sidecar(reference[0])["records"] if r["proposal"].model_id]
    old = export_fold_handoff(reference[0], fold_id=rows[0]["fold_id"])
    current = export_fold_handoff(reference[0], fold_id=rows[-1]["fold_id"])
    proposal = MetaSelector().propose(
        current.task,
        FitOutcome(old.model, "FIT_VALID", old.model.origin_count),
        schema=schema_from_payload(old.model.schema),
        ready_at=current.decision.ready_at,
    )
    bundle = DecisionHandoff(
        current.task,
        proposal,
        old.model,
        old.snapshot,
        dict(current.native_selection_reason),
    )
    assert restore(bundle).model.model_id == old.model.model_id


def test_q6_t06_corrupt_unknown_fields_and_size(reference):
    import json

    bundle = export_fold_handoff(reference[0], fold_id=0)
    doc = json.loads(dumps_handoff(bundle))
    doc["payload"]["broker_order"] = "forbidden"
    doc["content_digest"] = digest(doc["payload"])
    with pytest.raises(MetaRecordError):
        loads_handoff(
            json.dumps(doc),
            expected_handoff_id=bundle.handoff_id,
            available_as_of=bundle.decision.ready_at,
            authorized_corpora=bundle.snapshot.authorized_corpora,
            expected_family_id=bundle.task.family.family_id,
        )
    with pytest.raises(MetaRecordError, match="SIZE"):
        restore(bundle, max_bytes=1)


def test_q6_t07_host_read_is_pure_and_detached(reference):
    bundle = export_fold_handoff(reference[0], fold_id=0)
    before = dumps_handoff(bundle)
    params = bundle.read_params(available_as_of=bundle.decision.ready_at)
    params["window"] = -1
    assert dumps_handoff(bundle) == before
    assert set(
        vars(importlib.import_module("quantbt.optimization.meta_selection.handoff"))
    ).isdisjoint({"broker", "orders", "account"})


def test_q6_t07_pure_selector_example_no_financial_replay(reference, monkeypatch):
    from examples.wfo_meta_handoff import consume_reviewed

    row = sidecar(reference[0])["records"][-1]
    bundle = export_fold_handoff(reference[0], fold_id=row["fold_id"])
    monkeypatch.setattr(
        QuantBTEndpoint,
        "backtest",
        lambda *a, **k: pytest.fail("handoff replayed financial execution"),
    )
    before = dumps_handoff(bundle)
    assert (
        consume_reviewed(bundle, now=bundle.decision.ready_at) == bundle.selected_params
    )
    assert (
        consume_reviewed(bundle, now=bundle.decision.ready_at) == bundle.selected_params
    )
    assert dumps_handoff(bundle) == before


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_q6_t08_w3_untyped_config_unsupported_before_prepare(mode):
    from quantbt.backends.reactive_wfo import (
        ReactivePreparedWfoRuntimeV1,
        ReactiveWalkForwardUnsupported,
    )

    config = SimpleNamespace(meta_selection=SimpleNamespace(mode=mode))
    with pytest.raises(
        ReactiveWalkForwardUnsupported, match="typed WalkForwardConfig required"
    ):
        ReactivePreparedWfoRuntimeV1(
            endpoint=None, data=None, strategy_factory=None, walkforward_config=config
        )
