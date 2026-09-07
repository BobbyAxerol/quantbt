# PERF-08 Public WFO Preparation Evidence

This is an alternating paired public-facade measurement. Every pair retains the same strategy callback,
calendar, parameter space, Optuna seed/trial sequence, account configuration, and final stitched account.
Only `use_prepared_wfo_context` changes. Results are recorded only after full selection and account parity.

| Mode | Schedule | Reference median | Prepared median | Speedup | Folds | Trial rows |
|---|---|---:|---:|---:|---:|---:|
| `mode_4_is_only_robust` | `per_fold_causal` | 58.4198 s | 21.1193 s | 2.766x | 7 | 700 |

Mode 4 causal keeps one study per outer fold and never uses outer OOS for selection.

Prepared-window counters identify only immutable calendar/shard/trade-requirement reuse. They are not a
cross-run result cache, do not reuse Optuna observations, and do not suppress strategy invocations.

`memory_samples` records alternating same-process RSS/PSS observations before and after each lane. It is
a retention/plateau diagnostic, not a claim of isolated per-lane private memory; shared allocator state is
intentionally not summed as a speedup or a private-memory reduction.
