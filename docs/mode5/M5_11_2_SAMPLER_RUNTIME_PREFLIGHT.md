# M5-11.2 Sampler Runtime Preflight

Status: **PASS_FUNCTIONAL_ONLY / ECONOMIC_SAMPLER_STUDIES_NOT_RUN**.
This follows the [structural preflight](M5_11_2_RUNTIME_PREFLIGHT.md) and
[approved sequence](../../upgrade/implement.md#mode5-m5-11-1). It does not choose
a sampler, seal a recipe or run financial studies.

## Actual Shared Runtime

The unchanged factory, ordered WFO bridge, effective geometry and continuation
session ran synthetic feedback with actual dependencies: Optuna 4.8.0, CMA-ES
0.12.0, SciPy 1.18.1, NumPy 2.2.6 and pandas 2.3.3. CMA proposals reached its
numeric implementation, not just a lazy constructor. Inert package namespaces
isolated sampler modules from engine initializers. This is source-runtime proof,
not an installed QuantBT wheel or public WFO consumer.

| Recipe | RSI | SC | HMA | HASH | VWAP |
| --- | --- | --- | --- | --- | --- |
| Legacy TPE | PASS | PASS | PASS | PASS | PASS |
| Multivariate/group TPE | PASS | PASS | PASS | PASS | PASS |
| Strict CMA-ES | PASS | REJECT | REJECT | PASS | REJECT |
| Legacy Sobol | PASS | PASS | PASS | PASS | REJECT |
| Versioned latent Sobol | PASS | PASS | PASS | PASS | PASS |

Twenty-one arms each ran 24 primary proposals, a fresh same-seed 24-proposal
repeat and 13-prefix/13-reconstruction/11-suffix checks. Complete ordered
witnesses and checkpoint digests match. Four incompatible spaces reject without
ordinal conversion or silent substitutes. All 640 original admitted points
retain raw/effective/candidate identities, casts, masks and coupled constraints.

The 504 primary proposals comprise 473 synthetic COMPLETE, ten geometry rejections
and 21 declared FAIL. Infeasible proposals are retained, not projected/replaced.
Natural duplicates are zero in this tiny matrix; separate controls test duplicate
handling. Sobol records one independent startup then QMC indexes 0..22. Legacy
mixed categories remain independently sampled under their explicit policy.
Latent Sobol consumes complete numeric points before masks; both VWAP branches
occur. No Sobol balance or sampler-quality claim follows.

## Failures And Rights

Ten focused tests PASS in a separately registered correction. The original
9/10-test FAIL remains: a control attempted COMPLETE on a duplicate, which
correctly rejected. Fresh controls honor PRUNED without changing inputs, seed,
draw order or policies. The original matrix was not rerun. Its pending synthetic
point is not an interrupted financial account.

Retained work totals **1,796 fixture asks**, 1,795 terminal tells and 1,419
synthetic function evaluations. Reconstruction replays prior feedback. Financial
executions/bars, economic trials and reads of actual study RNG are zero; these
asks do not count toward a 128-point landscape or 256-query economic study.
Warnings remain disclosed: 1,512 system-attribute FutureWarnings, 56 experimental
feature warnings and 162 mixed-Sobol category-independent sampling warnings.

Continuation covers only the existing version-pinned, single-owner terminal
barrier and finite-event reconstruction with NopPruner. It is not account
recovery, cross-version portability, concurrent sampling or MedianPruner proof.

## Resources And Custody

Original work: 51.709 s / 161.9 MiB peak RSS. Correction: 7.182 s / 159.3 MiB.
These are fixture costs, not economic sampler latency or speedups. Bounds were
900 seconds, one numeric thread, 32 MiB scratch, 64 MiB combined retained and
5-GiB reserve; deadlines are cooperative, not hard process-kill guarantees.

Final custody retains 6,543,635 bytes before its receipt, no scratch/deletion.
Main read-only review verified 4,004 unique source/input/dependency/receipt pins
over 223,289,488 bytes in 1.147 s before planned documentation updates. Original
plan witnesses remain historical; future qualification must pin current source.
Private schemas, traces, failures and receipts remain ignored. Workers unchanged.

| Evidence | SHA256 |
| --- | --- |
| Original registration | ba1cfb649ec924fedce2f9d9af8534e0ef9d8d166662cc9ae09babdeabb2c41f |
| Preserved FAIL result | 7809e54b3dc1cb86a0f8b26f707c3ac4bc39db0ec96bc37919241137386664d3 |
| Correction registration | 030af15a2c9c86a2d79cd9ac12759f1703d5c577a2553ba02db1bc8e0f9d8aed |
| Corrected result | 7c8e10e10dc5a8d967c7ee2e013a1a867212eb47f1980a99423647e1a81b50c9 |
| Final handoff | 9781c8cf9d99883db72a5d72151ed3ab75146cd6b56ae6487355e66847f9b974 |

## Remaining Entry

Sampler-only comparisons require matched objective, selector, domain, financial
authority and budgets, with unique-work, failures/fallback and compute accounting.
Dossiers precede recipe selection. Continuous public-provider, whole-account
raw-Sharpe and probe-rights qualification, actual formal searches and prefix
forward remain unfinished. No sampler ranking, automatic promotion or release.
