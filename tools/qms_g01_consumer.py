"""Installed-only original-account liquidation compatibility proof."""

from hashlib import sha256
import json
from pathlib import Path


def main():
    import _quantbt_native as native
    import quantbt
    import numpy as np
    import pandas as pd
    from quantbt.preparation.native_execution import NativeExecutionPreparationCache
    from quantbt.backends.native_prepared_evaluation import (
        NativeEvaluationMetricContractV1, NativePreparedEvaluationRuntimeV1, NativePreparedWorkloadV1,
    )
    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert quantbt.__version__ == "1.1.2" and native.version() == "0.4.3"
    index = pd.date_range("2020-01-01", periods=7, freq="1D", tz="UTC")
    prices = np.array([100., 100., 120., 1., 1., 1., 1.]).reshape(-1, 1)
    cache = NativeExecutionPreparationCache()
    market = cache.prepare_market(timestamps_ns=index.asi8, opens=prices, highs=prices,
        lows=prices, closes=prices, volumes=np.ones_like(prices), funding=np.zeros_like(prices),
        funding_mask=np.zeros(len(index), dtype=bool), symbols=["A"])
    template = cache.prepare_template(market, contract_sizes=np.ones(1), leverages=np.array([3.]),
        fee_rates=np.zeros(1), initial_capital=100., maintenance_ratio=.005,
        slippage_rate=0., use_funding=False)
    contract = NativeEvaluationMetricContractV1(zero_base_return_policy="legacy_zero_base_v1")
    assert contract.fingerprint != NativeEvaluationMetricContractV1().fingerprint
    expected_returns = np.array([0., .4, -1., 0., 0., 0.])
    expected_sharpe = expected_returns.mean()/expected_returns.std(ddof=1)*np.sqrt(365.)
    runtime = NativePreparedEvaluationRuntimeV1(cache)
    try:
        for profile in (0, 1, 2):
            request = cache.direct_target_request(template, targets=np.full_like(prices, 2.),
                output_profile=profile, metric_zero_base_policy="legacy_zero_base_v1")
            before = cache.direct_target_request(template, targets=np.full_like(prices, 2.), output_profile=profile)
            actual, old = dict(request.core.execute()), dict(before.core.execute())
            assert actual["liquidated"] and request.signature != before.signature
            assert actual["native_metric_sample_count"] == 6 and old["native_metric_sample_count"] == 3
            np.testing.assert_allclose(actual["native_metric_sharpe"], expected_sharpe, rtol=0., atol=1e-12)
            for key in ("final_equity", "total_fee", "total_funding", "total_turnover", "fill_count", "rejected_count"):
                assert actual[key] == old[key]
            if profile:
                np.testing.assert_array_equal(np.asarray(actual["equity"]).reshape(-1), [100.,100.,140.,0.,0.,0.,0.])
            binding = runtime.bind_request(request, workload=NativePreparedWorkloadV1.TARGET_UNITS,
                candidate_id=profile, metric_contract=contract)
            row = runtime.evaluate_score_columns([binding])
            np.testing.assert_allclose(row.sharpe[0], expected_sharpe, rtol=0., atol=1e-12)
    finally:
        runtime.close()
    import _quantbt_native._quantbt_native as extension
    print(json.dumps(dict(schema="qms-g01-installed-metric-v1", checks=3, skipped=0,
        core_origin=str(Path(quantbt.__file__).resolve()), native_origin=str(Path(extension.__file__).resolve()),
        native_sha256=sha256(Path(extension.__file__).read_bytes()).hexdigest(),
        financial_profile_parity=True, sample_policy="legacy_zero_base_v1", publication=False)))


if __name__ == "__main__":
    main()
