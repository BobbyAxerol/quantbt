from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401
from _mock import TS0, chain, inverse_registry

from quantbt import QuantBTEndpoint, straddle


registry = inverse_registry()
option_chain = chain(registry, inverse=True)
package = straddle(
    TS0,
    "BTC-01FEB26-100000-C.DERIBIT",
    "BTC-01FEB26-100000-P.DERIBIT",
    quantity=1.0,
    package_id="inverse-long-straddle",
)

bt = QuantBTEndpoint.options(
    initial_capital=20_000.0,
    reporting_currency="USD",
    initial_balances={"USD": 20_000.0},
    conversion_rates={"BTC": 100_000.0},
    fee_rate=0.0001,
)
result = bt.simulate(chain=option_chain, instruments=registry, packages=[package])

print(result.run_manifest)
print(result.fills_report)
