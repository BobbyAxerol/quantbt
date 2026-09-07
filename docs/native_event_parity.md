# Native Event Parity Contract

Phase 46A establishes the correctness gate used before any Python, Numba, Rust,
or PyPI performance claim.

## Full parity

```python
from quantbt import assert_native_event_full_parity

certificate = assert_native_event_full_parity(
    candidate_result,
    replay_oracle_result,
    numeric_atol=1e-12,
    command_tape=(candidate_tape, oracle_tape),
)
```

The helper requires the lifecycle artifacts for a full certificate. It checks
effective command bars and sequences when a command tape is supplied; event
order, status, fills, equity, positions, fees, funding, turnover, margin, and
final liquidation state are checked when the selected capability supports that
field. Discrete values must be exact. Numeric arrays use `rtol=0` and
`atol=1e-12`; this tolerance is for floating-point operation order, not for
different execution decisions.

`require_full=False` is reserved for explicitly minimal or scalar runs. It is
not a production certification and must not be reported as full parity.

## Capability source of truth

`quantbt.NATIVE_EVENT_CAPABILITY_MATRIX` is the stable public vocabulary for
the certified single-symbol R2 surface. The Rust extension may expose release-
specific raw flags, but `normalize_native_event_capabilities()` maps those
flags into the canonical matrix and never enables an unreviewed capability.
Unsupported requests remain explicit errors; they do not silently fall back to
a different execution model.

The current matrix supports single-symbol market/limit/stop commands, place,
cancel, amend, replace, reduce-only, quantity constraints, and GTC. It does
not certify funding, liquidation, multi-symbol, OCO, parent-child, IOC, FOK,
or GTD semantics for the Rust path.

## Packaging baseline

The wheel source remains under `src/quantbt`. The old root compatibility mirror
was retired in NEXT-03; `tests/test_next03_canonical_source_layout.py` now
asserts canonical origin and rejects mirror regrowth. The earlier Phase 46A
retention statement is historical context, not current packaging policy.
