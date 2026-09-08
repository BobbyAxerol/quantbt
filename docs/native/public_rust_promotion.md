# Public Rust Promotion

QuantBT promotes a native route only when the request, the installed
core/native pair, the output profile, and current measurement evidence all
match. Installing `quantbt-native` alone does not make an endpoint Rust-first.

## Current Automatic Scope

With the exact supported pair `quantbt-engine==1.1.1` and
`quantbt-native==0.4.2`, `native_backend="auto"` may select Rust for one
bounded workload:

| Requirement | Required value |
|---|---|
| Workload | `NativeStrategyIR` v1 |
| Market | one aligned OHLCV symbol |
| Output profile | `score` only |
| Minimum tape | 2,000 bars |
| Contract | declared V2/V3 lifecycle, supported account model and template |
| Runtime | matching Linux x86_64 glibc CPython 3.11-3.13 companion wheel |

The public entry point is `NativeEventBackend.prepare_native_strategy_ir(...)`.
For an eligible score request, Rust owns the prepared execution and accounting
run. Python still owns construction of the public request and cold-path result
adaptation. `minimal`, `standard`, and `audit` deliberately remain Python when
`auto` is requested; use explicit `native_backend="rust"` only when the
bounded executor's documented explicit contract is the intended route.

The following remain Python under `auto`:

- static V2/V3 command tapes, including 10,000-bar tapes;
- Python callback and reactive strategies;
- generic `walk_forward()` / `train_test_split()` orchestration;
- generic portfolio, basket, arbitrage/package, options, and intrabar routes.

Static command tapes are not a partial promotion: their Phase 78 matched
public score fixture measured Rust at `52.850 ms` versus Python at `48.642 ms`.
Rust therefore remains available only as an explicit, fail-fast route there.

## Why Only This Route

The admission fixture for `NativeStrategyIR` score used one 2,000-bar typed
signal/program request, paired alternating backend measurements, and an
independent audit replay. Its median was `0.958 ms` for Rust and `34.566 ms`
for Python, with exact canonical trace/accounting parity and a `0.000 MiB`
warm RSS tail spread. These values describe that retained-output workload on
the recorded Linux candidate, not arbitrary callbacks or report-heavy runs.

The checked admission evidence is
[`phase78_public_promotion.json`](../../benchmarks/native_event/results/phase78_public_promotion.json).
It was captured before the routing-table enablement so the benchmark identity
cannot recursively include its own policy artifact. The registry stores that
immutable admission snapshot; the current resolver policy is separately tested
against the rebuilt native descriptor and installed wheel.

## Inspect And Roll Back

Every run records a structured decision. Inspect it rather than inferring the
backend from package installation:

```python
decision = result.metadata.get("native_event_promotion_v1", {})
print(result.metadata.get("native_event_backend_resolved"))
print(decision.get("reason"))
```

Set `QUANTBT_DISABLE_NATIVE=1` to force Python for all auto routes, or set
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` to keep the companion installed
while disabling automatic Rust promotion. Explicit Rust never silently falls
back to Python.

## Certification Boundary

This is A4 route promotion, not A5 engine-source-removal approval. The Python
oracle, historical compatibility-mirror retirement record, fail-closed explicit
route, and rollback controls remain required until a separately observed
shadow-release cycle is approved. The
generated [compatibility table](../contracts/generated_product_compatibility.md)
is the executable source of truth.
