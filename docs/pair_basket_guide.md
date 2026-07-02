# Pair And Basket Guide

Pair and basket trades should be modeled as a coordinated order plan, not as
independent dynamic weights.

Use `BasketSpec` and `BacktestEngineV2(backend="native_event")` when the hedge
ratio must freeze at entry and unwind exact units at exit.

```python
from quantbt import (
    AccountConfig,
    BacktestEngineV2,
    BasketLegSpec,
    BasketSpec,
)

basket = BasketSpec(
    basket_id="PAIR-001",
    legs=(
        BasketLegSpec(symbol="BASE", ratio=1.0),
        BasketLegSpec(symbol="HEDGE", ratio=-0.5),
    ),
    gross_notional=100_000,
)

engine = BacktestEngineV2(
    backend="native_event",
    basket=basket,
    signal=pair_signal,
    closes={"BASE": base_close, "HEDGE": hedge_close},
    highs={"BASE": base_high, "HEDGE": hedge_high},
    lows={"BASE": base_low, "HEDGE": hedge_low},
    datetime_index=pair_signal.index,
    account=AccountConfig(initial_capital=1_000_000, leverage=5),
)
result = engine.result
```

Behavior:

- entry units are computed once from prices at the signal transition;
- hedge ratio is frozen until exit;
- price drift does not create micro-rebalances;
- exit closes the exact frozen units;
- basket plan diagnostics are stored in `result.metadata["basket_plan"]`.

Current all-or-none behavior is represented in schema and metadata. The current
native event kernel executes generated leg orders best-effort; strict atomic
all-or-none matching is a later engine enhancement.
