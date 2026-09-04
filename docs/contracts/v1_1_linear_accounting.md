# V1.1 Linear Accounting Contract

Phase 57 defines the independent reference model for a linear,
quote-settled, gross-cross account. It is a specification and test oracle, not
a replacement account engine in this phase.

## State

For each symbol, the state is signed quantity `q`, average entry `a`, and
cumulative realized PnL. Account cash contains starting collateral plus
realized PnL minus charged fees and funding. With mark `m` and contract size
`c`, unrealized PnL is:

```text
u = q * (m - a) * c
```

and equity is:

```text
equity = cash + sum(u)
```

## Fill Transition

Let signed fill quantity be `d`, fill price be `p`, and one-way fee be `f`.

- If `q` and `d` have the same sign, the position scales in and the new
  average is the absolute-quantity weighted average of `a` and `p`.
- If their signs differ, `min(abs(q), abs(d))` closes existing exposure. A
  long realizes `closed * (p - a) * c`; a short realizes
  `closed * (a - p) * c`.
- If `abs(d) > abs(q)`, the residual opens in the fill direction at average
  entry `p`.
- If the position becomes zero, average entry becomes zero.

Every accepted fill charges `f` once. `fee_rate` means one-way quote fee per
fill; it is never divided by two inside the reference contract.

## Funding, Margin, And Liquidation

At a scheduled close boundary, funding charge is:

```text
funding_charge = q * m * c * funding_rate
cash -= funding_charge
```

Thus a positive funding rate costs a long and credits a short. Initial and
maintenance margin are gross notional divided or multiplied by their declared
ratios. A post-cost margin preview must reject without mutating state.

The historical `zero_equity_legacy` liquidation behavior remains an explicit
production comparator. Phase 57's oracle exposes a deterministic forced-close
transition for small fixtures but does not relabel the legacy behavior as
venue liquidation.

## Rounding And Tolerances

IDs, statuses, ordering, and timestamps compare exactly. Quantity is
lot-aware; price is tick-aware; cash, fee, funding, margin, PnL, and metrics
use distinct documented tolerances. The exact V2 table is stored in
[`contracts/v1_1_correctness_contract.json`](../../contracts/v1_1_correctness_contract.json).
No single global epsilon is a valid proof of accounting parity.

## Scope

The reference model supports linear quote settlement only. Inverse, quanto,
multi-currency conservation, and option valuation must use their own future
accounting contracts and fail closed rather than reuse this formula.
