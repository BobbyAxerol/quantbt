# M5-11.1 Strict Custody Repair Experiment

Status: **COLD_PARITY_PASS / PERFORMANCE_ADVERSE / NOT_ACTIVATED**.
Authority: [registered closure entry](../../upgrade/implement.md#mode5-m5-11-goal-closure)
and [guide resource and measured-work policy](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#73-resource-plan-và-tốc-độ-không-làm-hỏng-methodology).

## Observed Fault And Repair

The earlier faster epoch16 prototype missed per-path ancestor-read authorization.
One authorization traversal per epoch is not equivalent to the original guard's
readable descriptor traversal on every file stamp. Its failure and timing remain
historical, rejected evidence; they are not advertised as usable acceleration.

A new isolated source repeats each original ancestor authorization before each
fresh atomic leaf open. Original entry/exit byte hashes, device/inode/size/time/
mode checks, expected pins, worker identity, fault latch, nondependency hashing
and one-second ctime-age rule stay unchanged. No live guard was edited/switched.

Three exact real permission-revocation cases reproduce the rejected prototype's
FAIL. Repair qualification passes **103 tests, zero failures/errors/skips**;
34 matched permission outcomes per arm agree in type, errno, args, filename,
fault state and FD count. Original fixture bodies are reused; new checks require
ancestor authorization on every path stamp, rather than preserving the rejected
once-per-epoch directory-count assumption. FD count is four before/after.

These are bounded cold Linux x86_64 fixtures, not proof of all filesystem races,
financial equivalence, general platform support or a qualified worker switch.
Only the isolated fixture thread's capabilities/modes are changed and restored
for the real read-authorization tests. No research worker is touched.

## Registered Custody-Only Timing

After parity PASS, one alternating ten-verify sample uses the exact retained
1,635-dependency/130-nondependency roster. No retiming or financial work occurs.

| Measured Seconds | Original Guard | Repair |
| --- | ---: | ---: |
| Entry | 2.243 | 1.611 |
| Ten verifies | 4.746 | 6.990 |
| Verify median | 0.444 | 0.648 |
| Exit | 1.571 | 1.514 |
| Entry + own verifies + exit | 8.560 | 10.115 |

Verify total is approximately **47.3% slower**; full measured work approximately
**18.2% slower**. The sample runs during live HASH contention; it is neither a
backtest benchmark nor a language comparison. The repair is therefore retained
as a correctness experiment, **not activated as a performance improvement**.

## Evidence And Cleanup

Registered caps: ten minutes, one numeric thread, 16 MiB scratch/64 MiB retained,
512 MiB RSS and 5 GiB reserve. Actual wall **131.917 s**, peak RSS **32.297 MiB**.
All 733 frozen source/control pins remain unchanged. Cleanup PASS removes only
the exact new inactive fixture scratch; observed free-space gain is 4,096 bytes,
not cache or environment reclamation. Failed evidence, live HASH custody and
original artifacts/data/source/caches remain protected.

Result SHA256:
`201a55180c694e1d898b186c40b73fd1973dff95badb71a3aaecfcf5844bab89`.
Cleanup SHA256:
`ef6a340702da9705346005ad8615edc76f22cc5eebae07505897df4c7ab6054d`.
Repair source SHA256:
`2edef69266399103375c493f80c6047a0b305a5f128ef44b029cc7775ea0eb5b`.

Continue using the original guard. Future source/worker entry/exit/custody
integration is a separate gate, not permission granted by these fixtures.
Original 128-effective-config panels and subsequent sampler/formal/forward
requirements remain; no study, native build, queue activation or release occurs.
