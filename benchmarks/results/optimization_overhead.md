# Phase 32C Optimization Overhead Benchmark

Status: **pass**

| Measurement | Value |
|---|---:|
| Optimizer overhead | `0.017357s` |
| Optimizer overhead / trial | `0.000723s` |
| Normal signal replays | `0.165146s` |
| Prepared signal replays | `0.081492s` |
| Prepared signal speedup | `2.027x` |
| Intrabar first run | `0.017772s` |
| Intrabar warm run | `0.004809s` |
| Intrabar first/warm ratio | `3.695x` |

Parity checks:

- Signal final equity diff: `0.0`
- Intrabar final equity diff: `0.0`

This benchmark measures facade/optimizer overhead, not strategy quality.
