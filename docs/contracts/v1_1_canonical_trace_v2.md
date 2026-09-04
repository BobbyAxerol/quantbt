# Canonical Trace V2

Canonical Trace V2 is the backend-neutral evidence format introduced in Phase
57. It is additive to `canonical-execution-trace-v1`; V1 remains readable for
existing audit output and is projected into V2 only as a clearly labelled
lossy legacy adapter.

## Row Contract

Each row has typed numeric identifiers and two timestamps:

```text
sequence, bar_index, event_timestamp_ns, effective_timestamp_ns,
symbol_id, account_id, package_id, order_id,
event_kind, reason_code, order_status_code,
qty, price, fee,
cash_before, cash_after,
position_before, position_after,
realized_pnl_before, realized_pnl_after,
initial_margin_before, initial_margin_after,
maintenance_margin_before, maintenance_margin_after,
state_hash_before, state_hash_after
```

The event vocabulary includes market observation, funding, command,
order-lifecycle, fill, fee, position, cash, margin, liquidation, package,
reservation, settlement, and run-complete records. Absent numeric IDs use the
declared sentinel `-1`; absent financial values use canonical NaN encoding.

## Stable Serialization And Hashing

Rows are serialized in sequence order using a version-tagged,
little-endian binary format. Each floating field is normalized with its own
declared policy before encoding. The V2 trace hash is dual FNV-1a 128-bit;
this avoids a runtime dependency and is implemented in both the Python
verification layer and Rust domain crate. It is an evidence fingerprint, not a
cryptographic signature.

`TerminalFingerprintV2` separately fingerprints final cash, positions, order
states, margin, package state, trace, and metrics. Score, compact, and audit
profiles must have the same financial terminal fingerprint even when their
retained detail differs.

## Comparator Rules

Discrete fields compare exactly. Quantity uses a declared lot-aware policy,
prices a tick-aware policy, financial fields a strict financial policy, and
metrics their own policy. The first divergent row and field are returned by a
comparison rather than silently accepting a final-equity match.

## Authority And Scope

The Phase 57 model is a verification substrate. It neither changes endpoint
routing nor claims that V1 audit reports already contain every V2 event. The
independent oracle remains in `reference/python`, outside the packaged source
tree. Later phases may add direct Rust and Python runtime emitters only after
those emitters satisfy this schema.

The machine-readable companion is
[`contracts/v1_1_correctness_contract.json`](../../contracts/v1_1_correctness_contract.json).
