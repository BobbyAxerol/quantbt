# QuantBT Documentation Map

Use this page as the first stop when deciding which QuantBT document to read.

## Start Here

| Need | Read |
|---|---|
| Choose the right backend | [Backend selection](backend_selection.md) |
| Call QuantBT from notebooks/services | [Endpoint contract](endpoint.md) |
| Understand vectorized vs event-driven tradeoffs | [Vectorized vs event-driven](vectorized_vs_event_driven.md) |
| Validate leverage, buying power, liquidation, funding | [Margin and leverage](margin_leverage.md) |
| Understand market/limit/stop fill behavior | [Order fill policies](order_fill_policies.md) |
| Build pair trades or baskets | [Pair and basket guide](pair_basket_guide.md) |
| Understand Portfolio Engine V3 roadmap | [Portfolio Engine V3](portfolio_engine_v3.md) |
| Use Nautilus as third-party execution validation | [Nautilus backend](nautilus_backend.md) |
| Understand WFO parameter selection methodology | [Walk-forward methodology](walkforward_methodology_vi.md) |

## Strategy Route Map

| Strategy type | Preferred route | Why |
|---|---|---|
| Single-symbol signal research | `QuantBTEndpoint.signal_notional(...)` or `.pct_equity(...)` | Fast scalar signal backtests with stable notebook API |
| Explicit orders | `QuantBTEndpoint.orders(...)` | Market/limit/stop order lifecycle and fill reports |
| DCA/grid | `QuantBTEndpoint.dca_ladder(...)` | Structural levels, high/low touch detection, trigger-price fills |
| Portfolio matrix | `QuantBTEndpoint.portfolio(...)` | Multi-symbol positions with portfolio-level accounting |
| Pair/basket | `QuantBTEndpoint.basket(...)` | Frozen hedge-ratio units and package diagnostics |
| Arbitrage | `QuantBTEndpoint.arbitrage(...)` | Domain specs for basis, stat-arb, funding, carry, and index-basket routes |
| Walk-forward optimization | `QuantBTEndpoint.walk_forward(...)` | Folded OOS stitching and anti-leakage candidate selection |
| Single holdout train/test | `QuantBTEndpoint.train_test_split(...)` | One train period and one test period using the WFO scoring stack |
| Third-party validation | `QuantBTEndpoint.nautilus_validation(...)` or `backend="nautilus"` | Independent event-driven accounting reports |

## Example Map

Runnable examples live under [`examples/`](../examples/README.md).

Use examples as smoke templates, not as performance benchmarks. For benchmark
numbers and threshold rules, use [`benchmarks/`](../benchmarks/README.md).

## Validation Rule

For production-like research:

1. Prototype with `native_vectorized` when the signal is already known.
2. Move order-sensitive strategies to `native_event`.
3. Validate representative runs with Nautilus when execution/accounting evidence
   is needed.
4. Save `result.metadata`, order/fill reports, config, and benchmark artifacts
   with the strategy output.
