# M5-11.10 Cold Research Cleanup

**Date:** 2026-10-20, Asia/Saigon.
**Scope:** source/metadata contract tests and cold archive qualification only.
See the [phase report](../mode5/M5_11_10_ARCHIVE_BASELINE_REPORT.md).

## Registration

- Use one existing qualified environment; no build, install, native replacement
  or service control. Cold RSS cap512 MiB; retained/scratch caps64 MiB each;
  minimum available RAM512 MiB and free-disk reserve5 GiB plus forecast.
- Initial filesystem review has approximately6.5 GiB available and more than
  5.5 million available inodes. This is capacity, not cleanup savings.
- Only disposable target:
  `upgrade/private/mode5_upgrade_v1/m5-11-10/attempt-03/scratch`.
- Preserve all original metadata/accounts, dictionaries, alpha source, exact
  native artifacts, current environment, old failed/preliminary attempts,
  source-revision copies, JUnit and registration/qualification receipts.

## Observed Cleanup

The completed pytest command has exited. A host process/cwd/fd/maps review
examines172 processes, finds no references to the registered fixture and no
permission-denied processes. Only that exact owned inactive root is removed.
No source, scientific evidence, account path, cache tree or environment is
deleted. Protection checks preserve **923 inputs** across cleanup.

- Logical fixture regular-file payload: **166 bytes**.
- Observed filesystem free-byte increase: **131,072 bytes**.
- Directory/filesystem allocation and concurrent writes are distinct from
  logical payload; no larger host-space change is claimed as causal savings.
- Current final source-check peak RSS: **294.10 MiB**, below512 MiB.
- Approximately6 MiB retained in the final current lane, below64 MiB.

Private append-only receipts are `cleanup-before.json`, `cleanup-after.json`
and `phase-exit.json` in the current `attempt-03` lane. Earlier attempts remain
retained with their original statuses and exact prior helper-source copies.
The105-test source gate is local research qualification, not package,
financial performance, remote CI or release certification.
