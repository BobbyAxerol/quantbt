# M5-11.1 Missing Native Tranche

Status: **216 MISSING ACCOUNTS COMPLETE; FULL DIAGNOSTICS IN PROGRESS**.
Authority: [ordered local completion](../../upgrade/implement.md#mode5-m5-11-ordered-execution-20261012).

The missing-only inventory executed indices 56-127 for HMA, HASH and VWAP,
72 configurations each. The original 128-point designs, source alphas, 2020
preload and continuous 2021-2023 accounts remain unchanged. No completed
configuration was rerun and no censored attempt was relabeled successful.

All 216 results pass original compiler, typed/native lifecycle and terminal
checks plus independent fixed-fill accounting with residual zero. Fresh Python
oracle coverage remains control-only, not per bulk candidate. This tranche
adds no new Python-oracle executions.

| Alpha | New Configs | Profitable | Losing | Zero Return | No Fill | Median Return | Median Defined Sharpe | Median Worker |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HMA | 72 | 7 | 62 | 3 | 3 | -10.78% | -0.860 | 61.38 s |
| HASH | 72 | 10 | 62 | 0 | 0 | -3.82% | -0.348 | 33.15 s |
| VWAP | 72 | 7 | 24 | 41 | 41 | 0.00% | -0.662 | 12.39 s |

These are the new tranche's marginal summaries, not statistics for the complete
128-point panels. Defined Sharpe excludes undefined values only from that
descriptive median; their rows and masks remain in the evidence.

The supervisor took **4,092.284 s (68.20 min)**. Maximum worker RSS was 462.45,
495.19 and 440.76 MiB respectively. Actual returned work comprises 261,026
native feedback calls and 216 final normal-native calls. Each submits the full
26,280-bar market tape; the resulting 6,865,439,760 request-bars are not measured
internal kernel iterations or independent financial observations.

Cold closeout verified 5,185 source/artifact/output pins in **5.584 s**, adding
zero financial executions. The source-owned accounts still need complete cold
panel admission and the registered probes/matrices/dossiers before downstream
search and forward claims. Negative results do not establish absence of alpha
edge; neither do the profitable configurations establish method improvement.

| Private Receipt | SHA256 |
| --- | --- |
| `incremental-tranche03/result.json` | `b6aa47c5929ebf26100fcf8533287946b50dd711b540c855ac11697d4b5f0e3b` |
| `incremental-tranche03/cleanup.json` | `acb9dae884ebd005763e04a4cb3da8e92d11e9b28f33c420459551c1b2b05e6d` |
| `incremental-closeout03/result.json` | `547fde930b0a20f8222727f04982056da58d2406ae80701d705cbef63ea08949` |

The earlier failed closeout asserted committed steps without subtracting retries.
It remains retained; the corrected receipt verifies
`bar_steps - bar_retries == 26,280`. All owned workers were reaped. No new build,
environment or disposable scratch was created; cleanup deleted nothing. Exact
source, private alpha/data, failed attempts, logs and artifact hashes remain.
No CI, push, publication, deployment or independent-forward claim is implied.
