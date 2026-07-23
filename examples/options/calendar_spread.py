from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401
from _mock import TS0, chain, linear_registry

from quantbt import QuantBTEndpoint, calendar


registry = linear_registry()
option_chain = chain(registry)
package = calendar(TS0, "BTC-C100", "BTC-C100-MAR", package_id="call-calendar")

bt = QuantBTEndpoint.options(initial_capital=50_000.0)
result = bt.simulate(chain=option_chain, instruments=registry, packages=[package])

print(result.fills_report)
print(result.attribution_report)
