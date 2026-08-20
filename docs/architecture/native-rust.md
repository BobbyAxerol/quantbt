# Native Rust Architecture

The optional Rust component is a companion execution implementation, not a
second public product API. Python owns the public endpoint, compatibility
adapters, result objects, metrics, and the reference semantics. Rust owns
certified low-level state only after a contract handshake.

```text
quantbt-engine (Python core)
  public endpoints, oracle, plans, reports
          |
          | descriptor + protocol/ABI handshake
          v
quantbt-native (PyO3 extension)
  prepared tape, typed commands, native IR, batch drivers
```

## Crate map

| Crate | Role |
|---|---|
| `quantbt-domain` | Generated contracts, IDs, numeric primitives, shared types |
| `quantbt-engine` | Rust execution core and account/lifecycle state |
| `quantbt-strategy-ir` | Bounded strategy IR v1 |
| `quantbt-batch` | Shared-market batch execution |
| `quantbt-portfolio` | Target preflight primitives |
| `quantbt-package` | Package transaction preflight primitives |
| `native_event` | Thin PyO3 extension `_quantbt_native` |

## Ownership rules

- Rust-generated contract constants are sourced from the product registry.
- The PyO3 layer must not duplicate lifecycle or accounting rules.
- Native results carry typed, flat buffers; Python adapts them to public result
  objects without replaying execution as a hidden second engine.
- The Python oracle stays available for differential testing, investigation,
  historical replay, and fallback.

## Current release status

The staged pair is `quantbt-engine==1.0.8` with
`quantbt-native==0.4.0`. It is an exact staged pair only, and the native
package is not published. On the certified local Linux/CPython evidence matrix,
`auto` promotes static command tapes at 10,000+ bars and bounded Native
Strategy IR/batch requests at 2,000+ bars. All callback, reactive, portfolio,
and package routes remain Python. Consult the generated
[compatibility matrix](../contracts/generated_product_compatibility.md) rather
than assuming that an installed extension supports a workload.
