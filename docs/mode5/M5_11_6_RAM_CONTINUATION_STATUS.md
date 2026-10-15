# M5-11.6 RAM Continuation Status

## Current Update

The earlier three-worker snapshot below is historical. SC subsequently reached
57 complete folds but exceeded its individual memory cap during final-account
preparation; the peer coordinator also stopped HASH at 54 complete folds.
HASH subsequently completed all 57 folds and its final accounts/exact replay.
[SC's final accounts and independent exact replays also completed](M5_11_6_SC57_FINALIZATION_STATUS.md)
at 2026-10-16 06:31 Asia/Saigon, using all 57 saved corrected folds with no new
searches or label panels. HMA continues unchanged. The independent HASH launch
and earlier three-worker snapshot below are historical, not current pending
SC finance. Whole-phase qualification/economic closeout still remains open.

## Live Readback

Observed **2026-10-16 01:31:55 Asia/Saigon**. The earlier workers stopped
because host available RAM fell below 512 MiB. Their old PIDs are terminal,
not completed studies. Three new owned workers are running:

| Alpha | PID | Retained completed searches | Current work |
|---|---:|---:|---|
| HMA | 997113 | 29 / 57 | Fold 29, June 2024; 96 new attempts saved |
| HASH | 1002237 | 49 / 57 | Repair fold 44; 44 corrected/verified folds complete |
| SC | 1002291 | 35 / 57 | Repair fold 12; 12 corrected/verified folds complete |
| VWAP | Not rerun | 57 / 57 | Existing finance/replay retained |

For HASH/SC, `128 attempts` in a repaired fold denotes its **original retained
search**, not 128 new proposals. After their saved pools are repaired, they
automatically continue the incomplete studies at IDs 49/35, respectively.
The interrupted studies restart at trial zero; exact partial Optuna recovery
is not claimed. All completed optimizer results and prior partial journals stay.

## Observer Defect And Approved Repair

The new independent admission check caught the
[V1 peer observer defect](M5_11_6_RAM_CONTINUATION_OBSERVER_FINDING.md).
HASH folds 42--48 and SC folds 5--34 had valid saved IS searches and outer
accounts, but the private recovery wrapper rejected auxiliary observer engines.
The resulting failed labels must not be called valid meta evidence.

The owner approved [repair from saved pools](M5_11_6_PEER_OBSERVER_REPAIR_V2.md),
without another completed optimizer. Unaffected histories are restored exactly
(HASH 42, SC 5); affected full IS pools feed the actual learner/selector again,
followed by real original-engine forward observer accounts. New models,
decisions and revisions may differ. Old failed revisions are retained separately
and never inserted into the corrected history. HMA is independently continued
from its unaffected 29-fold prefix.

First live repair checks passed:

| Check | HASH fold 42 | SC fold 5 |
|---|---:|---:|
| Actual forward labels | 17 | 16 |
| `OUTCOME_FAILED` | 0 | 0 |
| Selected observation daily samples | 30 | 29 |
| Selected-forward/outer measurement mismatches | 0 | 0 |
| New optimizer attempts | 0 | 0 |

The saved search files are byte-exact. HASH's first corrected fold actually
fits/ranks (`META_MODEL_PROPOSAL`); SC's early fold correctly remains
`META_SUPPORT_INSUFFICIENT`, not artificially forced to fit. Later fit/quality
coverage still belongs to the ongoing study. Completion receipts are blocked
if selected-forward/outer measurement differs; failed panels stop the repair.

## Verification And Resources

Final-source focused tests: **23 continuation tests + 11 peer-repair tests**.
Actual public-entry cold proofs restored HMA29/HASH42/SC5 with **zero new
optimizer or financial executions**. These cold proofs alone did not establish
live observer correctness; the first live repaired panels above supply that
additional check. The live readback reverified **2,171 source/input/artifact
identities**. All source-pinned V1 helpers and the running HMA sources remain
unchanged; new private operational helpers own the repair.

Point-in-time resources: aggregate owned RSS **1.33 GiB**, host available RAM
**2.72 GiB**, free disk **6.66 GiB**. Remaining joint output/scratch forecast is
approximately **373 MiB**, beyond the mandatory 5-GiB free-space reserve.
Keep aggregate owned RSS at 3 GiB, the 512-MiB host floor, one numeric thread
per worker and existing worker guards. These are not full-run peak estimates.
Original absolute deadline remains **2026-10-17 11:30:20 Asia/Saigon**.

```bash
systemctl status quantbt-m5116-hma-ram-resume-v2.service
systemctl status quantbt-m5116-peer-observer-repair-v2.service
```

No unrelated process, notebook, collector or trading service was stopped.
No build, new environment or market download was required.

## Custody And Cleanup

Private evidence remains under
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01`:

- `ram-resume-hma-v2`: registration, exact 29-fold custody, cold proof,
  helper archive, launch/status/logs and continued HMA journals.
- `peer-observer-repair-v2`: complete saved search custody, explicit failed-label
  review, cold proofs, helper archive, launch/status/logs and corrected journals.
- `ram-resume-v2`: retained failed all-peer admission and its original helper
  source archive. It is not a passing qualification.
- `ram-resume-maintenance-v2/live-readback.json`: live PID/source/search/observer
  crosschecks and exact qualification/archive pins.
- `ram-resume-maintenance-v2/result.json`: cleanup of four inactive test roots;
  2,060 fixture files and 19 internal pytest links removed, **2,542 protected
  hashes** reverified. Observed free-space increase **9.46 MiB**, not the
  115.9-MiB apparent hard-linked fixture size. Active JIT/evidence remain.

Registration SHA-256:

- HMA: `334875321b1d43449d1ce69acde9c48d4b8d8964de8d392dc9cabb218bed8b85`.
- Peers: `86858db90b29256fcfe49a60acae6c51f58ba58cdd447b0ea8c9238560d3b1fc`.

M5-11.6 remains **IN_PROGRESS**. Complete repaired histories, remaining studies,
full continuous accounts/replay, chronology/economics and final cleanup are
still required. This is no economic promotion or phase certificate. M5-11.7,
M5-12, CI, push, merge, tag and publication remain unactivated.
