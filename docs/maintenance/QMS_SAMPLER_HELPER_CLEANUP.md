# Sampler Helper Cleanup Receipt

Date: 2026-10-07. Scope: approved QMS-SH01 local helper tests and artifact proof.
Machine receipt: `.maturin/qms08/sampler-helper-v1/cleanup.json`.
Report: [implementation and diagnostic](../meta_selection/QMS_SAMPLER_HELPER_REPORT.md).

## Reviewed Inventory

Host `ps -eo pid,ppid,comm,args` confirmed no helper build/consumer process
remained. Unrelated notebook kernels, collectors, services and main tooling were
left running. Resolved paths were non-symlinked, Git-ignored and inside this
phase's allowlist; each environment had `pyvenv.cfg`.

Only these seven inactive paths were removed:

| Lane Under `.maturin/qms08/sampler-helper-v1/` | Removed Scratch |
|---|---|
| `package-v1/cp312` | `build-env`, `pair`, `stage/build` |
| `package-v2/cp312` | `build-env`, `pair`, `sdist`, `stage/build` |

The failed first consumer origin-check log stays failed and retained. Cleanup
does not retroactively turn that lane into a passing proof. The second lane has
its own passing wheel/sdist consumers. Cleaned environments require fresh
installation in a new evidence lane for any rerun.

## Preservation And Measurement

- **740 protected files** retain exact before/after SHA256: all successful and
  failed logs/XML, registrations, summary, private/public raw results and
  arrays, staged source and exact core/native wheel/sdist artifacts.
- **261 canonical Python/typing members** and all sealed Rust/native sources
  remain unchanged. The original alpha/data and current tooling environment
  were not modified or removed. Offline dependency cache remains available.
- Actual filesystem free-space improvement: **1,779,650,560 bytes**, or
  **1,697.207 MiB**. Post-cleanup available space: **25,787,768,832 bytes**;
  free inodes: **5,592,515**. This is measured free space, not a summed `du` size.
- No broad cache cleanup, Rust rebuild, historical-lane deletion or service
  termination was performed.

## Budget Correction

The initial scratch estimate was 1 GiB plus 5 GiB safety headroom. UV reported
that hardlinking was unavailable and copied dependencies, causing about
1.70 GiB observed filesystem growth across the failed and successful lanes.
Original registrations/logs are unchanged; this variance is not concealed.
Future helper artifact preflight budgets **2 GiB plus 5 GiB headroom**. Disk
headroom remained sufficient throughout, and completed copy-mode consumers
were reclaimed before closing the phase.

This is an operational cleanup receipt, not remote or public-release
qualification. No push, workflow, merge, tag or publication is authorized.
