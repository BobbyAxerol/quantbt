# M5-11.6 Remaining Disk Forecast

Measured at **2026-10-15 22:30:24 Asia/Saigon** while all three workers were
running. This is an operational forecast, not a guarantee against unrelated
host writes. Original guard thresholds and scientific budgets are unchanged.

| Item | Measured/planned |
|---|---:|
| Filesystem free | 6.414 GiB |
| Free inodes | About 5.53 million |
| Original stopped queue retained | 59.83 MiB |
| Current HMA + peer output | 30.51 MiB |
| Current combined JIT scratch | 0.36 MiB |
| Conservative additional study output/scratch model | 196.50 MiB |
| Full remaining configured output/scratch allowance | 353.13 MiB |
| Required free: 5-GiB reserve + full remaining allowance | 5.345 GiB |
| Additional host-growth headroom beyond that requirement | 1.069 GiB |

## Model Components

The conservative model retains the original incomplete-prefix counts even if
the current fold has already advanced. It uses twice the maximum observed
completed-fold bundle, not a measured future percentile:

| Alpha | Remaining fold allowance | Observed maximum bytes/fold | Forecast bytes |
|---|---:|---:|---:|
| HMA | 36 | 390,598 | 28,123,056 |
| HASH | 15 | 427,154 | 12,814,620 |
| SC | 52 | 219,919 | 22,871,576 |

Total fold-bundle forecast is **60.85 MiB**. Add 16 MiB for trial/generation
logs, 48 MiB for the three pairs of final accounts/commands/reports, 8 MiB for
custody/cleanup records and up to 63.64 MiB additional JIT scratch. Independent
final replay compares in-memory buffers; it does not retain a second duplicate
financial dataset. Existing VWAP's final-account pair is 806,704 bytes; the
16-MiB-per-pending-alpha allowance is deliberately larger, not an assertion that
different alphas have identical output density.

The complete configured allowance, about **353 MiB remaining**, is more
conservative than the approximately **197 MiB** planning model. No extra build,
environment, package download or market snapshot is planned. Raw financial
evidence is not deleted to force the forecast to pass.

## Interpretation

The studies have enough disk for their registered remaining output with the
5-GiB reserve intact. Writing within their caps decreases free space and the
remaining reserved allowance together; the approximately 1.07-GiB extra margin
is mainly exposed to unregistered growth from collectors, service logs, manual
copies or another build. It is not safe to call that margin unlimited.

A **6-GiB free-space early-review level** is recommended, before the current
approximately 5.35-GiB joint admission/continuation threshold. This is a stated
review level, not a newly installed background alarm. Existing supervisors
already monitor free space, output caps and resource floors. No guard was
lowered or disabled, and no new unattended cleanup of unknown data was enabled.

Private source-bound receipt:
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/hma-recovery-cleanup-v1/disk-forecast.json`.
See [cleanup custody](M5_11_6_HMA_RESTART_CLEANUP.md) and
[parallel worker status](../mode5/M5_11_6_PARALLEL_RECOVERY_STATUS.md).
