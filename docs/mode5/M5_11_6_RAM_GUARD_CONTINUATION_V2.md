# M5-11.6 RAM-Guard Continuation V2

## Approved Operational Scope

The owner requests continuation after the available-RAM guard stopped all
three incomplete workers. This is an operational amendment to the
[rolling study](M5_11_6_LONG_ROLLING_QUEUE.md) and
[completed-prefix handoff](M5_11_6_PARALLEL_RECOVERY_STATUS.md), not a new
scientific phase. Frozen plans, providers and prior receipts stay unchanged.

| Alpha | Complete prefix | First incomplete fold | Retained partial attempts |
|---|---:|---|---:|
| HMA | 29 | ID 29, June 2024 | 88 |
| HASH | 49 | ID 49, February 2026 | 88 |
| SC | 35 | ID 35, December 2024 | 50 |

VWAP's 57 complete folds are excluded. Restore completed decisions, candidate
pools, model IDs, snapshots and canonical revisions in their original causal
order. Start only the interrupted study again at trial zero, with its original
derived seed and 128-attempt budget. This is not exact partial Optuna recovery.
Keep the interrupted attempts and all previous stop/cleanup receipts.

## Implementation And Admission

- Use new private `ram-resume-v2` helpers; do not edit source-pinned V1 helpers.
- Build a hash-verified custody view from original and V1 completed receipts.
  Restored V1 folds lack a copied attempts journal: use the original journal
  for those folds, never synthesize it or substitute the later partial one.
- Reuse strict canonical decoding, actual original public entry and final
  continuous-account assembly. HMA alone keeps its qualified delta provider
  and candidate binary. SC/HASH retain their original provider and binary.
- Verify original source/input/artifact pins, independent journal consistency,
  and dry restoration of 29/49/35 folds with zero optimizer/financial calls
  before launching. Add focused tests for the enlarged custody chains.
- Queue all three workers, at most three concurrent, one numeric thread each.
  Admit another worker only with its 900 MiB allowance plus 512 MiB host RAM
  available. Keep aggregate owned RSS at 3 GiB; do not stop unrelated services.
- Preserve the original absolute deadline, 2026-10-17 04:30:20 UTC. Do not reset
  the 48-hour study clock. Do not weaken guards or alter financial methodology.

## Storage And Cleanup

No build, environment creation or market download. Budget the new lane at
192 MiB retained and 32 MiB reproducible JIT scratch, beyond all prior retained
evidence. Require 5 GiB disk free after the remaining output forecast. Keep
source archives, original journals, logs, artifacts and scientific evidence.
Remove only reviewed inactive test/JIT scratch, with before/after verification
and a receipt; active worker scratch is never disposable.

## Exit And Status

Operational exit requires all three same-source dry proofs and observable live
attempts after the restored prefixes. This does not close M5-11.6: remaining
search, observer outcomes, continuous-account/replay, economics and final
qualification still apply. No M5-11.7, M5-12, CI, push or release activation.
Write launch/progress and cleanup receipts separately so this prospective
amendment can remain source-pinned.
