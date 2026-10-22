# M5-12 Local Cleanup And Resource Disposition

Date: 2026-10-22 UTC. Scope: owner-approved local package qualification only.
All registered regression, build and installed-consumer owners are terminal.
No unrelated service, notebook, primary environment, global cache or scientific
account evidence is removed. The owner explicitly accepts all four reconciled
operational exceptions, preserving failed receipts and waiving no correctness,
artifact or privacy gate. This does not turn original gates into PASS.

## Retained Inputs And Outputs

Preserved: owner changes, guide and private alpha bytes, original scientific
and failed receipts, logs/JUnit, exact wheel/sdist/native artifacts, source
staging, primary environment and offline dependency cache. Artifact identity
and protected original inputs are independently rechecked. Consumers retired
below require fresh exact-artifact installation before any rerun.

| Terminal Cleanup | Actual Available-Space Increase | Protected Files / Scope |
| --- | ---: | --- |
| Before V6 build | 876,744,704 bytes | 5,233 pins; terminal V5 pair and eight reviewed debug test binaries |
| V6 build scratch | 11,091,968 bytes | 5,704 pins; completed build environment and stage-build |
| V6 wheel consumer | 586,477,568 bytes | 5,948 pins; completed pair consumer |
| Archived external preflight scratch | 18,309,120 bytes | All 675 regular file payloads retained in a verified 4,878,834-byte archive; links recorded, not followed |
| Final sdist and owned JIT/plot caches | 619,225,088 bytes | 5,596 pins; completed sdist consumer plus exact phase scratch/numba and scratch/mpl |

The final cleanup records 5,769,383,936 available bytes before and
6,388,609,024 after, with 5,509,664 available inodes. These are immediate
filesystem observations, not sums of apparent directory sizes or a run-wide
disk peak. Other intermediate cleanup receipts remain in the private lane.

Exact terminal receipts are under
`upgrade/private/mode5_upgrade_v1/m5-12/attempt-01/`:
`cleanup-v6-build-admission.json`, `cleanup-v6-built-core.json`,
`cleanup-v6-pair-terminal.json`, `cleanup-preflight-workspaces.json` and
`cleanup-v6-terminal.json`. The final handoff binds the terminal receipt hash.
Host-reviewed cleanups require a proven init/systemd host PID view and inspect
process executable/cwd/fds/maps before exact inactive-path deletion. No whole
target/.maturin purge, Docker prune or dependency-cache deletion is used.

## Forecast And Exceptions

The original serial forecast is 896 MiB incremental plus 5 GiB reserve,
128 MiB scratch and 96 MiB retained evidence. The separately approved narrow
native build uses one offline build job and a 192 MiB incremental sublane.
Observed native net build growth is 1,503,232 bytes, not a measured peak.
V6 admission passed at 6,411,968,512 free bytes against 6,308,233,216 required.

The following are owner-accepted retained exceptions, not retroactive successful budget gates:

1. Metadata fixture growth exceeded its component forecast. A later admission
   found 5,304,512,512 available bytes, 64,196,608 bytes below the 5 GiB reserve.
   That new test was not launched. Reviewed fixture cleanup recovered
   276,406,272 bytes and verified 17,870 pins; serial per-shard cleanup followed.
2. A cleanup hash capture overlapped an owned harness edit. The cleanup stopped;
   the before/after two-line native-fixture environment change was reconstructed
   and matched exactly, while 19,405 other pins remained unchanged. The original
   FAIL stays retained in `cleanup-final40-reconciliation.json`; later shards
   used fresh host-reviewed cleanup and guards.
3. An early cleanup's host_proc_review field did not establish a true host PID
   namespace. It is not evidence of global host inactivity. Subsequent cleanup
   explicitly requires the host namespace and exact process/path/hash checks.
4. Final retention inventory observes 664 regular files / 107,459,322 bytes
   (102.48 MiB), including the just-generated closeout, versus 100,663,296 bytes
   (96 MiB) planned. This readback excludes separate artifact lanes and public
   copies; filesystem allocated size is about 105 MiB. The exact later total
   can grow with final receipts. Immutable pin manifests, original JUnit and
   failures are not deleted or edited to claim compliance; no run-wide retained
   peak was measured. This is a small retained-evidence forecast overrun, not
   authorization to launch more compute or raise a future budget silently.

The [initial canonical phase report](../mode5/M5_12_REPORT.md) predates the final
retention inventory and records the first three exceptions. The
[current revision](../mode5/M5_12_REPORT_R3.md) records all four observations
and the explicit owner disposition, without rewriting earlier sealed reports
or rerunning finance. Earlier versions remain retained.
The current [summary](../mode5/M5_12_LOCAL_QUALIFICATION_SUMMARY.md) keeps the
phase TECHNICALLY_VALID within local scope after that explicit disposition.
Acceptance of an operational exception waives no correctness, artifact or privacy gate.
The private append-only `operational-owner-disposition.json` records both actual
owner answers; the current canonical report binds its hash. Final handoff and
remote/public approval remain separate.

## Protected Scope And Next Entry

The owner-only plan hunk remains unstaged; original alpha/guide/data and
historical scientific receipts remain unchanged. Only approved runtime
amendments are qualified by the current source guard. The source has changed
financially since original QMS, so no old unchanged-finance claim is restored.

No new installed execution, build, workflow or publication is launched here.
Any future run needs a new resource readback and actual consumer installation;
retained receipts do not mean cleaned environments are still installed.
