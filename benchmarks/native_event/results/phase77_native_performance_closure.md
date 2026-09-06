# Phase 77 Rust Kernel And Result-Adapter Performance Closure

This artifact measures matching 1-hour, single-symbol intrabar compact/standard
results before and after prepared ownership. It keeps Numba as a path-bearing
rollback comparator. The direct-target row is measured with the same one-symbol
close-target fixture and is reported separately.

| Route | Median | P95 | Throughput |
|---|---:|---:|---:|
| Numba intrabar standard/path | 9.446 ms | 10.041 ms | 2,117,248 bars/s |
| Numba intrabar one-shot public endpoint | 72.906 ms | 121.140 ms | 274,324 bars/s |
| Numba intrabar prepared public runner | 13.884 ms | 15.557 ms | 1,440,470 bars/s |
| Rust intrabar one-shot adapter | 17.237 ms | 18.414 ms | 1,160,325 bars/s |
| Rust intrabar prepared adapter | 6.211 ms | 6.936 ms | 3,220,255 bars/s |
| Rust intrabar one-shot public endpoint | 72.241 ms | 74.515 ms | 276,853 bars/s |
| Rust intrabar prepared public runner | 10.233 ms | 11.016 ms | 1,954,380 bars/s |

- Prepared adapter improvement over one-shot adapter: `2.78x`.
- Prepared runner improvement over one-shot endpoint: `7.06x`.
- Rust prepared runner / matching Numba prepared runner: `1.36x`.
- Exact terminal/path/fill parity: `True`; public parity: `True`.
- Prepared request cache policy: `ephemeral_validated`. Dynamic intent validation remains enabled.
- RSS start / prepared market / after warm: `158.13` / `160.26` / `243.89` MiB.
- Prepared-runner RSS change over `96` additional runs: `6.824` MiB; final-half change: `-0.305` MiB. This is a same-process retention probe, not a cold-process peak claim.

## Direct Target

- Rust prepared score: `11,496,885` bars/s.
- Numba warmed kernel: `33,790,331` bars/s.
- Rust public compact: `885,405` bars/s; Numba public compact: `344,916` bars/s.
- Exact accounting parity: `True`; no order arena: `True`.
- Target RSS is governed by the standalone Phase 66 artifact; this embedded target run shares the intrabar process and does not claim an independent process baseline.

The prepared intrabar route is an opt-in `prepare_intrabar(...).run(intent)`
service/WFO surface. One-shot endpoints still validate and content-address the full
market/request input. No automatic backend promotion is changed by this evidence.
