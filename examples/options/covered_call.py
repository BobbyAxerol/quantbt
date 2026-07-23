from __future__ import annotations

from _bootstrap import PROJECT_ROOT  # noqa: F401
from _mock import TS0

from quantbt import compile_option_package_orders, covered_call


package = covered_call(
    TS0,
    underlying_id="BTC-PERP.TEST",
    call_id="BTC-C110",
    quantity=1.0,
    package_id="covered-call-template",
)

# Phase 8 templates only emit package intents. Mixed underlying+option
# execution is a later adapter concern, so this example stops at order leaves.
orders = compile_option_package_orders(package)

print(package)
print(orders)
