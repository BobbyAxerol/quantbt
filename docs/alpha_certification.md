# Alpha Execution Certification

Phase 31D adds lightweight tooling to classify alpha source files by the
execution contract they appear to require.

The scanner is intentionally conservative. It does not prove a strategy is free
of look-ahead bias. It finds execution-sensitive markers and tells the reviewer
which QuantBT route should be used before making production-style claims.

## CLI

```bash
PYTHONPATH=/root/bobby/pool_alpha \
python3 quantbt/tools/audit_alpha_execution_contracts.py \
  /root/bobby/pool_alpha/alphas_storage/TA \
  --json-out /tmp/alpha_contracts.json \
  --md-out /tmp/alpha_contracts.md
```

Default outputs are written under `benchmarks/out/`, which is ignored by git for
local scans.

## Python API

```python
from quantbt import (
    scan_alpha_directory,
    build_alpha_certification_report,
    alpha_report_markdown,
)

items = scan_alpha_directory("/root/bobby/pool_alpha/alphas_storage/TA")
report = build_alpha_certification_report(items)
markdown = alpha_report_markdown(report)
```

To classify a string directly:

```python
from quantbt import classify_alpha_source

item = classify_alpha_source(source_text, alpha_id="my_alpha")
print(item.required_engine)
```

## Classification Output

Each row contains:

```text
alpha_id
path
required_engine
current_backend
certification_status
certification_level
markers
notes
uses_stop / uses_take_profit / uses_trailing / uses_explicit_fills / uses_grid_or_dca
```

Typical required engines:

| Required engine | Meaning |
|---|---|
| `close_target_v2` | plain target signal route |
| `next_open_v1` | next-open timing required |
| `intrabar_bracket_v1` | SL/TP/trailing/high-low exit semantics required |
| `fill_replay_v1` | alpha emits fills; replay accounting first |
| `event_lifecycle_v2` | grid/DCA/package order lifecycle required |
| `unknown` | manual review required |

## Certification Metadata

Result metadata can be summarized with:

```python
from quantbt import certify_result_metadata

cert = certify_result_metadata(result.metadata)
```

Levels:

```text
0 legacy_or_unspecified_execution_contract
1 explicit_fills_accounted_but_fill_generation_not_certified
2 engine_owned_causal_execution_with_oracle_or_kernel_parity
3 native_engine_matches_native_event_on_known_scenarios
4 external_or_lower_timeframe_validation_available
```

## Migration Workflow

1. Scan the alpha source directory.
2. Treat `requires_intrabar_migration` as a hard warning, not a cosmetic note.
3. For old alphas with explicit `exit_price`, first replay existing fills with
   `fill_replay` to lock accounting.
4. Convert the alpha output into compact `entry_signal`, `stop_value`,
   `take_profit_value`, `trailing_value`, and `technical_exit` intent columns.
5. Compare `intrabar_bracket_reference` against `intrabar_bracket` on a small
   sample.
6. Use `report_level="audit"` for stakeholder/debug runs and
   `report_level="minimal"` for optimizer loops.
7. Add Nautilus/lower-timeframe validation only when the strategy needs Level 4
   evidence.

## Production Claim Rule

Do not call an execution-sensitive alpha production-certified just because it
runs through a vectorized endpoint. A stop-loss/take-profit/trailing strategy
should reach Level 2 at minimum. For investor or stakeholder reports, Level 3
or Level 4 evidence is preferred.
