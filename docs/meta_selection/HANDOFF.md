# Portable Decision Handoff

## Scope

Feature-branch QMS-06 exports an immutable, complete decision package from
the existing Mode-4/per-fold-causal result. This is not a new endpoint,
broker connection, deployment controller or account engine. Public core/native
remain 1.1.1 / 0.4.2; this feature has not been published.

`DecisionHandoff` contains the actual task/current candidate pool, exact native
anchor and selection reason, proposed/actual decision, full model when fitted,
and the exact authorized history snapshot with immutable terminal revisions.
The model includes descriptor schema/vocabulary, scaler, coefficients,
permissions, numeric policy, fit support and basis/frontier identifiers.
Cold-start native fallback is also a valid package with no fabricated model.

## Export

```python
from quantbt.optimization.meta_selection.handoff import (
    export_fold_handoff,
    dumps_handoff,
    loads_handoff,
)

# result is an existing completed meta-enabled walk_forward result.
bundle = export_fold_handoff(result, fold_id=0)
text = dumps_handoff(bundle)
```

Export reads existing sidecars; it does not rerun a candidate, refit the model,
send orders, close a position or reset indicators/account state.
`selected_params` means the **actual** winner: native in shadow/fallback,
meta winner in active. Proposed params remain separate in `decision`.

## Trusted Restore

The receiving host must supply authorization from its reviewed artifact store:

```python
restored = loads_handoff(
    text,
    expected_handoff_id=reviewed.handoff_id,
    available_as_of=now,
    authorized_corpora=reviewed.corpora,
    expected_family_id=reviewed.family_id,
    verified_output_witnesses=reviewed.output_witnesses,
    reviewed_revision_ids=reviewed.revision_ids,
    outcome_origins=reviewed.outcome_origins,
    research_exposures=reviewed.research_exposures,
)
params = restored.read_params(available_as_of=now)
```

`reviewed` denotes the caller's own trusted records, not an object constructed
by trusting the incoming JSON. `output_witnesses` maps original output references
to verified observation digests. IDs/hashes detect corruption; self-hashed JSON
does not grant permission. The runnable demonstration uses locally produced,
already reviewed inputs and makes this assumption explicit.

Restore rejects unknown/duplicate fields, nonfinite JSON, corruption, missing
review IDs, wrong economics family or unauthorized corpus/cohort/exposure.
The default serialized-size limit is 32,000,000 bytes; it is a hard failure,
not silent history/pool truncation. Every restored history revision passes the
existing strict witness/authorization decoder. Full model/snapshot/decision
lineage is checked, not merely coefficient shape.

## Time And State

| Clock | Meaning |
|---|---|
| `task.data_cutoff` / `decision.information_as_of` | Frozen permitted input frontier |
| Revision `available_at` | Complete label knowledge available to that snapshot |
| `task.search_completed_at` | Parameter search complete |
| `model.fit_completed_at` / `decision.fit_completed_at` | Model computation ready; cached older model retains its original clock |
| `decision.decision_sealed_at` / `ready_at` | Decision/artifacts ready to consume |
| `bundle.effective_at` | Optional **host-provided** actual activation reference |

A current model trained on later data cannot be substituted into a past task.
A cached older model is permitted only with its exact snapshot, revisions,
basis and original readiness. Restore and `read_params` reject calls before
decision readiness. Replay and wall-generation clocks remain distinct.

Default `effective_at=None` means export has not deployed anything. A host may
pass an actual activation reference to `export_fold_handoff(..., effective_at=...)`;
it cannot precede readiness. The task's recorded backtest first-forward action
remains provenance, not an automatically asserted live activation.

The host owns carry/wait-flat/amend, pending orders and event cadence. Reading
the same params twice is detached and side-effect-free; it does not reset state.
The module grants no live-trading permission or historical live-equivalence claim.

## Runnable Consumer

```bash
.venv/bin/python -m examples.wfo_meta_handoff --demo-support
```

The public synthetic SMA example obtains a full package, performs strict
reviewed restore, and revalidates the frozen proposal with the same pure
`MetaSelector`; no separate live selection algorithm or financial replay.
Minimum-origin-one is explicitly an engineering fixture; product default is
twelve. Results do not demonstrate economic edge or future robustness.

See [integration](INTEGRATION.md), [model mathematics](MODEL.md),
[QMS-06 report](QMS06_REPORT.md) and the
[approved phase](../../upgrade/implement.md#qms-06).
