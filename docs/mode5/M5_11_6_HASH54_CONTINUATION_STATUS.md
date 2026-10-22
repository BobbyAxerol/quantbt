# M5-11.6 HASH54 Continuation Status

## Running Independently

At **2026-10-16 04:55 Asia/Saigon**, HASH was running under its independent
`quantbt-m5116-hash54-v3.service`, worker PID **1078522**. All 54 complete
corrected folds were restored; July 2026 (ID 54) had six new attempts saved.
HMA's separate service remained active. SC and VWAP were not restarted.

The previous peer coordinator stopped HASH because **SC**, not HASH, crossed
its individual RSS allowance. SC's 57 search/selection/observer folds remain
saved, but its final continuous account/replay is still pending. This HASH-only
restart does not resolve or certify that remaining SC work.

## What Was Preserved

The [approved operational contract](M5_11_6_HASH54_CONTINUATION.md) restores
original candidate pools, native/active decisions, existing models, canonical
revisions and exact maturity snapshots in order. It does not reobserve or
reoptimize completed folds. The corrected auxiliary-observer pass-through and
selected-forward/outer measurement guard remain active for the last three
folds and final accounts.

The interrupted 113-attempt journal is retained unchanged. Its study restarts
at trial zero, not from a fabricated RNG checkpoint. The first **six** restarted
attempts matched the old partial journal exactly in params, state, objective
and user attributes, excluding only proposal wall-clock time. This is an early
readback, not certification that all 113 attempts have replayed yet.

## Proof And Resources

- Five focused tests passed: HASH-only scope, canonical witness/tamper rejection,
  live auxiliary-engine compatibility, phase-specific caps and final-admission
  host headroom. No new optimizer was run to benchmark or qualify this adapter.
- Actual original public-entry cold proof restored all **54 folds**, with zero
  new optimizer or financial executions. Model/snapshot identities matched.
- The live readback reverified **2,424** registered source/input/artifact pins
  and confirmed the new PID/command. All source-pinned HMA/V1/V2 files remain
  unchanged; the new helper source archive is retained.
- Point owned RSS was approximately **0.98 GiB** including HMA; host available
  RAM approximately **2.78 GiB**, disk free **6.58 GiB**. No resource guard was
  disabled. Search remains capped at 900 MiB. Final allocation is admitted
  separately, up to 2,304 MiB, within the unchanged 3-GiB aggregate and projected
  512-MiB host reserve. It has not been exercised by this startup receipt.
- No disposable test fixture tree was created, no build/environment/download
  was needed, and active JIT scratch is retained for the running worker. The
  previous peer scratch was already cleaned with its verified receipt. Exit
  cleanup removes only the new inactive registered JIT, not scientific evidence.

```bash
systemctl status quantbt-m5116-hash54-v3.service
```

## Receipts And Remaining Work

Private lane:
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/hash54-continuation-v3`.
It contains registration, exact prefix custody/lineage, cold proof, five-test XML,
helper archive, launch/status/logs, and `live-readback-and-test-cleanup.json`.

Registration SHA-256:
`38bd7a24f1370ba2504b457b0b75c00f661c22d1330b5c55901a1be20c621752`.

Original absolute deadline remains **2026-10-17 11:30:20 Asia/Saigon**, not a new
48-hour allowance. Three HASH studies, original full continuous accounts and
independent replay, economics and final qualification remain. M5-11.6 remains
**IN_PROGRESS**; no next phase, remote CI, push, merge, tag or publication runs.
