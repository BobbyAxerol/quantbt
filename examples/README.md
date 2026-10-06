# QuantBT Examples

These examples are small deterministic smoke templates. They are designed to be
copied into notebooks or used by services as endpoint wiring references.

Run from the repository root:

```bash
PYTHONPATH=/root/bobby/pool_alpha python3 quantbt/examples/single_order_event.py
```

## Files

| File | Route | Purpose |
|---|---|---|
| `single_order_event.py` | `EventDrivenBacktestEngine` | Minimal limit-order lifecycle and order report |
| `dca_grid_ladder.py` | legacy `BacktestEngine` with `hedge_type="dca_ladder"` | Structural DCA/grid levels with high/low touch simulation |
| `multi_symbol_portfolio.py` | `PortfolioBacktestEngine` | Multi-symbol position matrix and market-neutral accounting |
| `pair_basket_event.py` | `BacktestEngineV2(backend="native_event", basket=...)` | Frozen hedge-ratio pair/basket package |
| `arbitrage_basis.py` | `QuantBTEndpoint.arbitrage(...)` | Basis arbitrage spec and package execution |
| `walk_forward_train_test.py` | `QuantBTEndpoint.train_test_split(...)` | Single holdout train/test using the walk-forward adapter |
| `wfo_meta_selection.py` | existing `QuantBTEndpoint.walk_forward(...)` | Feature-branch Mode-4 causal off/shadow/active, typed history, original-result observer and audit lineage; synthetic smoke only |
| `wfo_meta_portfolio.py` | existing portfolio WFO/shared account | E04 opt-in with ordered universe, original aggregate labels and exact position output; synthetic engineering evidence, not empirical promotion |
| `wfo_meta_handoff.py` | existing meta result and pure selector | Full reviewed decision/model/snapshot export and restore; no broker, replay, activation or state reset |
| `wfo_meta_contract.py` | existing WFO endpoint and strict history restore | Complete off, sampler-only, reviewed local-history and unsupported-method cases; synthetic software proof, no economic/live claim |
| `wfo_reactive_samplers.py` | existing prepared W3 and R3B | Four shared recipes, original Rust account/reset policy and versioned batch proposals; see [scheduler contract](../docs/meta_selection/W3_SAMPLER_SCHEDULES.md) |
| `optimization_workflow.py` | `OptunaOptimizer` + prepared/generic evaluators | Domain-agnostic optimization smoke template |
| `optimization_exact_continuation.py` | additive owned sampler session | Four-recipe safe JSON checkpoint and exact fresh-process continuation; toy objective, no automatic WFO resume |
| `nautilus_validation.py` | `QuantBTEndpoint.nautilus_validation(...)` | Signal validation through NautilusTrader |
| `nautilus_explicit_orders.py` | `BacktestEngineV2(backend="nautilus", orders=...)` | Explicit order replay and native-vs-Nautilus parity |
| `phase6_public_api.py` | multiple | Compact API snippets for service authors |

Nautilus examples require the optional `nautilus-trader` dependency.
