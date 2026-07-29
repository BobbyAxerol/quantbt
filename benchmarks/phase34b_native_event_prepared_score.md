# Phase 34B Native Event Prepared Score Benchmark

- Rows: `600`
- Trials: `12`
- Public audit seconds: `1.763319`
- Prepared score seconds: `0.634422`
- Speedup: `2.779x`
- Peak RSS MB: `337.926`
- Metric parity: `True`
- Prepared endpoint result retained: `False`

Prepared score reuses market arrays and returns `NativeEventScoreResult` rather than storing full public artifacts on the endpoint.
