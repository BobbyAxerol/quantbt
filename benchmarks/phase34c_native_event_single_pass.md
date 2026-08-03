# Phase 34C Native Event Single-Pass Benchmark

- Rows: `1000`
- Trials: `20`
- Replay-certified seconds: `2.352882`
- Single-pass seconds: `1.977425`
- Speedup: `1.190x`
- Replay-certified static replays: `20`
- Single-pass static replays: `0`
- Accounting parity: `True`
- Peak RSS MB: `347.438`

This benchmark isolates the Phase 34C mode switch: `single_pass` materializes accounting from the reactive session for minimal/score runs and skips the final static replay.
