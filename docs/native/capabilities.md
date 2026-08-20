# Native Companion Capabilities

Capability claims are generated from
`contracts/native_event_product_registry.json`; the generated table is the
authoritative release-facing view:

- [Generated Native Product Compatibility](../contracts/generated_product_compatibility.md)

The table specifies contract IDs, strategy mode, result profile, account model,
portfolio/package policy, maturity, supported platform evidence, and whether
automatic promotion is allowed. This is deliberately more precise than a flat
list of booleans such as “supports limit orders”.

## Reading maturity

- **Certified**: covered by the declared contract and its current conformance
  evidence. It is not automatically promoted unless the table says so.
- **Experimental**: available for explicit validation only. It must not be used
  to imply generic endpoint or venue support.
- **Promoted**: eligible for `native_backend="auto"` only when its generated
  row, installed-wheel handshake, scale threshold, and local rollback policy
  all pass.

The current Stage-B table promotes only the bounded E0/E3/E6 families: static
command tapes at 10,000 or more bars, and Native Strategy IR/batch requests at
2,000 or more bars. Arbitrary callbacks, reactive strategies, and generic
portfolio/package/arbitrage endpoints remain Python. Phase 54B.3 additionally
certifies two explicit, bounded Rust helpers for `target_units` market targets
and same-bar all-or-none market packages; their rows are intentionally not
auto-promoted until a generic endpoint route has an equally exact fallback
contract. The extension's raw feature map is an implementation probe; it is
normalized by the core's generated descriptor before public routing decisions
are made.

At native probe time QuantBT validates two distinct descriptors:

- the frozen API 0.4 semantic descriptor for event-clock, fill, and account
  behavior;
- the product descriptor for exact core/native versions, protocol, command and
  result ABI, trace schema, strategy IR, and registry fingerprints.

An explicit Rust request fails before market preparation if either descriptor
drifts. `backend="auto"` follows the generated promotion table and records a
structured fallback reason when a request is below its threshold or outside a
certified row. `QUANTBT_DISABLE_NATIVE=1` and
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` deterministically force Python.
