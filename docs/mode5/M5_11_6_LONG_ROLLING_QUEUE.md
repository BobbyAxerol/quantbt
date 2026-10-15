# M5-11.6 Long Rolling Queue

## Scope And Authority

The owner approved this local study on 2026-10-15 (Asia/Saigon), following the
[phase amendment](../../upgrade/implement.md#mode5-m5-11-6). It supersedes the
initial expanding design for this lane only. Historical evidence is unchanged.
The [rolling preflight](M5_11_6_ROLLING_PREFLIGHT.md) certifies bounded engineering,
not mature-meta economics or the completed long study.

| Contract | Frozen value |
|---|---|
| Private alpha aliases | SC, HMA, HASH, VWAP; RSI evidence reused |
| Market | Retained, hash-verified ETHUSDT 1h; no download |
| Preload | From 2020-01-01, permitted prefix only |
| IS | Rolling `730D`; first start 2020-01-02 |
| OOS | 57 monthly folds, 2022-01-01 to 2026-10-01 exclusive |
| Search | Mode 4 / per_fold_causal, legacy TPE, 128 attempts/fold, seed 731 |
| Stopping | No early stopping, warm-start or outcome-driven budget changes |
| Native selection | Existing is_only_robust/medoid, top 10%, eps 0.15, support 3, one IS shard |
| Meta | Origin-sum Ridge, lambda 10, at least 12 matured origins, Q floor -0.10 |
| Labels | Sixteen base candidates plus deduplicated compared winners |
| Primary comparison | Original native anchor versus actual meta choice from the same IS pool |
| Inference | Roles 13/12/32; three-month blocks, 16,384 draws, seed 731, family 95%, eight R/Q coordinates |

SC remains an arbitrary Python callback. HMA/HASH/VWAP retain original
actual-feedback native order semantics. Trial diagnostics use the qualified
transaction/output/reuse policies. Final accounts retain their original
continuous-account replay/audit policy, including a flat pre-OOS prefix.
Native and active final accounts are reconstructed from their saved schedules;
independent final execution compares equity, returns, positions, fees, funding,
margin and fills. Diagnostic equity is never concatenated.

There are 29,184 unique proposal slots, not 29,184 total physical executions.
Observer panels, original financial execution, final assembly and verification
are charged separately. Native anchors are captured before meta selection;
the queue does not run a second identical full optimizer. Bounded off/active
preflight is reused within its scope, not mislabeled full mature parity.

## Admission And Status

- Approved protocol committed as `ed9c80f`.
- New operational/readback tests: **71 passed in 7.73 s**. They cover append-only
  receipts, interrupted tap restoration, RAM/disk admission, fixed rolling
  calendars, exact replay comparisons, typed missingness, R/Q decomposition and
  deterministic family inference. These are not new economic outcomes.
- Early actual IS controls are reused. All eight separately registered fixed
  middle/late controls passed in **157.79 s** combined queue wall time, without
  new optimizer proposals. Both 730D IS windows end exclusively at 2024-01-01
  and 2026-09-01, retaining the complete permitted preload from 2020.
- Six account buffers and fill identities match independent original-engine
  replay. Native controls also compare transaction feedback against audit
  outputs; SC remains Python. Peak worker RSS was 543.70 MiB (SC), 597.24 MiB
  (HMA), 554.42 MiB (HASH) and 565.16 MiB (VWAP). These are fixed-point control
  costs, not full-search p50/p95 or economic results.
- Control cleanup removed exactly 41 inactive Numba files after reviewing 77
  host processes and verifying 29 retained evidence files. Apparent removed size
  was 1,386,236 bytes; observed available-space increase was 1,482,752 bytes.
  Plan/rules copies, sources, data, financial records and environments remain.
- Historical launch status: **RUNNING**, launched at 2026-10-15 11:30:20
  Asia/Saigon under `quantbt-m5116-monthly-v1.service`. HMA, VWAP and HASH have
  live independent workers and durable attempted-trial records in fold 2022-01;
  SC waits for a safe completed slot. No completed long study,
  first fitted origin, runtime speedup or economic gain is claimed here.
- Launch readback verifies 708 source pins, ten input pins and eighteen prior
  witness references. Registration SHA-256:
  `5836bba220a005883d277286d1a4a35070d8fb0d297ef460e2a98831bd77a5b0`.
  Initial three-worker observation: approximately 1.05 GiB owned RSS and
  3.16 GiB host available RAM. Each worker reports Numba and both loaded
  OpenBLAS pools at one thread. These are launch observations, not run peaks.

The full-search p95 has not been measured. The earlier conditional HMA model
of approximately 24.8 worker-hours/search pass remains a forecast, not an ETA.
Middle/late controls measure preparation/account costs at predeclared points;
they do not fabricate a full adaptive-search p95 witness.

## Supervision And Evidence

The registered private lane is
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/long-rolling-monthly-v1`.
All private alpha sources, parameter dictionaries and financial detail remain
ignored and excluded from Git/package artifacts. Focused local helper sources
and plan/rules copies are retained with exact hashes before launch.

The host supervisor launches HMA, VWAP and HASH first; SC enters the first safe
completed slot. Adaptive studies and numeric pools use one thread each. The
initial three slots are below the approved maximum of four, not a requirement
to occupy unsafe RAM. Guards enforce aggregate owned RSS <=3 GiB, available
host RAM >=512 MiB, retained <=512 MiB, disposable scratch <=64 MiB, a 5-GiB
disk reserve beyond remaining forecast, and a 48-hour queue ceiling.
No unrelated notebook, service or collector is stopped.

Operational status lives in `status.json`, each alpha's `progress.json`, and
private supervisor/alpha logs. Immutable fold records contain attempted trial
rows, ordered sampler metadata, the original native anchor, eligible pool,
actual decision/ranking, model/snapshot references, sealed labels and completion
disposition. Completed financial records precede rendering. Partial progress
does **not** certify automatic exact full-WFO recovery; seed-only resume is
forbidden.

Host monitoring:

```bash
systemctl status quantbt-m5116-monthly-v1.service
```

The service is independent of this conversation or shell. Its approved 48-hour
ceiling starts at queue launch; guard/failure can stop it earlier. No completion
time or unattended phase certification is promised.

On completion or guard/failure, the supervisor reaps its owned workers, records
terminal dispositions and reviews only its exact inactive Numba scratch before
deletion. Unknown scratch entries or host-reference failures remain for review.
Sources, data, environments, native binaries and all financial/failure receipts
are preserved. No environment installation or rebuild is needed.

## Current Guard Stop

At **2026-10-15 20:45:50 Asia/Saigon**, the supervisor recorded
`FAIL_OR_GUARD_STOP_RETAINED`: the 5-GiB disk reserve plus remaining output
forecast was unavailable. VWAP had exited successfully; the supervisor stopped
HMA, HASH and SC. The queue is **not running**, and the phase is not complete.

This happened while the separately registered HMA performance build shared the
same filesystem. Source isolation did not isolate disk consumption. The build
cache has subsequently been removed, with the candidate artifact and failed/
passing receipts retained. This is not evidence of an alpha/accounting failure,
and no exact queue recovery or automatic restart is claimed. Other services and
the other alpha source/configuration files have not been changed.

HMA retains **21 completed folds, 2022-01 through 2023-09**. Fold 21 (2023-10)
has partial attempted-trial records, not a completed study. Any continuation
must preserve completed pools, chronological meta history, seeds, fold IDs and
selection/accounting contracts; simply shortening the calendar and reseeding is
not exact recovery. Recovery needs its own custody and equivalence proof before
another long launch. The owner has requested the speed report and a continuation
proposal, not an automatic restart of the other alphas. The
[HMA performance report](M5_11_6_HMA_PERFORMANCE_REPORT.md) separates measured
fixed-window gains from conditional search forecasts and unqualified recovery.

## Remaining Exit Gates

The queue executes the original studies, saves both schedules/accounts, checks
final accounting replay, computes descriptive R/Q and registered family
intervals where supported, and performs scratch cleanup. It does not issue a
phase PASS merely because its financial workers exit successfully.

Mature early/middle/late off/shadow/active and future-mutation qualification,
independent measurement review, final report/work ledger and owner review remain
explicit phase exit work. Missing economic support remains INCONCLUSIVE; adverse
economics does not authorize retuning. A lower IS score alone is not forward
improvement. This lane does not activate M5-11.7, M5-12, CI, push, merge, tags or
publication.

## HMA Live Inspection

The subsequent owner-approved [HMA-only performance amendment](M5_11_6_HMA_PERFORMANCE_PLAN.md)
is isolated from every active source pin and from SC/HASH/VWAP. Its prospective
qualification is not an in-place modification of this running queue.

On the owner's request, only the HMA worker was suspended at 2026-10-15
20:01:25 Asia/Saigon and continued at 20:04:52. SIGSTOP/SIGCONT preserved the
same process, live account/compiler state, current Optuna study, RNG and meta
history. No fold, optimizer or financial execution was restarted. Other workers
and the supervisor were not signalled or reconfigured.

At suspension HMA had completed nineteen folds and saved 102 attempted trials
in fold 2023-08. Recent trials were completing approximately every 9-14 seconds:
this was slow work, not an observed deadlock or stalled trial. Inspection of
the nineteen completed searches found:

| Observation | Measured value |
|---|---:|
| Search wall time | 28,843.21 s |
| Original window generation/feedback wall time | 27,745.95 s, 96.20% of search |
| Sampler wall telemetry | 68.42 s |
| Physical IS generation windows / native sessions | 2,390 / 2,390 |
| Native transactional step calls | 42,969,326 |
| Full-tape re-executions in those diagnostic windows | 0 |
| Median / maximum IS generation window | 10.68 / 39.06 s |

The aggregate window timer includes original alpha preparation, the Python
command/feedback compiler and native transactions. It does not independently
attribute their individual shares or prove a Rust-kernel bottleneck. The long
runtime is concentrated in this composite actual-feedback path, not sampler
time; the former repeated-full-tape execution defect was not observed.

All 114 retained files from the nineteen completed folds remained hash-identical
before and after continuation. A twenty-second continuation check observed
19.36 CPU-seconds of work and a newly persisted trial; subsequent readback
observed 105 attempted trials in the current fold. Both other running alphas
continued advancing.

The 206.88-second suspension is recorded separately in the private
`A-HMA/inspection-01` receipts. It contributes to the current window/fold's raw
wall timer and to the unchanged 48-hour queue ceiling; it must be annotated in
performance analysis, not silently removed from historical receipts. No runtime,
source pin, trial budget, estimator, financial contract or deadline changed.
Inspection created only compact retained receipts, with no new environment,
profiler installation, financial replay or disposable cache requiring deletion.
