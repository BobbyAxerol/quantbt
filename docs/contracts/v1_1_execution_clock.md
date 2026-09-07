# V1.1 Execution Clock Contract

This document is the Phase 57 specification for the two native-event timing
contracts. It does not change a public default and is intentionally more
precise than a statement such as "next bar".

## Common Clock

OHLC timestamps are **bar-close timestamps**. Bar zero is the immutable
initial snapshot: a command whose explicit timestamp maps to bar zero is
recorded as `OUTSIDE_TAPE` and cannot mutate account state. A command issued
after the final reactive callback is likewise outside the tape because no
future effective bar exists.

For every executable bar, the declared sequence is:

1. Mark carried positions to the close.
2. Evaluate intrabar liquidation under the selected contract.
3. Apply funding scheduled at that close timestamp.
4. Evaluate close-margin liquidation.
5. Expire GTD orders.
6. Apply commands whose effective timestamp is this bar.
7. Match active orders.
8. Activate child orders and cancel OCO siblings in deterministic sequence.
9. Evaluate post-order liquidation.
10. Commit the post-bar account snapshot.

Funding therefore belongs to the close boundary. A dataset whose timestamps
mean bar-open must be relabelled before using this contract; silently treating
an open timestamp as a close timestamp is not certified.

## `event_lifecycle_v2_next_bar_close`

The strategy observes a completed close. A command becomes effective on the
next eligible bar and a market order fills at that bar's close. Limits and
stops retain the frozen legacy unordered-OHLC behavior. This contract is for
historical reproduction, not a claim of venue-native intrabar ordering.

## `event_lifecycle_v3_next_open`

The strategy observes a completed close. A command becomes effective at the
next bar's open. Market orders fill at that open after declared execution
slippage. A favorable limit gap receives the open price; an adverse stop gap
fills at the worse open. If an unarmed stop-limit trigger and limit are both
crossed inside one OHLC bar without a known path, the order is armed and no
same-bar limit fill is claimed. The trace records the ambiguity.

## Hand Examples

For a command observed at close of bar `t`:

| Contract | Effective bar | Market reference price |
|---|---:|---|
| V2 next-bar-close | `t + 1` | `close[t + 1]` |
| V3 next-open | `t + 1` | `open[t + 1]` |

For a V3 buy stop with trigger 100 and next bar `open=103`, the fill reference
is 103 before buy-side slippage. For a V3 buy limit 100 and next bar
`open=97`, the fill reference is 97. These examples lock gap semantics without
assuming a hidden tick path.

## Effective Timestamp Rule

`event_timestamp_ns` is when an observation, command, funding event, or fill
is recorded. `effective_timestamp_ns` is when its account mutation becomes
eligible. They may be equal for close-boundary funding and different for
next-bar orders. Both are mandatory in Canonical Trace V2.

The machine-readable companion is
[`contracts/v1_1_correctness_contract.json`](../../contracts/v1_1_correctness_contract.json).
