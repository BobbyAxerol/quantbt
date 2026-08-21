# Native Event Contract Registry

The canonical machine-readable source is
[`contracts/native_event_contract_registry.json`](../../contracts/native_event_contract_registry.json).
Python and Rust identifiers are generated from that file by
`tools/generate_native_event_contracts.py`. The canonical JSON payload has
SHA-256 fingerprint
`601d639f1c398ac81f3c8231c30d067372c80e71ae4e5f097182f00c5c91f05d`.

## Contract Taxonomy

| Classification | Meaning |
|---|---|
| `CERTIFIED_CURRENT` | New behavior with explicit contract and Python/Rust parity gates. |
| `LEGACY_FROZEN` | Reproducible historical behavior retained for compatibility. |
| `UNSPECIFIED` | Behavior not yet suitable for a production claim. |
| `KNOWN_DRIFT` | Public metadata and implementation differ; migration is explicit. |
| `FUTURE` | Schema reservation only; no execution capability is advertised. |

## Versioned Event Contracts

### `event_lifecycle_v2_next_bar_close`

This is the honest name for historical native-event V2 behavior. A command
effective on bar `t` uses `close[t]` for market execution. Limits and stops use
the legacy unordered OHLC range rules. It is classified `LEGACY_FROZEN` and
must retain its historical equity, fill, event, fee, funding, and liquidation
outputs.

### `event_lifecycle_v3_next_open`

This contract observes a completed close, activates the command on the next
bar, and uses the actual `open[t+1]` for market execution. Favorable limit gaps
receive open-price improvement. Adverse stop gaps execute at the worse open.
An unarmed stop-limit whose trigger and limit are both crossed without known
intrabar path is flagged and conservatively remains armed for a later bar.
The route rejects missing open data; it never substitutes close prices while
claiming next-open semantics.

The stable endpoint keeps V2 as the compatibility default. Select V3
explicitly:

```python
bt = QuantBTEndpoint.event_driven(
    input_mode="orders",
    profile="audit",
    backend="python",  # or explicit "rust" with a compatible native wheel
    execution_contract="event_lifecycle_v3_next_open",
)
result = bt.simulate(data=ohlcv, order_commands=commands, symbols=["BTCUSDT"])
```

## Clock Order

Both contracts freeze the existing account phase order:

1. Mark carried positions to close.
2. Evaluate intrabar liquidation.
3. Apply close-timestamp funding.
4. Evaluate close-margin liquidation.
5. Expire GTD orders.
6. Apply effective commands.
7. Match active orders under the selected fill policy.
8. Activate children and cancel OCO siblings in sequence order.
9. Evaluate post-order liquidation.
10. Record the post-bar snapshot.

Bar zero is the immutable initial-state snapshot. An explicit command mapped
to bar zero is retained as `CommandOutcome.OUTSIDE_TAPE` and does not mutate
the account. An explicit tape command mapped to the final market bar may
execute on that bar; a command emitted by a reactive strategy after the final
callback has no next bar and is retained as outside-tape intent.

The sequence is a deterministic research contract. It is not advertised as a
clone of every venue's matching engine.

## Lifecycle Vocabulary

`CommandOutcome`, `OrderStatus`, and `LifecycleEventKind` are separate concepts.
A successful cancel command is `CommandOutcome.ACCEPTED`; it is never described
as a filled order. Partial fill is reserved in the state model but remains a
capability-gated feature. The registry transition table is executable test
input in both Python and Rust.

Audit results expose `command_outcome_report_v1`,
`lifecycle_event_report_v1`, and `event_phase_trace_v1`. Every phase-trace row
carries `bar`, `timestamp_ns`, `phase`, and a deterministic global `sequence`.
The Python oracle also exposes per-command `fill_policy_diagnostics`; Rust
records fill reason and ambiguity codes on `fills_report`. Both routes publish
the selected policy IDs in `event_clock_contract`. Legacy reports remain
present for compatibility and are not silently reinterpreted.

Python and Rust build the command-outcome projection from the same immutable
compiled command tape and the backend lifecycle stream. Report construction is
outside the execution hot path and does not mutate matcher or account state.

`EngineDiagnosticsV1` is opt-in through `diagnostics=True`. It reports exact
bar/symbol/command/fill/event counts, implementation scan counts, retained
output bytes, and prepare/engine/report timing. Enabling diagnostics must not
change positions, fills, equity, fees, funding, margin, or lifecycle events.

## Compatibility

Legacy aliases such as `event_lifecycle_v2` resolve only to
`event_lifecycle_v2_next_bar_close`. They never silently opt a caller into V3.
New research must request `event_lifecycle_v3_next_open` explicitly until the
release migration policy changes.
