# Event Clock Contract

Native event execution is explicitly versioned. An execution result records the
clock contract so that a historical run is not silently replayed under a new
fill-time interpretation.

| Contract | Market entry timing | Intended use |
|---|---|---|
| `event_lifecycle_v2_next_bar_close` | Next bar close | Legacy-compatible replay |
| `event_lifecycle_v3_next_open` | Next bar open | Causal next-open simulation |

For limit and stop orders, OHLC is an approximation of intrabar reachability.
The chosen contract also controls gap handling and the trace event vocabulary.
It does not claim L2 queue position or exchange matching-engine priority.

Funding requires declared timestamp semantics. If the input index represents
bar closes, a funding event at a boundary is applied after the bar's intrabar
actions. A bar-open convention is a distinct timing policy. Unsupported
position-at-event timing must be rejected rather than guessed.

The canonical lifecycle codes and transition table are generated from
`contracts/native_event_contract_registry.json`. Run
`python tools/generate_native_event_contracts.py --check` before changing a
clock or transition.
