# Phase 54A.5.6 Native Execution Exit Evidence

This artifact is machine-specific evidence, not an automatic backend promotion.
Only E0, E3, and E6 execute a native one-call score path in this phase.

| Workload | Scope | Parity | Native boundary |
| --- | --- | --- | --- |
| E0_STATIC_EXPLICIT_COMMAND_TAPE (low_churn) | measured | direct_vs_prepared_score_exact | recorded in JSON |
| E0_STATIC_EXPLICIT_COMMAND_TAPE (high_churn) | measured | direct_vs_prepared_score_exact | recorded in JSON |
| E3_NATIVE_STRATEGY_IR | measured | python_oracle_vs_rust_audit | recorded in JSON |
| E6_BATCH_OPTIMIZER_WFO | measured | serial_vs_shared_batch_exact, selected_audit_deferred | recorded in JSON |

## Non-promotion workloads

- **E1_CALLBACK**: Arbitrary every-bar Python callbacks retain an intentional Python callback boundary.
- **E2_SPARSE_CALLBACK**: Sparse callback/session behavior is compatibility infrastructure, not a one-call typed score route.
- **E4_PORTFOLIO**: Typed portfolio preflight has parity tests, but no promoted endpoint-level full native portfolio execution benchmark.
- **E5_PACKAGE**: Typed package preflight has parity tests, but no promoted endpoint-level package execution benchmark.

The score paths retain no dense audit ledger and do not invoke an audit replay. Rust remains explicit/experimental until a later workload-specific promotion gate passes.
