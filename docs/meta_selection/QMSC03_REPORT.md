# QMS-C03: Four Samplers On W3 And R3B

## Disposition And Authority

Date: 2026-10-05 (Asia/Saigon). Branch: `feat/meta-selection-samplers`.
Owner approved **C03 sampler/scheduler qualification**, not a new meta method,
scientific study replacement or publication. Entry `b2c6225`; reviewed production
adapters `63ab385`; exact guard and expanded cases `146b285`; installed/cost
evidence `886ba9e`. Owner final review remains pending.

Status: **COMPLETE_LOCAL_APPROVED_SCOPE**; technical gate **PASS_LOCAL**.
Software qualification is not economic acceptance or permission to publish.
The final receipt is
`benchmarks/optimization/meta_selection/qms_c03_gate_receipt.json`.

Read the [unified plan](../../upgrade/implement.md#qms-c03---four-samplers-on-w3-and-fixed-batch-schedulers),
[actual contract](W3_SAMPLER_SCHEDULES.md), detailed guide
[section 4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4)
and [section 10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10).
The original guide SHA256 remains
`adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d`.

## Delivered

All four actual recipes use the existing shared factory and search space on
W3 sequential/inprocess, safe Linux fork/COW process, and explicit R3B. No new
endpoint, account engine, Ridge formula, Rust sampler or dependency upgrade.

Opt-in R3B uses **`shared_sampler_batch_r3b_v2`**: ask the full batch, suggest
before any tells, score valid unique candidates, then tell in trial order.
Omitted legacy tuple-range scheduling remains on v1. Mapping geometry or
explicit sampler policy opts into v2. Fixed matrices remain frozen-pool replay;
sampler/warm/constraint options there fail instead of being ignored.

W3 keeps Modes 1/3/4/5 and their existing permitted schedules. Nested Mode 1
records inner train cutoff and fold-derived seed. Public meta remains only
Mode 4/per_fold_causal/sequential/reset-flat/single-symbol, now with four
qualified recipes. New sampler options do not activate extra meta modes.

Batch size greater than one is a distinct search algorithm. Metadata never
calls it sequential-equivalent. Sobol's 16 attempts consume **15** relative
proposals sequentially and **12** at batch size four on the qualified fixture;
the other attempts use independent startup. No budget padding or diagnostic
RNG draws. Batch-size-one equivalence is tested on the declared numeric fixture,
not asserted for arbitrary samplers, callbacks or private constraints.

## Correctness And Parity

Exact comparisons cover proposal order, real objective values, constraint/state
reasons, selected params and original equity, returns, accepted positions, fees,
funding and margin. No tolerance was loosened. Real native wake-plan candidate
failure is PRUNED with no fake COMPLETE score, while peers keep running.

Parameter violations/duplicates consume attempts without native scoring.
Result violations retain actual COMPLETE scores but cannot win. Pending trials
become FAIL on abort/cancel. Early stop finishes the batch already asked. Warm
seeds are rescored inside budget with actual factory/schema identity, strict
availability cutoff and no old-score import. Future-market mutation cannot
change the first causal search/decision.

Off/shadow search rows and ask/tell digests match exactly for each recipe;
shadow accounts remain exact. Active results apply the selected candidate and
exercise actual Rust Gram-solve plus original same-pass witnesses. This fixture
uses a reduced engineering support threshold and does not certify future edge.
The affected C02 suite also retains its engineered active-winner-switch test.

Only three reviewed production Python adapter files changed. Financial Rust,
Ridge, sampler implementations, original guide, dependency/version/product
contracts and scientific inputs are unchanged. The C03 exact-byte guard composes
with older C02/financial locks, with negative tests for unrelated edits.

## Tests And Installed Artifacts

The C03 tests map explicitly to C03-T01..T08. They include the four-recipe
matrix, legacy compatibility, actual process cleanup, conditional/log/integer/
step/fixed geometry, CMA margin/mixed opt-in, native failure, formal/post-filter
constraints, no feasible candidate, abort/early stop, warm-start errors, inner
seed/cutoff, future mutation and frozen-pool replay. Unsupported dependency,
geometry, schedule/meta and account routes fail before strategy preparation.

Fresh core wheel and sdist consumers run with `python -I`, outside the repo's
import context. **Each artifact** passes eight recipe/scheduler cells, four
process comparisons, four fixed-pool replays, four batch-size-one comparisons
and eight shadow/active meta cells with off baselines. Actual installed extension
bytes are hashed and no child survives. All eight meta cells additionally pass
safe-process versus inprocess original search/account comparisons. C02 installed transport and its runnable
process example pass again. No Rust rebuild was needed.

Local exact pair: **quantbt-engine 1.1.2 / quantbt-native 0.4.3**.

| Artifact | SHA256 |
|---|---|
| Source-exact core wheel (expanded v2 consumer) | `5cb3e37ae056ec84aa46d3acb5de3b8e74edda14b962602832ffa4c3bdd01d07` |
| Source-exact core sdist (expanded v2 consumer) | `b3ab1756ae4b50a7482b6b7862efb073351b3c7d9acacff59965950e43eec085` |
| Unchanged C02 native wheel | `20a9a5116470ad0f385bdfe4ec902ea43ba580a6cdb208920caffda4b8d4ba7a` |

The native artifact is local **CPython 3.12 / manylinux_2_34 x86_64**, not a
manylinux2014 or six-row remote qualification claim. Receipts/logs are under
ignored `.maturin/qms08/c03-package-v2`; the prior v1 receipt is retained, not
overwritten. The final gate binds actual artifact,
JUnit, cost, example and execution-log hashes without publishing binary/data.

The first broad regression had 765 passes and 12 setup errors because this
report link did not yet exist. The missing report was supplied without changing
domain code or skipping checks. Final broad QMS/W3/WFO/facade regression:
**783 PASS** in 262.85 s, plus **18 package/release checks PASS** and one separate
eight-cell meta-process test PASS: **802 PASS total, zero skips/errors**.
This contains **132 C03-specific checks**. It is the affected regression scope,
not a claim to have rerun every repository test. Eight source/layout/contracts/
API/architecture/docs/benchmark/secret execution checks and Ruff/whitespace
gates pass separately. Optuna experimental warnings remain visible.

## Engineering Costs

See [retained raw samples](../../benchmarks/optimization/meta_selection/qms_c03_sampler_evidence.json).
Same 180 daily bars, four monthly OOS folds, Mode 4/global, 16 attempts,
seed 731, one process/thread budget, fixed/logical account costs, IS subperiods
one, batch size four, one excluded warm-up and three timed full runs per cell.
Wall includes preparation, callbacks, native scoring, selection and adaptation;
imports/initial warm-up are excluded. Sampler time measures delegated public
Optuna methods, not all QuantBT policy overhead or financial work.

| Recipe | Sequential Full Run (ms) | Sequential Sampler (ms) | R3B Full Run (ms) | R3B Sampler (ms) |
|---|---:|---:|---:|---:|
| Legacy TPE | 200.19 | 24.49 | 155.56 | 16.53 |
| Multivariate/group TPE | 205.35 | 21.56 | 167.08 | 14.42 |
| CMA-ES | 262.66 | 20.52 | 153.69 | 13.83 |
| Sobol | 185.95 | 11.61 | 147.18 | 8.64 |

Omitted legacy sequential median is **215.57 ms**, with exact decision/account
digest equality to explicit legacy TPE. Three samples on this small fixture are
not a statistical latency SLA or a historical speedup claim.

Sequential retains 256 runtime score calls / 10,560 score bars; R3B retains
128 / 5,760, because its existing precomputed stage cache avoids repeated
selection scoring. Different recipes and B>1 schedules also have different
pools. **These totals are not equal-work speedup evidence.** Every same-cell
repeat has an exact decision/account byte digest.

Reported cumulative process peak RSS is **239.57-245.28 MiB** across the ordered
cells. This includes imported libraries and previous cells; it is neither a
fresh-process delta, process-tree RSS measurement nor an RSS acceptance gate.
No new real-alpha, sampler-superiority or meta-decay improvement study was run
in C03. Existing approved scientific evidence is not replaced.

## Reproduction

```bash
python examples/wfo_reactive_samplers.py --sampler sobol
python examples/wfo_reactive_samplers.py --sampler cmaes --scheduler throughput_batch_v1
python -m pytest -q tests/meta_selection/test_c03*.py
python -m tools.qms_c03_package --output .maturin/qms08/c03-new-proof \
  --build-python /path/to/build-env/bin/python \
  --python /path/to/python3.12 --native-wheel /path/to/qualified-c02-native.whl
```

Use separate fresh output directories; do not overwrite sealed receipts. Use
the existing optimization extra and required native capability; no alpha/data
loader is needed. Constrain BLAS/OpenMP/Numba threads to one for safe process
fixtures. The installed consumer script is `tools/qms_c03_consumer.py` and the
independent final verifier is `tools/qms_c03_gate.py`.

## Remaining Ledger

No approved local C03 implementation gate remains open. No additional scientific
methodology is silently activated. C01 additional
meta activation and C01-D01 Mode 2 selector-provenance repair still need separate
approval. Carry/multi-symbol financial runtime, public meta batch selection,
C04 persisted exact RNG continuation and C05 conditional Sobol/mixed centroids
remain their own future scopes. Hard Python callback preemption is not claimed.

Current C03 source needs new remote Ubuntu 22.04/24.04 x CPython 3.11-3.13
installed-scheduler proof before remote promotion; older remote runs cannot
certify these adapters. Public release and public-index consumer proof remain
owner controlled. **No push, merge, tag, release or PyPI upload in C03.**
