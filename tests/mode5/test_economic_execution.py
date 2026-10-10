"""M5T-109: stress reruns the actual callback policy and account engine."""
import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint, OrderCommand, OrderSide, OrderType
from quantbt.mode5.diagnostics.identity import digest
from tools.mode5_economics import StressRequest


class EquityGuard:
    def initialize(self, context):
        return ()

    def on_bar_close(self, context):
        if context.positions["SYNTH"] != 0 and context.bar_index % 4 == 2:
            return (OrderCommand(timestamp=context.timestamp, symbol="SYNTH", qty=100.,
                side=OrderSide.SELL, order_type=OrderType.MARKET, reduce_only=True),)
        if context.positions["SYNTH"] == 0 and context.bar_index % 4 == 0 and context.equity >= 19950:
            return (OrderCommand(timestamp=context.timestamp, symbol="SYNTH", qty=100.,
                side=OrderSide.BUY, order_type=OrderType.MARKET),)
        return ()

    def finalize(self, context):
        return ()


def test_fee_stress_changes_future_decisions_via_actual_equity():
    index = pd.date_range("2023-01-01", periods=48, freq="h", tz="UTC")
    frame = pd.DataFrame(dict(open=100., high=101., low=99., close=100., volume=1000.), index=index)
    def run(fee):
        endpoint = QuantBTEndpoint.event_driven(input_mode="strategy", backend="python", profile="audit",
            symbols=["SYNTH"], initial_capital=20000., leverage=1., fee_rate=fee, slippage_bps=0.,
            use_funding=False, execution_contract="event_lifecycle_v3_next_open")
        return endpoint.backtest(data=frame, strategy=EquityGuard())
    baseline = run(.0001)
    stressed = run(.01)
    assert len(baseline.fills) > len(stressed.fills) >= 2
    for result in (baseline, stressed):
        np.testing.assert_allclose(result.equity.iloc[-1], 20000.-np.asarray(result.fees).sum(), rtol=0, atol=1e-8)
    policy = StressRequest("actual-baseline", digest({"guard": 19950}), "one-way-fee-.01", "fee")
    observed = policy.execute(lambda request: dict(method="ACTUAL_ACCOUNT_RESIMULATION",
        params_digest=request.params_digest, economic_contract=request.stressed_economic_contract,
        execution_id=digest(np.asarray(stressed.equity).tolist()), accounting_verified=True,
        fills=len(stressed.fills), baseline_fills=len(baseline.fills)))
    assert observed.data["fills"] < observed.data["baseline_fills"]
