# HMA Saved-Account Finalization

The [approved observer repair](M5_11_6_HMA_OBSERVER_CLOSEOUT.md) completed all
57 decisions/panels and saved both original final accounts, commands, fills and
metrics. It stopped during the last independent replay at 2,336.81 MiB peak,
above its admitted 2,304-MiB allowance. The inherited exception text still says
"900 MiB"; the admission/peak records establish the actual final-stage limit.
The stopped run remains FAIL_RETAINED, never overwritten as PASS.

## Remaining Work Only

- Byte-exact custody of all 57 corrected folds, schedules and saved accounts.
  No optimizer, observer, alpha compilation or new account generation.
- Two serial fresh-process original-engine replays of saved command tapes;
  compare equity, returns, positions, fees, funding, margin and fills exactly.
  Keeping one audit alive at a time avoids the retained two-account peak.
- New custody markers explicitly reference original financial-complete markers;
  they do not claim a new financial execution. Original paths/fills/commands and
  failed receipts remain. New completion derives from successful replay proofs.
- Recover pairs/economics from verified selections/revisions, using the existing
  reducer without redoing financial work or changing the frozen estimator.
- Continue the separately registered checkpoint qualification and shared
  economics closeout. No M5-11.7, new experiment, CI or release is activated.

## Admission And Cleanup

Reuse exact HMA native artifact/environment/source/market. New retained ceiling
128 MiB, disposable JIT scratch 16 MiB, one process/one numeric thread at a time,
2,304 MiB worker and 3 GiB aggregate RSS, 512 MiB available host RAM floor and
5 GiB disk reserve beyond forecast. Each replay timeout is 300 seconds; keep
the original absolute queue deadline. No new build/env or other alpha run.
Retain source/log/receipt hashes before exact inactive scratch cleanup.
