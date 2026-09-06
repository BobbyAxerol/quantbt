# Percent-Equity Transition Contract V1

`QuantBTEndpoint.pct_equity()` is a stable compatibility route. Its input is a
signed **weight**, but it is not the same product as a per-bar target-weight or
Rust `EquityFraction` rebalance. `pct_equity_transition_v1` is the explicitly
certified Rust implementation of that historical transition-sized behavior;
it is judged against observable financial behavior rather than a similarly
named sizing formula.

## Scope

This contract applies to the single-account `%_equity` / `pct_equity` engine.
It is used directly by `QuantBTEndpoint.pct_equity()` and by a final
walk-forward account whose `target_mode="pct_equity"`. The historical Numba
route remains the default. The Rust route is deliberate, not automatic:

```python
endpoint = QuantBTEndpoint.pct_equity(
    fee=0.0004,             # historical round-trip compatibility input
    fee_rate=0.0002,        # canonical one-way rate: must equal fee / 2
    slippage=0.0001,
    target_runtime="rust",
)
result = endpoint.backtest(data=bars, signal=signal)
```

For public WFO scoring, add
`native_prepared_wfo="require"` under `optimization_config`; `"auto"`
intentionally keeps the historical scorer. The certified route is one symbol
and does not certify portfolio risk sizing, DCA/grid, shared cross-margin, or
an event-order strategy.

The strategy emits a raw weight $w_{t,s}$. With allocation fraction $a_s$,
close $C_{t,s}$, contract size $q_s$, and current equity $E_t$, a **new** target
unit quantity is calculated only when the raw weight changes:

$$
u^*_{t,s} = \frac{E_t a_s w_{t,s}}{C_{t,s} q_s}.
$$

`alloc_per_trade=0.50` and `alloc_per_trade=50` both resolve to $a_s=0.50$.
When `use_pyramiding=False`, the input weight is first reduced to its sign;
when it is true, the raw magnitude is retained.

## Bar Sequence

Bar zero is an account snapshot. It does not open a position even when the
first raw weight is non-zero. For every later bar, the legacy engine performs:

1. Mark the carried accepted units to the current close.
2. Test the intrabar liquidation price against maintenance margin.
3. Charge funding, when the bar is a funding event, to the position carried
   into that event.
4. Test close-margin liquidation.
5. If and only if $w_t \ne w_{t-1}$, calculate $u_t^*$ from current equity,
   quantize it against the instrument constraints, preview margin/cost, and
   commit the accepted delta.

For an accepted delta $\Delta u$, fee and slippage are calculated from the
execution price on that delta. If post-cost margin is insufficient, the current
accepted units remain frozen. Crucially, an unchanged raw weight on the next
bar does **not** retry that rejected order: a subsequent weight transition is
required. This is observable legacy behavior, not an accidental retry policy.

## Consequences

- A profitable hold does not drift-rebalance just because equity or price
  changes. It retains the previously accepted units until a raw-weight change.
- A reversal is one delta from the existing accepted units to the newly sized
  target. It is not an implicit close followed by a separately re-sized entry.
- The public `positions` frame preserves raw signal weights for compatibility;
  it is not an accepted-unit ledger. Equity, fees and funding are authoritative
  accounting outputs. A native replacement therefore needs an explicit
  accepted-unit/audit representation rather than interpreting that frame as
  fills.
- The historical compatibility engine receives the round-trip `fee` argument.
  The explicit Rust route accepts only the numerically equivalent canonical
  configuration: `fee_rate == fee / 2`, and an explicitly supplied V2
  slippage rate must equal legacy fractional `slippage`. A conflict raises
  before execution. It never silently divides an already canonical rate or
  changes an existing notebook's cost convention.
- The historical engine always used its canonical internal `DEFAULT` symbol
  surface for a scalar run. The Rust compatibility adapter preserves this
  observable surface and records an explicitly supplied symbol in
  `metadata["pct_equity_transition"]["requested_symbol_ignored_for_legacy_compatibility"]`.
  This is a compatibility fact, not a multi-symbol capability claim.

## Certification Fixtures And Evidence

The executable Phase 77.1/77.2 fixtures verify all of the following:

- first-bar snapshot;
- entry, hold without drift-rebalance, reversal and subsequent PnL;
- funding on a carried position;
- rejected unchanged signal not being retried;
- fraction/percentage allocation equivalence; and
- raw-weight report semantics when an order was rejected.

Phase 77.2 additionally verifies canonical one-way fee/slippage refusal,
accepted-unit ledger parity, one-versus-many prepared-worker parity, scalar
SoA score adaptation, and public WFO selection/stitch parity for Modes 1, 3,
4, and 5. Mode 2 remains the separately certified bootstrap/proxy route.

Run it through:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_phase77_1_measurement_contract.py \
  tests/test_phase77_2_pct_equity_native.py

PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_phase77_2_pct_equity_wfo.py --profile standard
```

The public WFO matrix is documented in
[Public WFO Baseline V1](../performance/public_wfo_baseline_v1.md). The Phase
77.2 benchmark is a paired opt-in measurement, not a default-backend or generic
WFO promotion claim.
