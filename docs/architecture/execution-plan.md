# Execution Plan Architecture

QuantBT separates research-facing API calls from the execution contract that a
backend actually receives. The separation keeps input normalization, planning,
execution, and reporting independently inspectable.

```text
endpoint / adapter
    -> normalize market data and account inputs
    -> immutable ExecutionPlan
    -> PreparedMarket context
    -> Python oracle or explicit Rust session
    -> typed payload/result adapter
    -> metrics, plots, and reports
```

## Ownership boundaries

| Layer | Responsibility | Must not do |
|---|---|---|
| `preparation` | Validate, align, fingerprint, and retain market arrays | Decide strategy behavior |
| `planning` | Resolve contract, profile, backend request, and output policy | Mutate account state |
| `strategies` | Emit bounded commands or a native IR | Read future bars |
| `engine_spi` | Define immutable plan/session/result boundaries | Import reporting/UI code |
| `backends` | Execute the declared plan and adapt results | Invent new trading semantics |
| `reporting` | Build metrics and visual artifacts from a result | Re-run execution implicitly |

The public endpoint remains compatible with existing alpha code. The internal
plan is an implementation boundary, not a new requirement for ordinary signal
or explicit-order users.

## Result profiles

`score`, `minimal`, `standard`, and `audit` are output-retention choices. They
do not change order timing, fills, fees, funding, margin, or liquidation.
`score` is suitable for repeated optimization; the selected candidate should be
rerun with `audit` before a research decision is presented.

## Backend selection

`backend="python"` is the readable reference/oracle. `backend="rust"` is an
explicit fail-fast request and verifies the native descriptor before execution.
`backend="auto"` remains Python-first in this release. Installed Rust alone
does not promote an execution path; promotion requires a separately published,
workload-specific compatibility and performance decision.

See [Native Rust Architecture](native-rust.md) and the generated
[product compatibility table](../contracts/generated_product_compatibility.md).
