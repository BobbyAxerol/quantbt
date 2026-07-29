# Phase 34C Native Event Single-Pass Benchmark

- Rows: `600`
- Trials: `12`
- Replay-certified seconds: `1.431315`
- Single-pass seconds: `0.750957`
- Speedup: `1.906x`
- Replay-certified static replays: `12`
- Single-pass static replays: `0`
- Accounting parity: `True`
- Peak RSS MB: `333.770`

This benchmark isolates the Phase 34C mode switch: `single_pass` materializes accounting from the reactive session for minimal/score runs and skips the final static replay.
