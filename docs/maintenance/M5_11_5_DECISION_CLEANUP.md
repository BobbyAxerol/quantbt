# M5-11.5 Decision Qualification Cleanup

Date: October 14, 2026 (Asia/Saigon).
Status: **PASS_EXACT_INACTIVE_CLOSURE_SCRATCH_CLEANUP**.

Scope: [C01--C08](../../upgrade/implement.md#mode5-m5-11-5),
[actual decision qualification](../mode5/M5_11_5_DECISION_QUALIFICATION_REPORT.md)
and the [cleanup runbook](../BUILD_TEST_CLEANUP.md). This is an operational
receipt, not an economic, installed-package, remote or public certificate.

## Reviewed Inventory

After every owned worker exited, remove only these ignored inactive roots:

- `.maturin/mode5-m5115/attempt-01/closure-tests`
- `.maturin/mode5-m5115/attempt-01/qualification01`
- `.maturin/mode5-m5115/attempt-01/studies01`

The review rejects symlinked, overlapping or replaced roots. Host process
inspection checks cwd, executable, file descriptors, maps and command lines;
170 PIDs were examined with no active reference. Protected hashes and Git
state are verified before and after deletion. There is no service stop, global
cache prune, source/evidence removal or environment deletion.

## Observed Results

| Receipt | Protected Files | Observed Available-Space Change |
| --- | ---: | ---: |
| `cleanup-tests01.json` | 1,231 | +21,692,416 bytes / 20.69 MiB |
| `cleanup-source03.json` | 4,202 | +230,150,144 bytes / 219.49 MiB |
| `cleanup-final01.json` | 4,402 | +5,431,296 bytes / 5.18 MiB |

These are nonoverlapping observations at their respective cleanup times, not a
claim about net disk movement throughout the research. The final operation
has 5,059,546 logical scratch bytes; filesystem-available bytes move from
6,846,660,608 to **6,852,091,904**, with 5,516,874 free inodes. Available disk
remains above the mandatory 5-GiB reserve.

The interrupted broad test attempt exceeded its first 64-MiB fixture estimate.
Its resource outcome stays **FAIL_RETAINED**. Subsequent fresh shards register a
prospective 256-MiB per-file fixture cap and clean each reaped fixture before
the next worker. Increasing a prospective operational cap does not turn the
earlier failure into PASS. XML, command logs and failure receipts remain.

## Retained

All full-scope diagnostic/account arrays, 768 formal proposals, sealed plans,
selected replay/direct controls, historical/current mutation evidence, source
and artifact pins, private alpha/data, original failures and the exact native
artifact are retained. Current regression/project environments and offline
dependencies remain usable. The private phase evidence is approximately
864 MiB within its 1-GiB incremental ceiling; it is not disposable build cache.

Exact private receipt location:
`upgrade/private/mode5_upgrade_v1/m5-11-5/attempt-01/cleanup-final01.json`.
The terminal `phase-exit01.json` links cleanup, source/tests, measured results
and scoped claims without another financial search. No wheel/native rebuild,
CI, push, merge, release or publication occurs in this cleanup.
