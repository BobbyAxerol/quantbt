# V1.1 Direct Target Execution Clock

`close_target_v2_same_close` is the narrow execution contract for a target
matrix that is already known at each bar close. It is not an order-lifecycle
contract and it does not imply next-open execution, stop/limit matching, OCO,
or a reactive grid state machine.

The explicit Rust route is available through
`NativeVectorizedBackend(..., target_runtime="rust")`. It is capability-gated,
fails closed when its matching `quantbt-native` wheel is unavailable, and is
never selected by `target_runtime="auto"` in V1.1.

## Clock

OHLC timestamps are bar-close timestamps. Bar `0` is an account snapshot:
there is no target fill on that bar. For every later bar `t`, Rust applies the
following deterministic sequence:

```text
1. Mark carried positions from close[t - 1] to close[t].
2. Check intrabar liquidation against low[t] for longs and high[t] for shorts.
3. Apply funding at close[t] to the carried position when funding_mask[t] is true.
4. Check close-margin liquidation.
5. Snapshot pre-rebalance equity E[t].
6. Resolve each raw target against close[t] and its instrument rules.
7. Compute delta_qty = accepted_target_qty - actual_position_qty.
8. In stable symbol order, preview fee + slippage + positive margin increase,
   then commit or reject that delta atomically for that symbol.
9. Check post-rebalance margin and emit the bar snapshot.
```

`next_open_v1`, `next_close`, and the event-lifecycle clocks are recognized as
different timing requests but are rejected by this route. A successful direct
target run therefore never silently changes a same-close research result into
a next-open or next-close result.

## Target Kinds

All conversions use the same close price `P[t, s]`, contract multiplier
`C[s]`, and immutable pre-rebalance equity snapshot `E[t]`.

| Kind | Raw value | Resolved desired units |
|---|---:|---:|
| `target_units_v1` | `u` | `u` |
| `target_notional_v1` | `n` | `n / (P * C)` |
| `target_weight_v1` | `w` | `w * E / (P * C)` |
| `equity_fraction_v1` | `a` | `a * f[s] * E / (P * C)` |

`f[s]` is the explicit per-symbol capital-allocation fraction passed to the
equity-fraction route. Leverage affects buying power and margin admission only;
it never multiplies the target notional or target weight.

After conversion, quantity is rounded toward zero by `qty_step`, then checked
against `min_qty` and `min_notional`. The canonical accounting delta is always:

```text
delta_qty = accepted_target_qty - previous_actual_qty
trade_notional = abs(delta_qty) * execution_price * contract_size
fee = trade_notional * one_way_fee_rate
```

Slippage is adverse to the delta side. A target that fails non-tradable,
stale-price, quantity, or post-cost margin admission leaves that symbol's
actual position unchanged and produces typed rejection evidence. The certified
public policy is `reject_run`: non-finite target inputs fail the request rather
than being converted to a flat target. Compatibility Numba routes retain their
historical missing-signal behavior.

## Static DCA Versus Reactive DCA/Grid

`run_static_dca_schedule(...)` compiles a predeclared absolute target schedule
into a `StaticTargetTapeV1`. Each scheduled target is carried forward until the
next schedule timestamp. It is appropriate only when all target levels and
times are known before the run.

Price-triggered safety orders, fill-dependent ladders, inventory-aware grid
logic, and dynamic DCA must use `event_driven(...)` or another declared
reactive contract. They are not lowered into this static tape because doing so
would replace their fill-dependent state machine with a different strategy.

## Output Profiles And Audit

The typed Rust request supports three retention profiles:

| Profile | Retained data | Intended use |
|---|---|---|
| `score` | terminal accounting and online metrics | repeated candidate scoring |
| `compact` | score plus bar paths | normal result adaptation |
| `audit` | compact data plus bounded target decisions, fills, and events | reconciliation and certification |

Score does not construct a pandas `DataFrame`, a generic order-command arena,
or audit rows. Python creates `BacktestResultV2`, charts, and reports only on
the cold result path; it does not replay target execution.

## WFO Boundary

`NativeTargetWfoRuntimeV2` accepts a prepared candidate target tensor and
executes each declared OOS fold with a fresh account. It retains one immutable
market/template plan, one explicit Python-to-Rust target-batch ingest, scalar
score rows, and selected audit replay. It does not convert targets into signals
or command tapes.

The V1 target WFO adapter is deliberately single-symbol and serial. Shared
multi-symbol account admission, portfolio allocation policies, and portfolio
WFO are Phase 67 work. This boundary prevents a direct target matrix from
being accidentally marketed as a fully certified portfolio engine.

## Certification Status

`target_units`, `target_notional`, `target_weight`, and `equity_fraction` are
separate explicit Rust capabilities. Phase 66 keeps Numba as the reproducible
compatibility comparator and leaves `target_runtime="auto"` on Numba. The
Phase 66 installed-wheel proof executes all four target kinds plus static DCA
from the exact staged pair. A future automatic promotion still requires its
own policy and performance review for the exact target kind and timing
contract; wheel availability alone does not change a public default.

The staged pair can be checked without source-tree imports with:

```bash
python tools/verify_wheels.py \
  --dist /path/to/staged-wheels \
  --require-native \
  --direct-target-smoke
```

The optional smoke imports the exact staged `quantbt-engine` /
`quantbt-native` pair from `site-packages`, executes `target_units`,
`target_notional`, `target_weight`, `equity_fraction`, and static DCA through
`target_runtime="rust"`, then verifies their direct-target metadata rather
than accepting an import-only native proof.
