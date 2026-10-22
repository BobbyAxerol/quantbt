# M5-11.6.1 Admission Cleanup

2026-10-16 UTC, after the eight fixed HMA controls, cold readback and 104 passing
calendar/selector/admission/readback tests. No research worker remains from
these controls; no optimizer, new financial study or native build was launched.
This is cleanup certification, not a quarterly economics or phase-completion PASS.

## Reviewed Removal

The registered budget is 512 MiB incremental retained output, 64 MiB scratch,
at most four workers / 3 GiB owned RSS, 512 MiB available host RAM and 5 GiB
free disk beyond remaining forecast. Tooling/native artifacts were reused.
The host process namespace, process CWD/exe, FDs and mappings were checked
before exact deletion, not inferred from sandbox-only `ps`.

Removed exact inactive roots:

- `.maturin/mode5-m5116-quarterly/attempt-01`
- `.maturin/mode5-m5116-quarterly/attempt-02`
- `/tmp/quantbt-m51161-contract-tests`

The two agent XML receipts were copied to the retained private cleanup records
and their byte counts/SHA-256 verified before removal. The registered
`attempt-03/tests`, `attempt-03/final-tests` and
`/tmp/quantbt-m51161-admission-tests` roots were already absent; they are not
counted as deleted. Current `attempt-03/numba` is retained for future work.

| Observation | Value |
|---|---:|
| Host processes reviewed per removed root | 84 |
| Roots removed | 3 |
| Ordinary files removed | 17 |
| Apparent file bytes removed | 301,363 |
| Protected files verified unchanged | 3,022 |
| Free bytes immediately before removal | 6,305,558,528 |
| Free bytes immediately after removal | 6,305,955,840 |
| Observed free-space increase | 397,312 bytes / 0.38 MiB |
| Free inodes after removal | 5,525,375 |

The observed change includes allocation/metadata and concurrent host activity;
it is not equivalent to apparent file bytes or GiB of reclaimed space. Existing
large environments, release/qualified native artifacts and offline dependencies
were reviewed as retained inputs, not treated as disposable because of size.
No unrelated service, notebook, language server or collector was stopped.
No user source, market, alpha, scientific evidence or package artifact was removed.

## Custody And Limitations

Private root:
`upgrade/private/mode5_upgrade_v1/m5-11-6-1/attempt-03/`.
`cleanup-admission-v2/before.json` records the exact inventory/hashes;
`cleanup-admission-v2/result.json` reports
`PASS_EXACT_INACTIVE_PILOT_SCRATCH_CLEANUP`.
The initial cleanup loader attempt remains
`cleanup-admission-v1/failure.json`: sibling import failure **before any deletion**.
Its XML copies remain retained. The corrected attempt does not relabel that
failure as PASS. Scientific financial controls and the 104-test final XML remain.

No cleaned consumer needs reinstallation: no environment was deleted. Old JIT
scratch is reproducible; the current cache remains. A future variant study still
requires owner-reviewed semantics and fresh actual resource admission; this
receipt grants no launch, release or economic permission.
