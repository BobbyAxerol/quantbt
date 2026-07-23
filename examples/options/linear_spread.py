from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401
from _mock import TS0, chain, linear_registry

from quantbt import QuantBTEndpoint, vertical


registry = linear_registry()
option_chain = chain(registry)
package = vertical(TS0, "BTC-C100", "BTC-C110", package_id="linear-call-vertical")

bt = QuantBTEndpoint.options(initial_capital=50_000.0)
result = bt.simulate(chain=option_chain, instruments=registry, packages=[package])

print(result.packages_report)
print(result.margin_report)
