# QuantBT Benchmarks

Phase 7 introduces a reproducible benchmark harness for the upgraded backtest
backends.

```bash
python3 benchmarks/run_phase7.py --profile smoke
python3 benchmarks/run_phase7.py --profile standard --repeats 5
```

Profiles:

- `smoke`: quick local sanity check.
- `standard`: commit-to-commit comparison target.
- `large`: stress profile for optimization decisions.

The runner writes both JSON and Markdown into `benchmarks/out/` by default.
Nautilus is optional and skipped unless `--include-nautilus` is passed.
