# M5-11.6 Initial Tranche Cleanup

## Scope

This receipt closes the bounded operational tranche's cleanup, not the
[whole research phase](../../upgrade/implement.md#mode5-m5-11-6). All four
128-attempt public studies exited successfully, their coordinator reaped them
and terminal cold readback passed before deletion. No further financial job
or long queue was launched.

The registered scratch inventory was confined to
`.maturin/mode5-m5116/attempt-01/tests/scheduled-numba`. Its six ordinary Numba
cache files total **93,839 apparent bytes / 106,496 allocated bytes**. The
directory also contained four cache subdirectories, three initially empty. Source,
evidence, markets, dependency caches and active/current environments were not
cleanup candidates.

## Safety And Result

- Explicit host preflight verified PID 1 is `systemd`, host/self PID namespaces
  agree and there is no nested `NSpid`. Host cwd, executable, FD and mapped-file
  checks found no live reference to the exact cache root.
- The first cleanup preflight rejected three unlisted empty cache directories
  and deleted nothing. Its failed receipt, source copy and six-file manifest
  remain preserved; it was not relabeled PASS.
- After reviewing those exact empty directories, the replacement verifies the
  completed cold proof's expected hashes and snapshots **1,743 protected files**.
  It deletes only the six individually pinned cache files, then removes empty
  directories with `rmdir`. Unexpected additions cannot be deleted recursively.
- All protected hashes match after cleanup, including successful/failed
  accounts, prior source copies, current source/helpers and native artifacts.
  The native extension and current tooling environment remain available.

The successful host review inspected 71 accessible live process maps; processes
that disappeared or lacked an executable were skipped without inventing an
inspection. All other access failures would stop cleanup. The private receipt
records free bytes **6,864,461,824 before / 6,864,588,800 after**, an observed
increase of **126,976 bytes (124 KiB)**. This filesystem observation is separate
from cache-file sizes and may include unrelated filesystem activity. Free space
remains above the 5-GiB reserve. No broad cache, Docker or service cleanup ran.

## Custody And Replay

Append-only evidence under the ignored Mode 5 private root:

- `m5-11-6/attempt-01/cleanup-preflight01`: retained no-delete preflight failure.
- `m5-11-6/attempt-01/cleanup-first-tranche01`: protected/cache manifests and
  successful cleanup receipt.
- `m5-11-6/attempt-01/cold-first-tranche-close01`: terminal account/measurement
  readback, source and original-prefix checks.

Replaying a cleaned JIT cache requires normal recompilation, not reinstalling
or rebuilding the retained native wheel. Financial evidence was not rerun for
report rendering or cleanup. Subsequent scoped documentation updates are not
misrepresented as byte-identical to the pre-cleanup documentation snapshot.

Read the [qualification report](../mode5/M5_11_6_MODE4_REPORT.md) for actual
runtime, trial dispositions and first-month outcomes. Mature meta qualification,
same-pool off/shadow checks, long continuous accounts and economics remain open.
