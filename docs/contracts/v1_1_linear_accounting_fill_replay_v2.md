# V1.1 Linear Accounting And FillReplay V2

The machine-readable contract is
[`v1_1_linear_accounting_fill_replay_v2_contract.json`](../../contracts/v1_1_linear_accounting_fill_replay_v2_contract.json).
It defines the first V1.1 route where Rust is the accounting authority rather
than a score-only acceleration: an explicit, whole-run fill and funding tape
for one quote-settled, linear, gross-cross account.

This route validates **accounting from supplied events**. It does not claim to
model how a strategy generated an order, how a venue queued it, or whether a
fill was causally obtainable. Those responsibilities remain with the producer
of the explicit tape or a later execution-model route.

## Scope And Boundary

`QuantBTEndpoint.fill_replay(accounting_backend="rust_v2")` accepts one
canonical close-timestamp market tape, an ordered typed fill tape, and an
optional ordered funding tape. Rust owns marks, positions, average entries,
realized and unrealized PnL, fees, funding, margin, liquidation, and the audit
trace for the complete run. Python validates and packs input once, makes one
native call, then adapts compact/audit buffers to normal QuantBT results. It
does not replay accounting after the native result returns.

The certified account is a single-currency linear quote-settled gross-cross
model. For symbol `i`, signed quantity `q_i`, average entry `a_i`, mark `m_i`,
and multiplier `c_i`:

```text
unrealized_i = q_i * (m_i - a_i) * c_i
equity       = cash + sum(unrealized_i)
initial      = sum(abs(q_i) * m_i * c_i / leverage_i)
maintenance  = sum(abs(q_i) * m_i * c_i * maintenance_ratio)
available    = equity - initial - reserved_margin
```

Scale-ins use the absolute-quantity weighted average. Opposite-direction fills
first realize the closed portion, then either retain the old average for a
reduction or set the residual reversal to the new fill price. `fee` is an
explicit one-way quote charge for that one fill. It is never halved by this
route.

## Transaction And Rejection Semantics

The Rust account exposes an internal `preview -> reserve -> commit -> release`
protocol. Preview is side-effect free. A post-cost margin rejection, stale
preview, invalid fill, duplicate funding event, unknown reservation, or
reservation/candidate mismatch must leave the account fingerprint unchanged.
Reservations bind the full candidate event, not merely an ID, so reserved
collateral cannot be consumed by a different fill.

FillReplay itself consumes pre-committed candidates directly after a
side-effect-free preview. This keeps the replay route simple while allowing
future command/package routes to use the same reservation authority.

## Funding And Liquidation

Funding is a separate event tape. A positive rate charges a long and credits a
short:

```text
funding_charge = q_i * m_i * c_i * rate
cash          -= funding_charge
```

Each funding `event_id` applies once. The declared close-boundary phase is
either `before_fills_at_close` or `after_fills_at_close`; it is recorded in
result metadata. Bar timestamps must mean **bar close**. A source whose
timestamps mean bar open is rejected rather than silently shifting funding.

After each mark, funding phase, and supplied-fill phase, the account checks the
maintenance condition. A breach enters deterministic liquidation state,
cancels/reserves no hidden exposure, and emits ordinary executable close fills
in ascending symbol order at the observed mark. The terminal state is
`LIQUIDATED` or `BANKRUPT`; subsequent user fills reject with
`TERMINAL_LIQUIDATION`.

## Audit And Parity Evidence

`report_level="minimal"`/`"standard"` lower to compact output; `"full"` and
`"audit"` retain the canonical trace. Direct internal callers may request a
score-only output that contains terminal scalars without paths or Python audit
objects. Score, compact, and audit must share the same terminal account and
trace fingerprints.

The trace uses `canonical-trace-v2` with per-field quantity, price, and
financial tolerance policies. The account also keeps a raw IEEE-754 fingerprint
for in-process transaction staleness. That raw fingerprint is intentionally not
a cross-language equality claim. Trace checkpoints use a separate normalized
state hash with a `1e-6` financial quantum, avoiding false divergences from a
last-bit addition-order difference while still making material state changes
visible.

Certification compares the Rust trace with the standard-library-only
`reference/python/fill_replay_v2_oracle.py`, uses FillReplay V1/Numba as a
terminal arithmetic comparator over its smaller common scope, runs randomized
valid and invalid streams with invariant checks, and verifies explicit
margin-reject, duplicate-funding, reservation, and liquidation fixtures.

## Explicit Use

```python
bt = QuantBTEndpoint.fill_replay(
    accounting_backend="rust_v2",
    initial_capital=20_000,
    leverage=5,
    maintenance_ratio=0.005,
    contract_size={"BTCUSDT": 1.0, "ETHUSDT": 1.0},
    funding_phase="after_fills_at_close",
    liquidation_fee_rate=0.0005,
    report_level="audit",
)

result = bt.backtest(
    data={"BTCUSDT": btc_ohlcv, "ETHUSDT": eth_ohlcv},
    symbols=["BTCUSDT", "ETHUSDT"],
    fill_replay=fills_df,
    funding_replay=funding_df,
)
```

`fills_df` must have `bar_index`, `sequence`, `event_id`, `symbol`,
`signed_qty`, `price`, and `fee`. `funding_df` must have `bar_index`,
`sequence`, `event_id`, `symbol`, and `rate`. Rows are never sorted by the
facade: invalid ordering is rejected by the authority. Empty pandas frames are
valid zero-event tapes.

The historical default remains `accounting_backend="numba_v1"` for backward
compatibility. It is a single-symbol, no-funding, no-margin/liquidation
comparator; it does not silently become V2. Inverse/quanto contracts,
multi-currency balances, venue portfolio margin, matching, queue/depth, and
fill generation remain outside this A2 accounting certificate.
