# M5-11.1 Native04 Closed Checkpoints

Status: **TWO_COMPLETE_CELLS / HASH_CENSORED / FULL_PANEL_INCOMPLETE**.
Authority: [ordered closure](../../upgrade/implement.md#mode5-m5-11-goal-closure)
and guide [comparison/work units](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

## Actual Closure

The exact registered supervisor returned at **2026-10-11 10:42:49 UTC** with
`INCOMPLETE / TRANCHE_TIME_CAP`, no supervisor errors, zero automatic retries
and all owned children reaped. Independent host review found the original
supervisor and three worker handles absent. This differs from the earlier live
checkpoint; neither historical observation nor the old censored attempts changed.

| Original Configuration | HMA1 | VWAP2 | HASH2 |
| --- | ---: | ---: | ---: |
| Final receipt | COMPLETE | COMPLETE | CENSORED |
| Exit code | 0 | 0 | -9 |
| Worker wall, seconds | 20,191.936 | 1,253.506 | 21,603.181 |
| Returned account passes | 1,874 | 123 | 2,052 lower bound |
| Native / Python passes | 1,873 / 1 | 122 / 1 | Oracle not returned |
| Returned account-bars | 49,248,720 | 3,232,440 | 53,926,560 lower bound |
| Financial checkpoint | Retained | Retained | Absent |

All accounts use the original 2020 preload and continuous 26,280 scored hourly
bars over 2021-2023. Compiler passes are work, not configurations or economic
replications. HASH's interrupted guard faults remain recorded; no terminal
account or economics is inferred from its last completed pass.

## Returned Development Results

| Final Metric | HMA1 | VWAP2 |
| --- | ---: | ---: |
| Total return | -10.1576% | -1.2182% |
| Annualized growth | -3.5075% | -0.4077% |
| Sharpe | -0.847151 | -0.071855 |
| Maximum drawdown | 11.7045% | 5.8695% |
| Daily loss ES, return units | 0.00539641 | 0.00553959 |
| Fees, account currency | 1,495.4379 | 95.9781 |
| Accepted fills | 1,871 | 120 |
| Closed / open campaigns | 935 / 1 | 60 / 0 |
| Rejected orders | 0 | 0 |
| Fixed-fill accounting residual | 0 | 0 |

These are two returned development configurations, `clean_oos=false`, not a
selector/sampler comparison, independent forward result or claim that either
alpha lacks an edge. Fixed-fill reconciliation is not independent execution.
Original full Python-owner execution and available-field parity are retained.
Native terminal output, cancellation-slot and liquidity checks are PASS under
their existing contracts. Full cross-owner remaining-quantity parity remains
unavailable: Python lacks the named native terminal fields; no state is fabricated.

## Certificate And Checkpoint Verification

The new disjoint cold checker delegates exact Candidate/source/output/receipt
verification to existing `jobs._reuse`. It then reconciles every original
`feedback_iterations.json` record with its durable returned signature pair,
native/Python account roster, bar bill and observer summary. Both cells have
the original consecutive identical command/result hashes, fully mapped final
feedback and no pending or faulted pair. No account was replayed/deserialized,
no additional financial-object signature was computed, and no checkpoint was
adopted or published by this check.

Twelve targeted cold fixtures PASS, no failures/errors/skips. An earlier fixture
construction error is retained as a distinct FAIL; it occurred before real
output qualification. Revision02 repairs that fixture and preserves source
snapshots and the old log. The original financial and shared source are unchanged.

Closed proof takes **8.714 seconds**, peak process RSS **154.578 MiB**. Cleanup
PASS removes only its exact empty inactive fixture scratch; all original
checkpoints, data, logs, source snapshots and shared environments remain.
No cache/receipt cleanup is relabeled as economic qualification.

## Retained Continuous Attribution

A separate, registered cold adapter now reduces both COMPLETE account paths
through the unchanged typed continuous snapshot and official reporting reducers.
Nine focused fixtures PASS; two parent accounts produce eight dependent
whole/annual views. No alpha, financial engine, compiler or owner pickle is run
or loaded. Initial adapter-shape FAIL remains retained: the original margin
output has two flattened columns, not one value per bar. Revision02 only admits
that retained shape as supplementary, unused measurement data.

| Annual View | HMA1 Return | HMA1 Sharpe | VWAP2 Return | VWAP2 Sharpe |
| --- | ---: | ---: | ---: | ---: |
| 2021 | -9.2697% | -1.791472 | -1.5054% | -0.190459 |
| 2022 | +2.9701% | +0.810014 | +2.3243% | +0.746115 |
| 2023 | -3.8349% | -1.336946 | -1.9865% | -1.626247 |

Later-year baselines are the actual prior closes. Returns compound; cash PnL,
fees/funding/turnover and fill/closure flows partition the one original account.
Carried watermark and held campaign stocks remain separate. Whole Sharpe is
calculated from all 1,095 daily UTC/365 returns, not averaged annual Sharpes.
Costs already in equity are not charged again. Twenty-six sealed numeric
comparisons are exact; 48 independent stdlib validation comparisons have maximum
absolute errors 1.111e-15 / 8.882e-16, within the unchanged registered tolerances.
Original 365-day growth and the official 365.25-day elapsed CAGR retain different
names and values. These checks do not add independent economic replications.

Reduction wall **7.139 s**, peak RSS **71.813 MiB**. Cleanup PASS verifies 2,560
protected pins unchanged; zero scratch/deletion. Original failures, source,
account paths, artifacts and the live HASH worker remain protected. Result SHA256:
`1590177f9674a8a1c048aa41cdfe4250230aa035e35ebf98a7a1d1a679d41b94`.
Cleanup SHA256:
`db943147df028ed88843dd8ac6487ebaf17847554e76cdefb27374ee751c71e7`.
Full rows and source-bound report remain private. This is measurement of two
configurations, not native 128-point panels, search/selector comparison or forward.

Result SHA256:
`bb7eef250a6bfe6d030cdfba4e1ba542bba40862a4b210a623efccb1b83067f8`.
Cleanup SHA256:
`f69b21d30a6de23e2cf4772f5d3c4a9985f12f0bd2681a57919784256595c088`.
HMA checkpoint SHA256:
`92c6180b13f8b8f143504a56f9657a918810ff1574f7e3ca5262ba28accb237a`.
VWAP checkpoint SHA256:
`0b92d42b88bbf3d83d3df35255551a0b751ea36a4513dcf249f5697e4fbc6a54`.
Private checker SHA256:
`412cb925a20e3f0ad16d7b5d77db759de832728b3cd7464332a94cfdf3fed5ff`.

## Cost And Next Work

| Recorded Timing, seconds | HMA1 | VWAP2 |
| --- | ---: | ---: |
| Original finance wall | 20,165.180 | 1,224.042 |
| Native-feedback compiler | 20,129.583 | 1,190.299 |
| Full Python-owner parity | 29.198 | 28.493 |
| Observer execute | 660.654 | 35.106 |
| Observer build | 3,557.841 | 109.397 |
| Compilation / result signature | 2,896.520 / 3,318.737 | 156.183 / 172.658 |
| Pin / source-resource validation | 9,670.118 / 9,470.073 | 739.763 / 727.059 |

Timers are **nested, not additive**. Observer execution is not an isolated Rust
kernel benchmark. The full fixed-point compiler and strict custody dominate
this workload; no language speedup or full-panel ETA follows from these timings.

The supervisor cleanup records exact inactive scratch removals without hash
errors, but filesystem free bytes fall by 149,966,848 during that interval; it
is not positive net-reclamation evidence. Approximately 21.8 GiB remains free
at the subsequent cold proof; this is available bytes, not an inode estimate.

Reuse both COMPLETE cells. A future HASH attempt must have a fresh registered
identity, not resume the censored compiler. Original 128-effective-point targets,
missing probes/dossiers, actual sampler-only studies, 256-query adaptive studies
and prefix-rebuilt forward remain open. First-three COMPLETE capacity and the
16-GiB queue are not promoted by two completed cells. No CI/push/release occurs.
