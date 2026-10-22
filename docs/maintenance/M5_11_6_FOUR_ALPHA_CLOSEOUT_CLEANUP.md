# M5-11.6 Four-Alpha Closeout Cleanup

Local cleanup on 2026-10-16 after
[HMA repair/account recovery and all 100 checkpoint controls](../mode5/M5_11_6_FOUR_ALPHA_CLOSEOUT.md).
The controller and terminal cold-reader processes exited before removal. This
receipt is not an economic promotion, installed-package or release certificate.

## Reviewed Removal

The prospective checkpoint budget was 64 MiB retained and 16 MiB disposable
scratch, one worker, 900-MiB worker allowance, 3-GiB aggregate owned RSS,
512-MiB host available RAM floor and 5-GiB free disk reserve. Existing tooling
and native artifacts were reused; no build or dependency download was required.
The earlier HMA observer lane had its own separate cleanup receipt.

Exact inactive roots removed:

- `/tmp/quantbt-hma-observer-v3-tests`
- `/tmp/quantbt-hma-observer-v3-tests-pass`
- `/tmp/quantbt-m5116-closeout-tests`
- `/tmp/quantbt-m5116-closeout-tests-v2`
- `/tmp/quantbt-m5116-closeout-tests-v3`
- `.maturin/mode5-m5116/four-alpha-closeout-v1/attempt-01`

The separately registered `/tmp/quantbt-m5116-checkpoint-tests` was already
absent; it is not counted as a deletion. Host PID namespace, process CWD/exe,
FDs and mappings were checked before removal. Exact file hashes/inodes and
internal fixture links were reviewed; links were unlinked, not followed.

| Observation | Value |
|---|---:|
| Host processes reviewed per existing root | 75 |
| Roots removed | 6 |
| Ordinary files removed | 324 |
| Apparent ordinary-file bytes | 747,832 |
| Protected files unchanged after cleanup | 11,884 |
| Free bytes before deletion | 6,811,398,144 |
| Free bytes after deletion | 6,814,134,272 |
| Observed free-space increase | 2,736,128 bytes / 2.61 MiB |

Observed filesystem change includes allocation/metadata and concurrent host
activity; it is not equated with apparent file size or claimed as GiB savings.
Free bytes remained above the 5-GiB reserve; free inodes were above 5.5 million.

## Preserved Evidence

All original/corrected financial paths, fills, ordered search journals,
failed/partial runs, source archives, model/history records, qualification/test
XML and logs, alpha/market inputs, exact native artifacts and current environments
remain. No unrelated service, notebook or collector was stopped. JIT scratch
can be regenerated; no consumer environment requires reinstallation here.

Private records:
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/four-alpha-closeout-v1/`
`cleanup-before.json.gz` and `cleanup.json`. The latter is
`PASS_EXACT_INACTIVE_FIXTURE_AND_JIT_CLEANUP`; the final scope receipt separately
binds source, financial replay, public summary and qualification. No CI, push,
merge, tag, publication or new experiment was performed.
