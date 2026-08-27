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

## Public Installation Boundary

The public package pair is `quantbt-engine==1.1.0` and
`quantbt-native==0.4.1`. The core declares the companion directly only for
Linux x86_64 glibc / CPython 3.11-3.13. `pip install quantbt-engine` and
`poetry add quantbt-engine` therefore install a pre-built wheel on that matrix;
they do not build Rust locally. Other platforms retain the full Python/Numba
endpoint surface and record Python selection where a governed native route is
not available.

Public availability is certified by the native-first publish workflow and the
Ubuntu 22.04/24.04 Poetry consumer matrix. See the
[release checklist](../testpypi_release_checklist.md) for the immutable
artifact order and exact proof output.

## Performance Boundary

On the committed release fixtures, the promoted Native Strategy IR score path
processed 2,000 bars in 0.741 ms (2.70M bars/s), versus 31.565 ms for the
Python oracle, with exact trace/accounting parity. A shared 64-scenario IR
batch processed 128,000 simulated bars in 11.379 ms (11.25M bars/s).

The explicit bounded portfolio-target and atomic-package helpers measured
3.594 ms and 3.512 ms on their 2,000-bar x 8-symbol fixtures, 9.3x and 5.6x
faster than the corresponding Python event oracles. These are score hot-path
results. They do not imply the same speedup for callback strategies or full
audit/report construction. Read [Benchmarking governance](../performance/benchmarking.md)
for evidence links and interpretation rules.

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

For the exact installed-wheel release gate, core-only fallback behavior,
rollback procedure, and release-owner checklist, read the
[native release handoff](../migration/native_release_handoff.md).
