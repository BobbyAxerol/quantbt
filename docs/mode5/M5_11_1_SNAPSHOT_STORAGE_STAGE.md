# M5-11.1 Snapshot Storage Staging

Status: **GAP_REPRODUCED / STAGED_FIXTURES_PASS / SOURCE_UNPATCHED**.
This is reporting/cache correctness work required before the continuous public
measurement provider. It does not change engine accounting, formulas or studies.

## Actual Counterexample

The controlled NumPy 2.2.6 runtime reproduces writable ancestry after pickle
protocols 0..4 for a 144-observation account. Although the final owner is bytes,
the existing helper shares writable ndarray ancestors. Enabling write access and
changing the final equity mark leaves the saved identity unchanged: cache reuse
returns +10%, while direct account reduction returns -20%.

The independently run roster contains 80 cases per arm: account, nested returns,
execution streams and episode buffers; copy/deepcopy and pickle protocols 0..5;
three- and 144-observation paths; readonly sharing, header isolation, writable
owners and explicit changed-observation cache reconciliation. The original arm
has ten failing roundtrips and five stale-cache clones, all on the 144-point
fixture. The three-point fixture and protocol 5 do not reproduce this gap under
this runtime. This is not evidence that every pickle or snapshot is defective.

## Staged Repair

An isolated helper shares bytes-backed storage only when every ndarray ancestor
is readonly; otherwise it creates fresh immutable storage. All 80 staged cases
pass, with identical values, shapes, dtypes, content identities and reduction
contracts. No shared source was changed while the exact native workers are live.
These synthetic fixtures do not certify a deployed source patch, the complete
reporting regression corpus or an installed-wheel consumer.

Both arm receipts and cleanup were sealed successfully in 1.122 seconds; peak
RSS was 47.51 MiB. The wrapper then exited 1 because its terminal print incorrectly
indexed a file-pin object. That command failure is retained separately, not
relabeled green. Independent review verified all 16 source/dependency pins and
the sealed measurements; no fixture rerun, financial call or source activation.

Original preflight, three-point and length-mismatch failures remain retained.
The latter was a fixture error, not an account-engine failure. The fresh revision
preserves array lengths and directly tests write-enable before cache mutation.

| Evidence | SHA256 |
| --- | --- |
| Registration, revision03 | bdfa9c279ae19d40d460524ab3455240a6bb25d9a193d0692402f93c04c5462a |
| Original arm | dbb3e75a650b9c115bbf9e85a094dca89813ade3bd5ed77df452e8483a8be632 |
| Staged arm | 04285a9a4373fe6ffa7f6190b460fcc97b3a453b839d4d8c2bf2b8e41e7241eb |
| Measurement receipt | a0df3e19d7ed94f9a01ad7d2938dfb6e590452f43f5ee8f5222c0bdfe76be184 |
| Cleanup | 90c707d2cd723e26937f5515835f458f16c1b92ca2110d13f6aac592364eb4d1 |

## Custody And Next Gate

The private snapshot-storage11 lane remains ignored. Registered bounds were one
numeric thread, ten minutes, 16 MiB scratch, 32 MiB combined retained and a 5-GiB
reserve. Cleanup PASS recorded 160,069 retained bytes before its receipt, zero
scratch and no deletion. All failures, exact fixtures and receipts are preserved.

After active worker closure, apply the narrow shared repair under a new source
witness and qualify reporting/cache serialization regressions. Only then can
the continuous public provider claim that shared snapshot gate closed. This
staged test does not complete M5-11.1, authorize a recipe or release a package.
