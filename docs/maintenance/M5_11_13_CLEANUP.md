# M5-11.13 Cold Disposition Cleanup

This is an operational receipt for the
[approved no-new-finance scope](../../upgrade/implement.md#mode5-m5-11-13),
not new economic, installed-package or release qualification. See the
[research disposition](../mode5/M5_11_13_CHRONOLOGICAL_DISPOSITION_REPORT.md).

## Registered Inventory

Reused `.maturin/qms08/release-regression-v1`; no environment/install/native
build. One cold worker / one numeric thread, 512 MiB RSS, 30-minute wall /
20-minute CPU budget, 32 MiB retained output and **64 MiB allocated scratch**.
Required free reserve: 5 GiB beyond remaining output/scratch forecast and
512 MiB RAM. Free bytes and inodes were measured separately before admission.

Only removable owner:
`upgrade/local/mode5_upgrade_v1/m5-11-13/attempt-01/scratch/`.
It contains reproducible terminated pytest fixtures only. A process cwd/root/FD
check and Git-ignore check precede removal; the current output/evidence root,
source snapshots, logs, failures and all financial evidence are excluded.
The new registration corrects the earlier lane's small-file accounting problem
by checking allocated blocks, including directories, rather than logical sizes.

## Measured Cleanup

| Quantity | Actual Receipt |
|---|---:|
| Inactive scratch logical file bytes | 309 |
| Removed filesystem-allocated bytes per round | 135,168 |
| Removed across two measured rounds | 270,336 |
| Removed members including directories | 33 |
| Immediate free-space increase | 135,168 bytes |
| Free filesystem bytes immediately after final cleanup | 6,200,991,744 |
| Free inodes immediately after final cleanup | 5,513,778 |
| Protected files rechecked at final cleanup | 200 |
| Environments/services/other workers removed or stopped | 0 |

The final cold terminal output was about 0.41 MiB logical / 0.46 MiB allocated before
the subsequent compact coverage/documentation handoff. Final retained sizes and
document/source pins are recorded separately, not substituted for this measured
cleanup window. The 170-test process-group-plus-owner RSS observation was
245.75 MiB; no financial latency/speedup benchmark ran. The initial 155-test
receipt is retained separately, not counted as additional distinct coverage.

All original receipts and both reader-failure source copies remain. Cleanup
does not turn failed reads into PASS; repaired cold readbacks have separate
receipts. No global cache, Docker storage, shared native build tree, private
alpha/data, scientific path or M5-11.9 worker was touched.

The M5-11.12 scratch overrun was owner-disposition pending at this cleanup.
The [later explicit acceptance](M5_11_12_CLEANUP.md) closes that operational
disposition with evidence retained. Neither lane retroactively raises its cap
or claims that the previous operational resource gate passed.

Private receipts:
`upgrade/private/mode5_upgrade_v1/m5-11-13/attempt-01/registration-v3.json`,
`test-complete-v2.json`, `cleanup-v2.json`, `phase-exit-v2.json` and final handoff.
Original `registration.json`, failed audit receipts, test XML/log and pinned
input references are preserved. No financial work, optimizer or model was rerun.
