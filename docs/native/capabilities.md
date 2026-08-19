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
- **Promoted**: reserved for a future release after clean wheel, parity, RSS,
  performance, and rollback gates.

Version 1.0.8 declares no promoted Rust workload. The extension's raw feature
map is an implementation probe; it is normalized by the core's generated
descriptor before public routing decisions are made.

At native probe time QuantBT validates two distinct descriptors:

- the frozen API 0.4 semantic descriptor for event-clock, fill, and account
  behavior;
- the product descriptor for exact core/native versions, protocol, command and
  result ABI, trace schema, strategy IR, and registry fingerprints.

An explicit Rust request fails before market preparation if either descriptor
drifts. `backend="auto"` remains Python-first in this release.
