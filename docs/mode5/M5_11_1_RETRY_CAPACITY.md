# M5-11.1 Retry-Aware Capacity Admission

Status: **PASS_BOUNDED_RETRY_ADMISSION / THREE-ALPHA_CAPACITY_PENDING**.
Authority: [ordered closure](../../upgrade/implement.md#mode5-m5-11-goal-closure)
and [guide work-count/identity rules](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

## Why A Versioned Review

The historical native03 resource policy requires three literal attempt names.
Two attempts were censored and cannot later become COMPLETE. Accepting another
name without request/source/receipt checks would weaken custody; renaming old
cells or overwriting the failed capacity review would falsify history.

A new cold contract binds the preregistered native04 HMA1/HASH2/VWAP2 raw requests
to independently qualified completed attempts. A retry must match the entire
original typed raw request, not merely alpha/index or a favorable result. The
financial gate, effective candidate, account scope, inputs, original six-hour
caps and 4,096-pass compiler contract are not changed.

## Actual Admission

Twelve focused fixtures PASS for complete/duplicate/missing origin rosters,
changed parameters/identities/horizons/types, request JSON order, unsafe IDs,
censored/live/failed children and missing/error/unreaped supervisor custody.
Existing exact Candidate/checkpoint reuse verifies original source and outputs;
closed compiler proofs and returned-work bills agree with original receipts.
Every file in each whole cell is inventoried, including logs and metadata.

The actual review admits **HMA1 and VWAP2**, each against its own preregistered
request and original COMPLETE proof. HASH is explicitly missing; its running
attempt is not a closed proof. The output remains
`PENDING_MISSING_CLOSED_SLOTS`. Successful admission of two slots is not a
three-alpha resource PASS, financial execution, panel completion or launch.

The schema is `mode5.retry-capacity-review.v2`; the old native03 FAIL remains
unchanged. It is **not compatible with the historical queue consumer**. Explicit
versioned consumer/policy integration plus all three actual closed proofs and
conservative disk admission are required before any future 16-GiB activation.
No queue, policy, guard or live source was switched by this run.

## Evidence And Resources

The bounded cold run takes **8.762 s**, peak RSS **37.621 MiB**, with zero account
calls, owner unpickles, compiler-object signatures or activation. File byte hashes
are custody checks, not financial-object hashing. Registered caps are five minutes,
16 MiB scratch/32 MiB retained/512 MiB RSS and 5 GiB reserve.

Cleanup PASS_NO_SCRATCH_CREATED retains original checkpoints, failed attempts,
source snapshots, private evidence and active caches. No files were deleted.
The exact source/fixture/registration and whole-cell inventories remain in the
ignored research lane, not in GitHub or package artifacts.

Result SHA256:
`a3d0aa5e27b57f1521c53705e6f314573bf539e043617607c1a495c7c1337830`.
Review SHA256:
`f03c64cde8a6c79f20aa6e9a5d94fe8934d937264233ff34a8f5ca479a72c2ad`.
Cleanup SHA256:
`232f9e7e336e23fef9ea4b745e18eb70319997f79389f85e692273685420cc75`.

M5-11.1 remains IN_PROGRESS. The complete original 128-point native panels,
required probes/dossiers, economic sampler-only experiments, separate 256-query
studies and prefix-rebuilt forward remain required. No remote qualification,
publication or economic superiority follows from this resource-only proof.

## Explicit Pending Consumer

A separate private v2 consumer now reuses the qualified original budget loader,
fresh-driver ownership, fault latch, restore and conservative space checks.
The v1 budget-envelope format is unchanged; v2 capacity admission is explicit.
Complete reviews are recomputed from their original registrations and proofs;
the entire sealed payload must agree. The baseline/native gate are additionally
anchored to the preregistered native04 origin, not supplied by a later caller.

Revision02 passes seven focused cold cases: pending, forged PASS, forged empty
missing roster, legacy review schema, byte-identical unapproved baseline/gate
copies, and unchanged four-GiB synthetic factory/restore. All six rejection
cases stop before factory calls or resource mutation. The synthetic baseline
case creates one ModuleType fixture, not a financial driver/account. Earlier
consumer output/source remains retained; the hardening is a fresh revision.

Actual consumer wall **9.609 s**, peak RSS **36.926 MiB**. Cleanup PASS preserves
source/receipts and copied fixtures, deleting only the registered inactive
fixture scratch. No active policy/launcher or financial source is changed.
Result SHA256:
`3c5306da9e9ea5e6308ab12daef372140ea104453c6c36c52709299aa37159c6`.
Cleanup SHA256:
`d4c5b280cc2cd0234e3776badce9642fd75d1c42a947a1cc7809f61c76ac4692`.

This closes pending-consumer fail-closed behavior, **not** actual three-slot
qualification. HASH's closed checkpoint and explicit future launcher/policy
source selection still gate activation. The historical native03 review and
old queue remain unchanged; no runtime quietly substitutes this implementation.
