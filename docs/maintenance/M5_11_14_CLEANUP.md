# M5-11.14 Cleanup And Resource Receipt

Status: PASS for the exact registered inactive scratch cleanup, not an
installed artifact or parent research certificate. See the
[implementation report](../diagnostics/M5_11_14_IMPLEMENTATION_REPORT.md).

## Admission And Ownership

The private `m5-11-14/attempt-01/registration.json` records one test worker,
one numeric thread,512MiB owned RSS,64MiB compact additional retention,
64MiB allocated scratch, at least512MiB available RAM and5GiB disk reserve
beyond the128MiB incremental forecast. Existing `.venv` and native tooling are
reused: no build, install, duplicate environment or dependency download.

Only this exact ignored phase-owned root is removed:

```text
upgrade/private/mode5_upgrade_v1/m5-11-14/attempt-01/scratch
```

All registered pytest, financial and readback sessions are terminal before
cleanup. Review agents are closed. Sandbox process visibility is not proof of
host-wide inactivity; no unrelated service/notebook/process is controlled.
The cleanup tool rejects a symlinked/wrong root and checks Git ignore status.

## Observed Results

| Quantity | Actual value |
|---|---:|
| Allocated scratch removed | 53,092,352 bytes / 50.63 MiB |
| Filesystem available before | 6,261,805,056 bytes |
| Filesystem available after | 6,314,897,408 bytes |
| Immediate observed available-space change | +53,092,352 bytes |
| Protected files checked before/after | 110 |
| Final source-suite process peak RSS | 273,084 KiB / 266.68 MiB |
| Final actual synthetic smoke peak RSS | 313,452 KiB / 306.11 MiB |
| Cold benchmark whole-process peak RSS | 225,284 KiB / 220.00 MiB |

These process peaks are separate runs, not concurrent RAM sums. Filesystem
availability is an observation at cleanup, not a promise of future capacity.
Current retained evidence remains below its64MiB allowance after scratch removal.

The private `cleanup.json` retains the exact protected list/hashes. It includes
all phase evidence/logs/packs/journals, eight original source metadata files,
three authoritative guides, the five registered original financial owner files
and private alpha inputs. All110file checks agree before and after removal.
Source/financial owners also have empty diff against the phase baseline.

## Preserved

- Every passing, failing, interrupted/setup and synthetic qualification receipt.
- Original seven-alpha evidence, market/alpha sources and source snapshots.
- Private run packs, journals, readbacks, reports and registered preferences.
- Current environment/native artifacts, offline dependencies and Git history.
- Unrelated owner plan edit and untracked owner guide.

The failed first synthetic control remains failed; scratch removal does not
reclassify its result. Cumulative work remains14proposal slots/23financial
invocations including failures, not merely successful work. There is no broad
cache purge, environment/artifact/evidence deletion, worker restart, CI or release.
