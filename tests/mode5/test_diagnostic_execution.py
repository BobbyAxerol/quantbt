"""Actual prepared Rust/Python fixtures: retained outputs, fresh state, parity."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256

import numpy as np

from tests.native_event.test_rust_batched_full_tape import _bars, _fixture
from tests.mode5.test_diagnostic_planner import key, plan, reuse
from tools.mode5_diagnostics import AccessPolicy, AccessWitness, ExecutionEvidence


def prepared_fixture(n=None):
    backend, frame, market, commands, compiled, runner = _fixture()
    if n is not None:
        from quantbt import RustBatchedRunner
        frame = _bars(n)
        market = backend.prepare_market_arrays(datetime_index=frame.index,
            closes={"BTC": frame.close}, highs={"BTC": frame.high}, lows={"BTC": frame.low}, symbols=["BTC"])
        compiled = backend.compile_order_commands(frame.index, commands, symbols=["BTC"])
        runner = RustBatchedRunner(idx=frame.index, symbols=["BTC"], market_arrays=market,
            contract_size=1., leverage=5., fee_rate=.0002, initial_capital=10000.,
            maintenance_ratio=0., slippage=.0002, use_funding=False)
    market_sha = sha256(frame.index.asi8.tobytes()+frame.to_numpy().tobytes()+b"BTC/OHLCV").hexdigest()
    k = replace(key(), market_snapshot=market_sha)
    w = AccessWitness("prepared-synthetic-v1", "synthetic", int(frame.index[0].value),
        int(frame.index[-1].value)+1, int(frame.index[-1].value)+1)
    p = AccessPolicy("synthetic-v1", ("synthetic",), (w.manifest_id,), w.ready_ns, "diagnostic")
    def execute(required):
        audit = runner.run_tape_audit(compiled)
        arrays = dict(timestamps=frame.index.asi8, equity=audit.equity, positions=audit.positions,
            fees=audit.fees, funding=np.zeros(len(frame)),
            margin=np.column_stack((audit.initial_margin, audit.maintenance_margin)), turnover=audit.turnover,
            fill_time=frame.index.asi8[audit.fill_bar], fill_qty=audit.fill_qty,
            fill_price=audit.fill_price, fill_fee=audit.fill_fee)
        return ExecutionEvidence.from_arrays(k.identity, w, arrays,
            source_ref="actual-prepared-Rust-v2-fixture", backend="rust_batched")
    return backend, frame, market, commands, compiled, runner, k, w, p, execute


def test_m5t_039_actual_prepared_rust_score_retained_python_accounting_parity():
    backend, frame, market, commands, compiled, runner, k, w, p, execute = prepared_fixture()
    owner, _ = reuse()
    required = plan("accounting", "fill_audit")
    retained, _ = owner.evaluate(k, w, p, required, execute)
    cached, state = owner.evaluate(k, w, p, required, execute)
    score = runner.run_tape_score(compiled)
    python = backend.run_order_commands(datetime_index=frame.index, commands=commands,
        closes={"BTC": frame.close}, highs={"BTC": frame.high}, lows={"BTC": frame.low},
        symbols=["BTC"], market_arrays=market, compiled_commands=compiled,
        contract_size=1., leverage=5., fee_rate=.0002, report_level="minimal")
    values = retained.arrays()
    np.testing.assert_allclose(values["equity"], python.equity, rtol=0, atol=1e-12)
    np.testing.assert_allclose(values["fees"], python.fees, rtol=0, atol=1e-12)
    np.testing.assert_allclose(values["positions"], python.positions.iloc[:, 0], rtol=0, atol=1e-12)
    np.testing.assert_allclose(values["turnover"], python.diagnostics["turnover"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(values["margin"][:, 0], python.margin["initial_margin"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(values["margin"][:, 1], python.margin["maintenance_margin"], rtol=0, atol=1e-12)
    assert values["equity"][-1] == score.final_equity
    assert values["fill_qty"].size == score.fill_count > 0
    assert state == "REUSED" and cached.content_id == retained.content_id and owner.executions == 1
    fresh = execute(required)
    assert fresh.content_id == retained.content_id


def test_shared_owner_deduplicates_thread_misses_without_reusing_mutable_accounts():
    _, _, market, _, _, _, k, w, p, execute = prepared_fixture()
    owner, _ = reuse()
    before = market.closes.copy()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: owner.evaluate(k, w, p, plan("accounting"), execute), range(4)))
    assert owner.executions == 1 and sum(state == "REUSED" for _, state in results) == 3
    assert len({value.content_id for value, _ in results}) == 1
    np.testing.assert_array_equal(market.closes, before)


def test_m5t_031_actual_cost_change_reexecutes_and_changes_cost_accounting():
    from quantbt import RustBatchedRunner
    _, frame, market, _, compiled, runner, k, w, p, execute = prepared_fixture()
    owner, _ = reuse()
    original, _ = owner.evaluate(k, w, p, plan("accounting"), execute)
    changed_key = replace(k, costs="one-way-0.0004/slippage-0.0002")
    changed_runner = RustBatchedRunner(idx=frame.index, symbols=["BTC"], market_arrays=market,
        contract_size=1., leverage=5., fee_rate=.0004, initial_capital=10000.,
        maintenance_ratio=0., slippage=.0002, use_funding=False)
    def changed(required):
        out = changed_runner.run_tape_audit(compiled)
        arrays = dict(original.arrays(), equity=out.equity, positions=out.positions,
            fees=out.fees, margin=np.column_stack((out.initial_margin, out.maintenance_margin)), turnover=out.turnover)
        return ExecutionEvidence.from_arrays(changed_key.identity, w, arrays,
            source_ref="changed-fee-actual-Rust", backend="rust_batched")
    result, state = owner.evaluate(changed_key, w, p, plan("accounting"), changed)
    assert state == "EXECUTED_RETAINED" and owner.executions == 2
    np.testing.assert_allclose(result.arrays()["fees"], 2*original.arrays()["fees"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.arrays()["equity"][-1], original.arrays()["equity"][-1]-original.arrays()["fees"].sum(), rtol=0, atol=1e-10)
