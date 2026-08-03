# Pre-48E Native Event Performance Pass

Contract: **2,000 bars**, one symbol, identical deterministic tape, fresh
process per route, seven measured warm runs. Runtime is reported in seconds;
RSS is MB. Commit `0121163` is the frozen pre-patch baseline and the current
working tree is the after result.

## Parity Gate

All eight groups passed Python/Rust fingerprint parity:

```text
common_low/high_churn     x score/audit       PASS
explicit_low/high_churn   x score/audit       PASS
numeric tolerance:        atol <= 1e-12
discrete lifecycle fields: exact
```

The fingerprint covers equity, positions, fees, funding, margin, fill rows,
and the core lifecycle counters (`fill_count`, `event_count`, rejection and
cancellation counts). Final equity and fill counts are equal for every group.

## Warm Runtime Before / After

| Workload | Route | Before s | After s | Change | Before bars/s | After bars/s | After RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|
| common low | Python score | 0.148483 | 0.087736 | -40.9% | 13,470 | 22,796 | 183.2 |
| common low | Rust score | 0.232064 | 0.188448 | -18.8% | 8,618 | 10,613 | 185.7 |
| common low | Python audit | 0.166945 | 0.087327 | -47.7% | 11,980 | 22,902 | 240.8 |
| common low | Rust audit | 0.250250 | 0.176075 | -29.6% | 7,992 | 11,359 | 243.9 |
| common high | Python score | 0.165390 | 0.086609 | -47.6% | 12,093 | 23,092 | 182.9 |
| common high | Rust score | 0.246971 | 0.188299 | -23.8% | 8,098 | 10,621 | 186.1 |
| common high | Python audit | 0.167247 | 0.119269 | -28.7% | 11,958 | 16,769 | 241.2 |
| common high | Rust audit | 0.254275 | 0.198521 | -21.9% | 7,866 | 10,074 | 243.1 |
| explicit low | Python score | 0.020644 | 0.018784 | -9.0% | 96,882 | 106,475 | 180.8 |
| explicit low | Rust score | 0.001032 | 0.000964 | -6.6% | 1,937,178 | 2,075,635 | 182.8 |
| explicit low | Python audit | 0.009188 | 0.007786 | -15.3% | 217,680 | 256,879 | 239.5 |
| explicit low | Rust audit | 0.002404 | 0.002434 | +1.2% | 832,012 | 821,591 | 182.9 |
| explicit high | Python score | 0.021454 | 0.023843 | +11.1% | 93,224 | 83,883 | 181.3 |
| explicit high | Rust score | 0.001358 | 0.001404 | +3.4% | 1,472,565 | 1,424,350 | 182.3 |
| explicit high | Python audit | 0.015307 | 0.012157 | -20.6% | 130,662 | 164,519 | 240.2 |
| explicit high | Rust audit | 0.002879 | 0.002879 | 0.0% | 694,585 | 694,620 | 182.7 |

The explicit high-churn score rows are within normal short-run variance and
are not treated as a speed claim. The reliable improvement is in the generic
callback path, where empty-bar retime/quantize work was removed. No domain
accounting was skipped.

## What Changed

- Cache quantity-constraint enablement once per Python reactive session.
- Skip retime, schedule and quantity preflight when a callback emits no
  commands.
- Preserve quantity preflight for enabled `PLACE`/`REPLACE` commands.
- Add execution counters to Python score/audit metadata.
- Use the existing prepared Rust full-tape runner with one PyO3 tape call per
  measured execution; no implicit Python fallback is used.

Reactive Grid remains a separate integration workload and is deliberately not
included in the README native-event throughput headline.

Artifacts:

- `baseline.json`: frozen pre-patch result.
- `after.json`: post-patch result and parity matrix.
- `baseline.md`: baseline table.
- `benchmark_pre48e.py`: reproducible process-isolated runner.
