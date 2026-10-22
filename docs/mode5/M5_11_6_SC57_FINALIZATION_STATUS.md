# M5-11.6 SC57 Finalization Receipt

## Outcome

SC final continuous accounts and independent replays **PASS**. Financial work
completed at **2026-10-16 06:31:47 Asia/Saigon**, followed by successful terminal
cleanup. This closes the pending SC final-account/replay item, not the whole
M5-11.6 phase or its remaining cross-alpha qualification.

The [registered scope](M5_11_6_SC57_FINALIZATION.md) restores all 57 corrected
folds from the [peer observer repair](M5_11_6_PEER_OBSERVER_REPAIR_V2.md).
No source-pinned previous helper, alpha, engine or active HMA worker changed.

## Completed Work

- Restored 57 searches, selections, canonical revisions, outer measurements and
  cutoff snapshots, with exact original 128-attempt journals for each fold.
- Ran **zero new optimizer searches, label panels or selection decisions**.
  The 7,296 proposal slots in the result are retained historical work.
- Constructed the active and native schedules using their saved dictionaries
  through the original continuous-account assembler and original engine.
  Each covers 59,160 hourly bars through September 2026, including the flat
  2020--2021 pre-OOS prefix; OOS starts January 2022.
- Independently replayed both accounts: equity, returns, positions, fees,
  funding, margin and every fill match exactly. Diagnostic fold equities were
  not concatenated. All 114 applied fold dictionaries match sealed decisions.
- Verified label/snapshot chronology and terminal source/artifact custody.
  Six focused tests and the actual public-entry 57-fold cold proof passed.

| Continuous Account | Initial Equity | Final Equity | Total Return | Actual Fills |
|---|---:|---:|---:|---:|
| Native selector | 20,000.00 | 24,160.99 | +20.80% | 155 |
| Active meta | 20,000.00 | 21,110.12 | +5.55% | 558 |

Meta underperforms native on final equity in this cell. No gate, recipe or
parameter search was changed to improve this outcome. Historical fit/rank
witnesses exist at 42 origins, first April 2023, with 42 changed decisions;
these models were restored, not refitted in the finalization lane. R/Q family
inference and checkpoint mutation qualification remain separate closeout work.

## Resources And Cleanup

Finalization worker elapsed **263.72 s**, supervisor through reap **269.47 s**,
and through cleanup approximately **274.36 s**. These are restoration/final
execution costs, **not** timings for a fresh 57-fold optimization study.
Peak worker RSS was **1,581.52 MiB**; peak aggregate owned RSS including HMA
was **2,126.78 MiB**, below the original 3-GiB aggregate cap.

The earlier 900-MiB preparation stop remains retained. The new lane admitted
up to 2,304 MiB only at final assembly, with aggregate/host/disk guards intact.
An initial custody-review failure is also retained: three original flat
NO_VARIANCE folds serialize profit factor as positive infinity. The new review
accepts only that exact canonical case, with negative tests; no metric changes.

After SC exited, cleanup reviewed 79 host processes, removed exactly 41 inactive
registered JIT files (1,386,199 apparent bytes), and reverified **3,999 protected
hashes**. Observed available-space increase was **1,482,752 bytes**, separate
from apparent file size and concurrent host activity. Sources, financial paths,
failed receipts, artifacts, environments and active HMA cache remain intact.

## Reproducible Custody

Private retained lane: `upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/sc57-finalization-v3-02`.
Its `terminal-readback.json` binds registration, final result, handoff, accounts
and cleanup; `sealed-helpers.tar.gz` preserves the exact operational source.
Registration SHA-256: `724f10af37253f389604add0ca50a1185dcd7981eea4917ba447f9710225f9a8`.
Private alpha definitions and selected dictionaries remain ignored by Git.

HMA remains running independently. HASH/VWAP were not rerun. M5-11.6 remains
IN_PROGRESS pending HMA and common qualification/economic closeout. No M5-11.7,
M5-12, CI, push, merge, tag or publication was activated.
