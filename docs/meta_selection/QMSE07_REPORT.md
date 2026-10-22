# QMS-E07 Event WFO Qualification

## Status And Guide

**COMPLETE_LOCAL_SOFTWARE_QUALIFIED_OPT_IN:** 342 distinct scoped source tests,
72 installed lifecycle/output reruns and all 150 complete source/wheel/sdist
workload cells PASS, no unexpected skips. Privacy and registered cleanup PASS.
The [source-bound receipt](../../benchmarks/optimization/meta_selection/qms_e07_closure.json)
seals exact artifacts, verification code, matrices and protected evidence.
Entry is `1a0f892`; prepared local pair remains **1.1.2 / 0.4.3**.
Read [registration](QMSE07_QUALIFICATION.md), [unified E07 plan](../../upgrade/implement.md#qms-e07)
and guide [causality](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[selection](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[W3/account ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[cost](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10)
and [reporting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12).
Synthetic strategies qualify software, not universal decay improvement.

## Runtime And Endpoint Output

No engine, optimizer, Ridge, objective, sampler, RNG, margin, fee, funding or
lifecycle logic was changed. The runtime amendment is exactly three additive
lines in shared `PublicMetaRuntime`: retain and return immutable **current-run**
`observed_revisions` after the original successful history publication.
The guard reconstructs these exact insertions and checks all other runtime/build
bytes against entry: 322 files, no whole-file exemption. Rust bytes are unchanged.

This sidecar retains object references, not extra financial paths or a copy of
the archive. Meta off adds no sidecar. Existing records, tasks, models,
snapshots, full-pool predictions and actually applied parameters are retained.
Each revision adds the original panel, raw forward observations, typed status,
labels and availability clocks needed for further measurement from result alone.
It neither reruns financial execution nor serializes/logs private information.

```python
# Generic callback or command WFO result:
meta = result.metadata["walk_forward"]["meta_selection"]
# Prepared numeric W3 result:
meta = result.metadata["meta_selection"]

records = meta["records"]
tasks = meta["tasks"]
models = meta["models"]
observed = meta["observed_revisions"]
```

Bind each `observer_revision_id` to its actual revision and candidate evaluation
IDs. Proposal predictions are learned quantities, not raw Sharpe or Optuna
objectives. Observed forward data arrives **after** selection; it cannot be
used to retune that same fold. Invalid/censored/failed measurements are not
silently converted to zero. See [full usage](EXECUTION_WFO.md#inspect-the-actual-meta-run).
Audit exports can disclose the alpha and remain caller-controlled.

## Qualified Protocol Boundaries

| Protocol/backend | Original final account | Caller strategy ownership |
|---|---|---|
| Generic `event_driven`, Python | One continuous event account | Fresh callback factory per window |
| Generic `event_driven`, Rust | One continuous Rust financial account | Python callbacks, not a Rust-compiled alpha |
| `order_commands`, Python | One continuous original command account | Actual typed commands, no signal proxy |
| `order_commands`, Rust | One continuous original native command account | Actual typed commands, no signal proxy |
| Numeric reactive/W3, Rust | Separate reset-flat accounts | Numeric context/fill-feedback callback |

All are opt-in **Mode 4 / `per_fold_causal`**, endpoint-backed scoring.
IS and counterfactual forward diagnostics use independent fresh accounts.
Generic final output stitches factories/commands chronologically and runs the
original continuous primary account once. Pending orders, positions and protection
survive factory switches; a new parameter is not an automatic amend instruction.
W3 remains one symbol, sequential and reset-flat, with no continuous equity
or invented cross-fold pending-order carry. Safe process transport is checked
separately; arbitrary blocking Python callbacks are not hard-preemptible.

The five mature-history families retain their original clocks: generic callback
and command fixtures use the compatibility `event_lifecycle_v2_next_bar_close`;
numeric W3 explicitly uses `event_lifecycle_v3_next_open`. Eight additional
Python/Rust x callback/command x legacy/v3 tests use unequal open/close prices
and independently check timestamps, prices, fees and final equity. Explicit
command timestamps are effective bars; callback emissions after close shift
to the next bar. These clock tests do not claim an additional mature-history
study for generic v3. Actual `execution_contract_id` / `event_clock_contract`
are authoritative; the legacy WFO boundary description is not a clock override.

## Conformance

Each of five cases builds its **own** compatible 26-origin history, starting
April 2020, then makes a May 2022 decision from the matured prefix. The minimum
is 12 origins; every enabled matrix cell has **24 actual mature origins**.
Real model fit, full-pool ranking and actual selected-parameter execution are
required; missing-history fallback cannot pass this gate.

- Compare every admitted panel candidate's raw IS/forward Sharpe, return-sample
  count/std, trade activity and validity with the original endpoint result.
- Off/shadow preserve the exact trials, RNG and executed account. Active's
  selected evaluation, effective params and final applied fold params agree.
- Change future OHLCV/funding, unavailable labels and late corrections; reverse
  history insertion; reject future model artifacts. Earlier permitted snapshots,
  fits, predictions and selections remain unchanged.
- Independently rebuild final equity, returns, positions, fees, funding and
  margin using the actual applied windows, never diagnostic fold-equity joining.
- Keep declared-clock fill feedback, carried pending orders, parent SL/TP-OCO,
  cancel/amend/replace, reduce-only clipping and margin rejection unchanged.
- Check reference/prepared witness policy, numeric reference/Rust, process
  witness ownership, cancellations, deadlines and child/error cleanup.

Quantity clipping here is a partial reduce-only execution against the actual
held position. It is not certification of venue queue priority, order-book
volume splitting or new L2 simulation semantics. Existing OHLCV matching
assumptions are unchanged.

First fixture runs exposed incorrect numeric-context test API and incorrect
test expectations, not changed execution. A separate first-model comparison
exposed Numba's first thread-pool initialization in physical telemetry. The
final mutation test warms that inspection, then compares the full model basis
and permitted fit unchanged. Failed receipts remain alongside passing reruns.
The benchmark harness also retains its portable-key and meta-off rebuild
failures. No scientific tolerance or source guard was relaxed.
Final order fixtures also distinguish absolute timestamps from fold-local bar
indices and effective tape timestamps from callback emission timestamps.
The failed fixture receipts remain retained; no financial default was changed.

| Source shard | Distinct PASS |
|---|---:|
| Original revision output | 13 |
| Shared output/observer regression | 66 |
| Original lifecycle | 15 |
| Mature/no-leakage, quantity/clock and closure | 61 |
| Matrix, source guards and clean-process W3 | 12 |
| Original financial and transport regression | 175 |
| Total, deduplicated | **342** |

The additional post-handoff-allowlist closure rerun passes 13/13; it is not
counted as 13 new tests. Each installed consumer passes 36 output/lifecycle/
quantity tests, 72 reruns total; they are not additional distinct source tests.
The cost/installed matrix adds 90 source executions and 30 per exact consumer;
these are workload cells, not fabricated extra pytest cases. Independent original
account rebuilds have maximum financial difference **zero**, including meta-off.

## Cost And Artifacts

The registered 30 cells have off/shadow/active and reference/prepared variants.
Three fresh-process repeats include one untimed warmup and one complete timed
May WFO call: 8 trials, 90D IS and monthly forward, lambda 10, seed 731.
Market/runtime construction and frozen-history loading precede the timer;
search, fit/rank, observer and final execution remain inside. Independent
verification follows the captured wall/CPU/peak RSS/resident/PSS measurement.
The historical 26-fold runs check multi-fold behavior; their unregistered wall
times are not presented as matched long-horizon benchmarks.

The frozen synthetic tape is daily UTC, 2020-01-01 through 2022-05-31 (882
bars). Generic final execution retains that original full calendar, including
flat/no-command prefix bars; the current numeric W3 final account is only its
31-bar May segment. IS/forward windows, search budget and own compatible histories
are matched within each route's off/shadow/active arms. Different financial
account/protocol scopes are not an apples-to-apples callback-versus-W3 speedup.

Only descriptive medians are valid with three repeats. Process peak RSS includes
imports, history and warmup; resident/PSS after the call is a separate measure.
Five additional ownership/stage diagnostics are not included in warm medians.
Native timing blocks can overlap and must not be summed as percentages.

Primary variant: witness reuse enabled for callback/commands; required Rust
meta math for W3. These are measured **complete-study** wall times, not kernel
or per-bar throughput. Median of three warm source repeats:

| Financial route/backend | Off | Shadow | Active | Active CPU | Active process peak RSS |
|---|---:|---:|---:|---:|---:|
| Callback / Python | 925.96 ms | 1,216.00 ms | 1,210.26 ms | 1,209.74 ms | 297.69 MiB |
| Callback / Rust | 1,067.77 ms | 1,392.56 ms | 1,411.27 ms | 1,394.48 ms | 298.80 MiB |
| Commands / Python | 777.35 ms | 1,024.31 ms | 1,039.13 ms | 1,039.02 ms | 300.66 MiB |
| Commands / Rust | 702.16 ms | 1,061.13 ms | 1,062.62 ms | 1,059.06 ms | 255.00 MiB |
| Numeric W3 / Rust | 74.97 ms | 298.58 ms | 295.32 ms | 294.12 ms | 243.99 MiB |

Active adds approximately 284/344/262/360/220 ms over off respectively,
including fit/rank and full-panel forward observation. Active peak RSS changes
by +5.15/+4.16/+5.13/+2.75/+4.42 MiB on these measured process arms.
W3's percentage overhead is larger because its off baseline is only 75 ms;
shadow still fits/ranks and observes, so it is not a no-work baseline.

| Active route/backend | After-call RSS | After-call PSS |
|---|---:|---:|
| Callback / Python | 297.82 MiB | 260.65 MiB |
| Callback / Rust | 298.89 MiB | 261.31 MiB |
| Commands / Python | 300.77 MiB | 263.52 MiB |
| Commands / Rust | 255.23 MiB | 219.38 MiB |
| Numeric W3 / Rust | 244.19 MiB | 208.28 MiB |

Peak uses `ru_maxrss` captured through the call; resident/PSS uses the subsequent
`smaps_rollup` snapshot. These kernel counters/snapshots are not interchangeable.
No systematic cache speedup or significance follows from three repeats.
In particular, callback Rust is slower than callback Python on this small
unchanged synthetic financial workload. Arbitrary callback code remains Python;
certifying meta does not turn it into a batched native strategy or a new speedup.

Separate fresh-process active diagnostics, not cost-matrix repeats:

| Route/backend | Snapshot | Combined fit/select | Full-panel observer |
|---|---:|---:|---:|
| Callback / Python | 0.401 ms | 57.968 ms | 228.961 ms |
| Callback / Rust | 0.401 ms | 50.505 ms | 222.940 ms |
| Commands / Python | 0.435 ms | 51.486 ms | 163.231 ms |
| Commands / Rust | 0.405 ms | 51.388 ms | 152.514 ms |
| Numeric W3 / Rust | 0.467 ms | 50.386 ms | 45.703 ms |

The current runtime has a combined `fit_select` timer, not independently
observable search/fit/rank stage timers. These cold diagnostics must not be
subtracted from the warm medians above. Each original final callback account
reports 882 callbacks, two emitted commands, one primary run and one existing
audit oracle/static verification. The Rust callback reports 882 PyO3 boundary
calls; the Rust command tape reports one native static execution boundary.
This is original audit verification, not replay added by the meta sidecar.
W3 keeps one prepared market allocation, zero market copies per score and
original-pass witness packets with zero market IPC bytes; its numeric grid
emits 17 commands in the inspected segment. No claimed all-Rust strategy.

Ridge's requested native blocks resolve transform/Gram-solve/rank to Rust;
schema encoding, historical scaling and diagnostics retain their recorded
Python/NumPy roles. BLAS is observed at one thread. The existing W3 telemetry
also reports a configured-one versus observed-four Numba/libgomp pool mismatch;
the declared serial native numeric contract is not a certificate for every
library pool. That observation is retained, not rewritten as a one-thread
Numba proof. No new thread policy or parallel numeric method is activated.

Fresh core wheel and sdist contain the exact 260 canonical modules.
The identical native wheel is reused only after complete native-source, build
lineage, wheel and extension hash checks. Each isolated consumer validates
loaded origins before/after and reruns all 30 mature/off cells; checkout runtime
is not an installed proof. These are Linux CPython 3.12 **local** results.
Remote Ubuntu/CPython matrix and public-index proof belong to approved E08.

| Exact retained artifact | Bytes | SHA-256 |
|---|---:|---|
| Core wheel | 1,042,937 | `9bac93c15118487abf3926c6879b54c322379b368ed5f8cd40a425f6baa6a9f1` |
| Core sdist | 926,477 | `da337eb708c5a979f73a4bdf8c271662d8764d65998ddc58492632db8f295e85` |
| Unchanged native wheel | Original artifact | `f5fe1ec4d9268752733ba2c7023cc0e2548215986a8cd73fb6fafb285422a3b6` |

Loaded native extension SHA-256 is
`e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba`.
All 260 canonical module origins/hashes are verified before and after each
installed proof; the checkout supplies public fixtures, not financial runtime.

## Economics And Remaining Decisions

For valid original observations only:

$$
R=(S_{IS,a}-S_{F,a})-(S_{IS,m}-S_{F,m})
  =(S_{IS,a}-S_{IS,m})+Q,
\qquad Q=S_{F,m}-S_{F,a}.
$$

Keep the IS contribution and forward-Q separate. One synthetic forward month
cannot estimate reliable confidence, real-market edge or persistent decay
improvement. Same-winner zero R/Q is also valid software behavior.
No private strategy, real-market economic retune or default promotion occurred.

Actual active May-fold points, same on the matched reference/prepared variants:

| Fixture | IS contribution | Forward Q | R | Same winner |
|---|---:|---:|---:|---|
| Callback / Python and Rust | -2.469808 | +0.974386 | -1.495421 | no |
| Commands / Python and Rust | 0 | 0 | 0 | yes |
| Numeric fill-feedback grid / Rust | 0 | 0 | 0 | yes |

The callback's forward Sharpe improves while its measured decay reduction is
negative; this is an allowed selection outcome, not a license to retune the
synthetic example. Shadow's **applied** winner remains native even when a
different proposal is exported. All four raw observations are VALID for these
point rows. No interval or economic PASS is inferred.

No endpoint or mode was renamed. W3 carry/shared multi-symbol/public meta batch,
Mode 2 bootstrap, options/Nautilus meta and other unapproved methodologies remain
separate capabilities, not hidden E07 engine work. E08 integrated artifacts,
remote matrix and owner release decision are next only on separate approval.

## Reproduction And Retention

See the [qualification tools](../../tools/qms_e07_qualification.py),
[package proof](../../tools/qms_e07_package.py),
[closure gate](../../tools/qms_e07_closure.py) and
[public numeric grid](../../examples/wfo_meta_reactive_grid.py).
New lanes/prefixes are required for reruns; immutable output files are not
overwritten. Exact artifacts, staged source, all histories and pass/fail logs
are retained. Only registered inactive build/consumer scratch may be removed.
No push, workflow dispatch, merge, tag or publication belongs to this phase.

Run the examples from a repository checkout with the prepared local pair and
optimization dependencies installed; public fixture modules are not wheel APIs.
[Cleanup](../maintenance/QMS_E07_CLEANUP.md) removes only four registered inactive
build/consumer roots, preserves **941 protected file hashes** and observes
**1,151.35 MiB** more available space. Exact artifacts, staged source, histories,
passing and failed logs/receipts, tooling and offline dependencies remain.
Cleaned consumers need a fresh isolated installation before rerun.
