# Phase 34B Native Event Prepared Score Benchmark

- Rows: `1000`
- Trials: `20`
- Public audit seconds: `2.869046`
- Prepared score seconds: `1.846037`
- Speedup: `1.554x`
- Peak RSS MB: `335.645`
- Metric parity: `True`
- Prepared endpoint result retained: `False`

Prepared score reuses market arrays and returns `NativeEventScoreResult` rather than storing full public artifacts on the endpoint.
