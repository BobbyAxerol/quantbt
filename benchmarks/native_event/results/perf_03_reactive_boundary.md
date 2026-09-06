# PERF-03 Reactive Boundary Benchmark

This is a development measurement from one local machine. It reports full public-facade time; it is not a universal backend promotion claim.

Process RSS for the complete same-process run: initial `152.58` MiB, post-run `168.64` MiB, peak `170.66` MiB. Per-row RSS delta is sampled only across that case's timed pair after its audit/warm-up run, so it is not a substitute for the complete-process figure.

| Workload | Binding | Median ms | Bars/s | Dynamic lookups | Projections | Getters | Writer calls | Rows | RSS delta MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| control no-op callback | dynamic | 24.378 | 82041.9 | 2002 | 2000 | 0 | 0 | 0 | 0.00 |
| control no-op callback | run_stable | 23.911 | 83643.6 | 0 | 2000 | 0 | 0 | 0 | 0.00 |
| B-02 many getters | dynamic | 37.472 | 53373.6 | 2002 | 2000 | 168000 | 0 | 0 | 0.00 |
| B-02 many getters | run_stable | 36.237 | 55192.2 | 0 | 2000 | 168000 | 0 | 0 | 0.00 |
| B-03 many commands/callback | dynamic | 27.168 | 73616.2 | 2002 | 2000 | 3999 | 16 | 16 | 0.00 |
| B-03 many commands/callback | run_stable | 26.002 | 76915.8 | 0 | 2000 | 3999 | 16 | 16 | 0.00 |
| B-04 Python-heavy decision | dynamic | 197.151 | 10144.5 | 2002 | 2000 | 2000 | 0 | 0 | 0.00 |
| B-04 Python-heavy decision | run_stable | 200.582 | 9971.0 | 0 | 2000 | 2000 | 0 | 0 | 0.00 |
| B-05 declared sparse wake | dynamic | 23.250 | 86020.3 | 4 | 2 | 2 | 0 | 0 | 0.00 |
| B-05 declared sparse wake | run_stable | 23.664 | 84518.1 | 0 | 2 | 2 | 0 | 0 | 0.00 |
| B-06 high-churn grid-like | dynamic | 32.624 | 61305.2 | 2002 | 2000 | 2000 | 250 | 250 | 0.00 |
| B-06 high-churn grid-like | run_stable | 32.334 | 61855.3 | 0 | 2000 | 2000 | 250 | 250 | 0.00 |

Dynamic binding is the compatibility default. `run_stable` is valid only when the strategy does not replace lifecycle callbacks while one run is active.
Business admission remains per command; callback exceptions discard only unsubmitted staged rows and poison the reusable session until reset.
