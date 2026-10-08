# MET-03 Local Certification

**Latest source:** read the [copy/cost closure](MET03_COPY_COST_REPORT.md)
for round-trip cache correctness, costs and new artifacts. The historical
[performance follow-up](MET03_PERFORMANCE_REPORT.md) and
[owner recheck](MET03_RECHECK_REPORT.md) closes five
additional reporting edge defects with 667 tests and fresh installed artifacts.
The results/hashes below remain the original MET-03 qualification, not proof
for the subsequently changed source.

**COMPLETE_LOCAL.** MET03-T01..T10 PASS for the admitted coverage. Owner final
review remains pending. No push, workflow, merge, tag, version change or upload.

Read the [public usage](PUBLIC_REPORTING.md), [contract](REPORTING_CONTRACT_V1.md)
and [phase plan](../../upgrade/implement.md#metrics-met-03). Legacy/scientific
defaults, accounting, optimizer/RNG and engine ownership are preserved; new
report populations are optional and explicitly witnessed.

## Implemented

- Stable keyword-only `reporting=ReportingRequest(...)` on endpoint/result
  `full_report`, `show_metrics` and `quick_plot`; omission preserves the exact
  legacy method body and dictionaries. Lazy public exports for request,
  contract, coverage and bounded caller-owned cache. No constructor/backtest
  routing or dataclass financial-field change.
- Namespaced account-period, execution, closed-trade and closed-action groups;
  explicit currency, baseline, frequency, sample counts, validity and reasons.
  The dictionary is opt-in, not a replacement scientific/WFO scoring format.
- Observed drawdown episode rows, open/censored null recovery timestamps,
  fractional hours/days, baseline-aware equity plot and deduplicated legends.
  Dark/light layout and nonblank-pixel tests pass; no unseen intrabar claim.
- Explicit ledger/execution witnesses refer to the same completed result.
  Missing/truncated attribution, scalar-only paths or absent grouping are N/A,
  never fake closed actions or an implicit simulation rerun.
- Updated endpoint guide, contract/dictionary, docs map, README, changelog and
  runnable public synthetic example. No private alpha/data was needed.

## Correctness And Preservation

**598 tests passed, zero failures/skips** in the qualified source run, covering
all metrics oracles/reducers, intraday scope, Phase 49 schedules, the event-driven
facade and native V2 contracts. Python/Numba Reporting V1 values and episode
rows agree; pinned QuantStats 0.0.81 comparisons preserve matching conventions
and expected differences instead of replacing our independent oracle.

The immutable MET-01/02 source baselines are retained. Of 325 protected files,
**321 byte hashes are exact**; four public files admit only lazy exports or the
explicit reporting branch. AST checks remove that branch and require the
entire legacy method body/signature and remaining source to match the parent.
Financial kernels, reducers used by WFO, objectives, optimizer and Rust remain
unchanged. Baseline expected values were not rewritten or tolerances relaxed.

Actual completed executions exercised pct-equity, shared portfolio, basket,
arbitrage, intrabar/session, generic callback, command-tape and numeric W3.
Raw equity/returns/positions/fees/funding/margin, liquidation fields and retained
orders/fills/events/package metadata are canonically compared before/after
reporting. W3 reset-flat segments remain independent, never fabricated into
continuous account performance. Options-compatible result data is tested as a
report surface, not new option execution certification.

Mature meta off/shadow/active tests use real fit predictions in public synthetic
history. Reports leave accounting, selected decisions, proposal sequence,
scientific metrics and Python/NumPy RNG exact. Seeded Mode 1/per-fold decay and
Mode 4/per-fold causal selection/account sentinels also pass. This is read-only
report correctness, not a new meta-economics study.

| Gate | Certified coverage |
|---|---|
| T01 | Default APIs/keys, opt-in configuration, strict contracts and finite JSON |
| T02 | Independent fixtures, Python/Numba equality, pinned QuantStats conventions; native V2 preserved |
| T03 | Scope-entry baseline, carried outcomes, action closure, costs and explicit disjoint-account rules |
| T04 | Actual representative routes, compact/audit/score coverage and unavailable policies |
| T05 | Exact financial fields/arrays/metadata, source guards and no replay |
| T06 | Mature meta modes, old scientific results, seeded decisions/account and RNG |
| T07 | Formatted units/validity, open recovery null, dark/light plots, pixel/layout/docs/example checks |
| T08 | Twelve preregistered cost cells, bounded cache, primary peak RSS under 2 GiB |
| T09 | Exact local wheel and sdist, native identity, outside-checkout imports/examples/plots, dependency checks |
| T10 | Preserved failures/log hashes, allowlist/privacy, current source and owned-scratch cleanup |

Rust Reporting V1 is **not implemented or claimed**. Native MetricContractV2
has different definitions and remains the execution/scientific authority;
comparing it as the same-report oracle would be incorrect.

## Measured Costs

Local CPython 3.12.13, NumPy 2.2.6, pandas 2.3.3, Numba 0.65.1, SciPy 1.18.1;
one thread, fresh workers, one warmup/five repetitions. CPU is not exclusive;
host load and five-sample p95 noise limit precision. No post-result latency
threshold or blanket 1-10 ms claim is invented. Performance acceptance remains
owner review, separate from correctness and registered resource budgets.

Account workload includes snapshot/hash, reduction, retained episode rows and
grouped dictionary construction. Formatting and plot rendering are separate.

| Observations | Backend | Fresh public p50 / p95 | Observations/s | Peak RSS |
|---:|---|---:|---:|---:|
| 2,000 | Python | 8.816 / 9.143 ms | 226,858 | 201.02 MiB |
| 100,000 | Python | 440.436 / 657.913 ms | 227,048 | 172.15 MiB |
| 1,000,000 | Python | 3.460 / 3.931 s | 289,034 | 331.34 MiB |
| 2,000 | Numba | 2.420 / 3.551 ms | 826,395 | 304.46 MiB |
| 100,000 | Numba | 43.827 / 70.266 ms | 2,281,707 | 270.11 MiB |
| 1,000,000 | Numba | 326.657 / 351.821 ms | 3,061,311 | 423.95 MiB |

Snapshot adaptation alone: 0.88-0.91 / 29.49-29.83 / 281.49-283.62 ms.
Warm Numba reduction with episodes: 0.672 / 3.901 / 26.758 ms. First account
compile/reduction: **5.54-5.77 s**; ledger first-call compilation is **1.22-1.30 s**.
Python is therefore the reporting default, with Numba explicit. Primary peak
RSS includes dependencies/JIT, and the 2k worker also renders the plot.

Public cached p50 still snapshots/hashes and serializes: Python 1.367 / 30.189 /
279.994 ms, Numba 1.338 / 33.317 / 301.391 ms. A direct reducer cache hit is not
this workload. Episode dictionary/frame adaptation scales with requested rows;
serialization was 0.25 / 2.07 / 20.09 ms in the Python account worker. Text
formatting was 0.05-0.10 ms. Requested detail is never silently discarded.

| Recorded population | Backend | Group/sort/reduce p50 | Public account + ledger p50 / p95 |
|---|---|---:|---:|
| 32 closed outcomes | Python | 0.605 ms | 2.590 / 2.941 ms |
| 32 closed outcomes | Numba | 0.603 ms | 5.023 / 6.915 ms |
| 2,000 closed outcomes | Python | 4.696 ms | 13.709 / 14.260 ms |
| 2,000 closed outcomes | Numba | 4.338 ms | 7.774 / 11.937 ms |
| 2,000 opposite-side legs / 1,000 actions | Python | 7.353 ms | 21.940 / 27.593 ms |
| 2,000 opposite-side legs / 1,000 actions | Numba | 7.043 ms | 11.038 / 12.220 ms |

Group/sort/Python attribution remains part of ledger costs; Numba is not
automatically better for a small ledger. No execution speedup is claimed here.

Matched compatibility timings use the immutable parent method and the new
public default on the **same observations**, with equal returned values:

| Worker / observations | Parent p50 | Current default p50 |
|---|---:|---:|
| Python / 2k | 1.432 ms | 1.290 ms |
| Python / 100k | 8.159 ms | 8.123 ms |
| Python / 1M | 83.240 ms | 80.721 ms |
| Numba-enabled worker / 2k | 1.324 ms | 1.263 ms |
| Numba-enabled worker / 100k | 8.788 ms | 8.592 ms |
| Numba-enabled worker / 1M | 75.951 ms | 85.732 ms |

The last cell is **12.88% higher**, retained without alteration. Both default
calls execute the same legacy body/reducer; worker name denotes the later
opt-in experiment, not a changed legacy backend. Five nonexclusive host samples
do not establish a causal algorithm regression or a latency guarantee. New
opt-in report work is not a matched legacy speedup. Full distributions are in
the [benchmark receipt](evidence/met03/run-20261007T195815741400Z/benchmark.json).

## Installed Artifacts And Cleanup

Local wheel/sdist and outside-checkout consumers PASS, with all **275 canonical
package modules** byte-equal to source. `pip check`, public example, report JSON
and rendered plots pass in each isolated environment. The unchanged native
0.4.3 wheel is reused after Rust-source/build-lineage/extension checks; no Rust
build occurred. Native extension SHA256 is
`e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba`.

Core wheel SHA256:
`626c69b4116368d490967ea0934e51ac48fac007f8883e7358c5ae090424f065`.
Core sdist SHA256:
`cc8b20508d964b2da3796d0bc9f5b54657bc7299d762ec5b082d4104fcf6ba36`.
Exact artifacts remain under `.maturin/met03/run-20261007T200542851857Z/dist/`.

Exploratory fixture/pickle checks, old tooling-pair rejection, cache-path failure,
missing offline visualization dependency and DNS failure remain recorded. The
correct isolated pair passed after the missing public dependency wheels were
downloaded with approval; artifacts then installed fully offline. Primary
tooling/native versions were not changed. No failed proof was relabeled PASS.

All owned build/consumer/JIT/pytest/plot scratch was removed; exact artifacts,
successful/failed receipts, logs and offline dependencies remain. See the
[cleanup receipt](../maintenance/MET03_CLEANUP.md). The 3 GiB / 20k concurrent
inode / 2 GiB worker RSS budgets pass; consumers were cleaned sequentially.

## Handoff And Limits

No open in-scope arithmetic, compatibility, attribution, raw mutation or
artifact blocker was found. Automatic closed-ledger production from insufficient
raw, a Rust Reporting V1 reducer, flow-adjusted accounting and new financial
domain certification are not silently promised. Exact new conventions may
produce different numbers from legacy aliases; legacy scientific values remain
unchanged. This does not retune WFO/meta or establish new trading edge.

Local CPython 3.12 is certified here. Ubuntu/CPython matrix, manylinux/public
consumer proof, final owner acceptance and any publication require separate
approval. Receipts: [source](evidence/met03/run-20261007T195815741400Z/receipt.json),
[installed artifacts](evidence/met03/run-20261007T200542851857Z/receipt.json),
[closure](evidence/met03/closure.json). Reproduce with
`tools/metrics/run_met03_qualification.py --stage source` and `--stage package`;
fresh lanes are required, and cleaned consumers must be reinstalled.
