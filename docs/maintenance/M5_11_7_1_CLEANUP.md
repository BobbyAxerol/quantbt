# M5-11.7.1 Reporting Cleanup

## Scope And Registration

Local shared pre-search reporting only. No financial study, optimizer, model
fit, wheel build, dependency installation, service stop or market download.
The current `.venv` and exact existing native artifacts were reused/preserved.
See the [implementation report](../diagnostics/M5_11_7_1_IMPLEMENTATION_REPORT.md).

The ignored private lane registered 64 MiB incremental retained output,
32 MiB scratch, 512 MiB per-report-process RSS and at least 5 GiB free space
beyond forecast. Initial free bytes were 5,768,458,240 with 5,474,570 free inodes.
These are separate quantities; neither is a claimed saving.

The sole deletion root was:

`upgrade/private/mode5_upgrade_v1/m5-11-7-1/attempt-01/scratch`

Its resolved root was not a symlink and was Git-ignored. Host process and
complete readable `/proc` cwd/FD checks found no owner of the root at either
deletion. Only pytest `current` links resolving inside the exact scratch root
were permitted; no external links were followed. No host process was stopped.

## Measured Removals

| Cleanup | Apparent File Bytes | Allocated Bytes | Immediate Free-Byte Increase |
|---|---:|---:|---:|
| Completed main/regression fixtures | 990,735 | 4,571,136 | 4,571,136 |
| Final timing-null regression fixtures | 114,314 | 786,432 | 786,432 |
| Total | 1,105,049 | 5,357,568 | 5,357,568 |

The observed immediate recovery is **5.11 MiB**, not a claim that the whole
phase reduced total filesystem usage. New retained reports/receipts also consume
space. At the second cleanup there were 5,748,674,560 free bytes and 5,474,066
free inodes; the safety reserve remained satisfied.

The second receipt verifies 185 protected inputs and 394 retained files before
and after deletion, representing 8,165,714 retained bytes at that instant.
Subsequent small terminal/docs receipts remain inside the 64 MiB budget.
Current and historical export revisions are evidence, not disposable fixtures.
No multi-gigabyte trace/snapshot or duplicate market tape was created.

## Preservation And Failures

Original alpha/data, frozen Ridge inputs, existing wheel/native artifacts,
all original financial accounts, selection/pool/label evidence, negative results,
test XMLs, failed and successful readers, and current tooling remain retained.
Source, evidence and artifact pins were verified around deletion. Both current
report-source locks and the frozen 42-source/5-receipt Ridge lock pass separately.

Conservative initial cleanup refused pytest symlinks before deleting anything;
the later review admitted only the verified internal links. One final test lane
started after the scratch parent had been cleaned and produced fixture-setup
errors; its XML remains failed. Recreating only that registered parent produced
the separate 211-pass final receipt. Early reader/prerequisite-order failures
are also recorded, never relabelled successful or used as scientific evidence.

Private machine receipts: `cleanup.json`, `cleanup-final.json`,
`operational-failures.json` and the terminal qualification under the ignored
`upgrade/private/mode5_upgrade_v1/m5-11-7-1/attempt-01/` lane. Rerunning tests
requires recreating only the exact fixture parent, not reinstalling the retained
environment. No M5-11.7.2, M5-11.7.3, M5-12, CI, push or release ran.
