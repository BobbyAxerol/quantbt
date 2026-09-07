# PERF-07 Combined Qualification

This artifact is a current-candidate integration qualification. It intentionally does not
publish a single aggregate speedup: the covered routes have different execution contracts,
work denominators, retention levels, and Python decision boundaries.

## Qualification Scope

- Profile: `standard`.
- Candidate source/build identity is attached to the JSON artifact.
- All rows ran against the same checked source candidate; performance claims remain row-scoped.
- Reactive cross-route controls cover public WFO, shared portfolio, bounded package, and intrabar.

## Five-Mode WFO Reuse

| Mode | Exact public parity | Reuse policy | Cache hits |
|---|---|---|---:|
| `mode_1_decay` | `True` | `enabled_then_released` | 8 |
| `mode_2_sbb` | `True` | `disabled` | 0 |
| `mode_3_flat_minima` | `True` | `enabled_then_released` | 8 |
| `mode_4_is_only_robust` | `True` | `enabled_then_released` | 8 |
| `mode_5_full_robust` | `True` | `disabled` | 0 |

## Five-Mode Research Retention

| Mode | Public parity | No sidecar | Full ledger | Retention overhead |
|---|---|---:|---:|---:|
| `mode_1_decay` | `True` | 0.318826 s | 0.418372 s | +31.22% |
| `mode_2_sbb` | `True` | 0.819991 s | 0.887553 s | +8.24% |
| `mode_3_flat_minima` | `True` | 0.379051 s | 0.439747 s | +16.01% |
| `mode_4_is_only_robust` | `True` | 0.539137 s | 0.801813 s | +48.72% |
| `mode_5_full_robust` | `True` | 0.129018 s | 0.179276 s | +38.95% |

## Result

- All current qualification gates: `True`.
- Process RSS: `158.262` -> `305.062` MiB; peak observed `305.062` MiB.
- The PGO/build decision and clean-wheel proof are separate immutable artifacts required by
  `quantbt.performance_closure.v1`; this report alone does not promote a route or publish a wheel.
