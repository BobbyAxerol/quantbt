# M5-11.6 Native Transaction Cleanup

## Disposition

The [native runtime report](../mode5/M5_11_6_NATIVE_TRANSACTION_CLOSURE.md) and
[phase plan](../../upgrade/implement.md#mode5-m5-11-6) record the bounded scope.
All 12 matched controls and their foreground coordinator exited; the test/build
processes were reaped before cleanup. No long study or optimizer was launched.

The preflight registered one offline incremental native build with up to 512 MiB
additional scratch, 128 MiB retained evidence, a 2-GiB process cap and a 5-GiB
disk reserve. One existing Python environment and Cargo release target were
reused, with one numeric/build thread. No environment was recreated.

The recorded release-target footprint grew from 229,951,272 to 231,494,547 bytes
(about 1.47 MiB). That is a steady before/after delta, not measured peak build
scratch. The current offline dependency/build cache remains available for reuse.

## Reviewed Removal

Exact ignored root: `.maturin/mode5-m5116/transaction-v1`.

A full host-namespace review inspected **72 processes**, including cwd,
executable, file descriptors and memory mappings. Only six known reproducible
Numba `.nbc`/`.nbi` files and the named empty cache directories were removed.
No active reference, symlink, unexpected file, source, environment or financial
evidence was deleted. No service was stopped and no global cache prune ran.

| Measurement | Bytes |
|---|---:|
| Apparent cache files removed | 93,963 |
| Allocated cache files removed | 106,496 |
| Available before deletion | 6,327,242,752 |
| Available after deletion | 6,327,201,792 |
| Observed available-space delta | **-40,960** |

The measured filesystem delta includes retained inventory writes and concurrent
host activity; it is **not a net disk-space saving claim**. Available space
remains about 5.89 GiB, above the 5-GiB reserve. Both bytes and inodes were
checked; final free inodes were 5,514,712.

An initial whitelist omitted three known empty cache directories. It refused
deletion before removing any file. Its source/failure record remains alongside
the reviewed passing cleanup; a failed preflight is not relabelled PASS.

## Preserved Custody

All **540 protected file hashes** matched before/after deletion, including failed
and successful evidence, original inputs, the current native candidate, source
copies and the original qualified native binary. Twelve source snapshots were
also copied and hash-compared. The candidate does not overwrite the installed
native artifact or alter a historical receipt.

The later cross-owner guard changes one of those 540 pinned source paths
intentionally. `owner-guard-amendment.json` records its before/after hashes,
539 unchanged protected hashes, retained new source and the passing 179-case
regression. It does not attribute that authorized edit to cleanup or rewrite
the source identity of the original matched controls. No new financial run or
registered JIT-cache recreation follows from that guard.

Private custody is `m5-11-6/attempt-01/transaction-v1/cleanup-v3`:
`inventory.json` and `result.json`. The complete transaction lane, including
source snapshots, candidate binary, 12 controls, failures, logs and guard
amendment, retains **18,376,195 bytes** at final readback (about 17.53 MiB),
well below 128 MiB. None is treated as disposable research evidence.

The original native SHA remains
`2959f5388c6a8e57bdef5a6dafe76da3624ef57dba379f7ca686e9bf202ad26b`.
The new local candidate SHA is
`f74b5669dd6da58a80d292ad39b3ca150092b4775b7d0000459b37da2778ffbc`.
Future replay regenerates the removed JIT cache within a new resource admission.
There is no installed-wheel, remote, long-WFO or economic release certificate.
