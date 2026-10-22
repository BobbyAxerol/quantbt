# M5-11.6 Parallel Recovery Status

## Current Status

The V1 workers below stopped at the RAM guard. They are superseded by the
[RAM continuation and approved observer repair](M5_11_6_RAM_CONTINUATION_STATUS.md).
The older live PIDs and cold proofs below are historical receipts, not current
worker status or proof that subsequent V1 peer observer labels were valid.

## Historical V1 Receipt

## Qualified Continuation

This receipt implements the owner's
[parallel continuation amendment](M5_11_6_PEER_PREFIX_HANDOFF.md), without
changing alpha logic, financial execution, trials, selection or meta methodology.
HMA retains its separately qualified optimization and independent supervision.

The peer suite passed **14 tests in 24.25 seconds**: exact completed-prefix
decisions/models/snapshots, non-vacuous future-label exclusion, witness/family/
calendar/seed rejection, callback/order placeholder safety, complete final
assembly and joint HMA/peer resource guards. Together with the 18 HMA tests,
this is 32 focused tests, not a rerun of the complete research/package suite.

Both actual public-entry dry proofs passed: SC restored **5** complete folds,
HASH **42**, with zero optimizer/financial executions. The source-qualified
review binds **632 / 5,880** full observation witnesses respectively. Original
decision, panel, model, snapshot maturity and revision identities are retained;
labels enter history in chronological order, not all at startup.

## Running Workers

Host readback at approximately **2026-10-15 22:26 Asia/Saigon** observed:

| Alpha | Complete folds retained | Current fold | PID | State |
|---|---:|---|---:|---|
| HMA | 21 / 57 | ID 21, October 2023 | 926687 | Running, new attempts saved |
| HASH | 42 / 57 | ID 42, July 2025 | 933228 | Running, new attempts saved |
| SC | 5 / 57 | ID 5, June 2022 | 933331 | Running, new attempts saved |
| VWAP | 57 / 57 | Through September 2026 | None needed | Finance and final replay complete; qualification pending |

All three live workers consumed approximately one CPU each. Observed aggregate
owned RSS was about 1.21 GiB, with approximately 2.8 GiB host available RAM;
these are point observations, not run peaks. Peer workers launched at 22:24:55
and 22:25:05 Asia/Saigon under supervisor PID **933222**.

The HMA restarted fold's first **54 attempts** match the old incomplete study
exactly in params, state, objective, candidate/effective identities and
constraints. Only `qms_proposal_seconds` is excluded as timing telemetry.
This is a new physical replay of those attempts, not an exact saved-RNG resume.
Old partial costs (HMA 54, HASH 71, SC 18) remain recorded separately.

There are **13,184** proposal slots after the retained complete prefixes;
startup attempts already processed belong to those slots. No completed study
or VWAP's 7,296 proposal slots are reoptimized. Diagnostic account equity is
not concatenated: final assembly and independent six-path/fill replay still
operate on each complete 57-decision continuous schedule.

## Supervision And Limits

```bash
systemctl status quantbt-m5116-hma-recovery-v1.service
systemctl status quantbt-m5116-peer-recovery-v1.service
```

The peer service cannot signal HMA; each supervisor owns only its explicit
worker groups. Maximum aggregate owned RSS remains 3 GiB and host available
RAM floor 512 MiB. Each adaptive/numeric worker uses one thread. The 5-GiB disk
reserve includes joint remaining HMA/peer output forecasts. Original absolute
deadline remains **2026-10-17 11:30:20 Asia/Saigon**, not 48 hours from restart.
Worker/supervisor exit cleanup removes only reviewed inactive registered JIT
scratch, preserving all partial/completed financial receipts and artifacts.

## Custody And Remaining Work

Private peer lane:
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/peer-recovery-v1`.
It retains registration, per-alpha review/manifest/qualification, helper source
archive, launch receipts, logs/status and new per-fold records. Registration
SHA-256 is
`1354aaff406358e01631b7cc212d4b454b08301e140386bf8e2f98b59049a567`.
All original 708 source pins, active HMA pins and original peer native artifact
were reverified after cleanup and launch.

[Cleanup](../maintenance/M5_11_6_HMA_RESTART_CLEANUP.md) removed only reviewed
inactive dependencies, obsolete installed consumers and completed test fixtures.
Docker had no disposable build cache or orphan overlay; active resources and
database/dashboard volumes were preserved.

M5-11.6 remains **IN_PROGRESS**. Remaining folds, original final-account
assembly/replay, mature checkpoint/mutation qualification, independent economics,
work ledger and owner review remain required. Running or financially complete
workers do not constitute economic promotion or phase PASS. M5-11.7, M5-12,
CI, push, merge, tag and publication have not been activated.
