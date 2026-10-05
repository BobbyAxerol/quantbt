# Persisted Exact Optuna Continuation

QMS-C04 adds an **opt-in owned session**, not automatic resume for
`QuantBTEndpoint.walk_forward`, W3, R3B, or `OptunaOptimizer(storage=...)`.
Existing endpoint arguments, schedules, search, selection and accounting stay
unchanged. Use the same public sampler config and normalized parameter schema.

## What Is Exact

The checkpoint records every owned ask/suggest, intermediate report, pruning
query, constraint vector and terminal tell, in its original order. Restore
creates the same factory sampler and replays those events with recorded
observations. Every proposal/pruning decision and the final study witness must
match exactly before the session is returned. This reconstructs RNG, sampler,
trial, pruner, duplicate and supported callback state; seed alone does not.

Restoring never evaluates the strategy or backtest again. Only remaining trials
call the caller's evaluator. Historical objectives here are the observations
of **this same study**; they are not warm-start scores imported into a new IS
window. Changing the IS cutoff, tape, evaluator or meta snapshot requires a new
study with properly authorized and rescored params-only warm starts.

No pickle or Optuna system-attribute payload is accepted from a checkpoint.
Optuna's pinned CMA implementation generates its own optimizer state during
replay; its internal serialization is not a public checkpoint deserializer.
Trial timestamps, diagnostic wall times and storage-specific UUIDs are not
reproducible semantic state and are deliberately excluded from the witness.

## Supported Boundary

| Component | Contract |
|---|---|
| Samplers | Four existing recipes; Optuna 4.8.0 / cmaes 0.12.0; existing factory kwargs/geometry rules |
| Runtime | Matching Python patch, implementation, OS/architecture, NumPy/SciPy versions and reviewed execution-policy source hashes; locally tested CPython 3.12/Linux only |
| Objectives | One direction, finite numeric observations; COMPLETE, PRUNED and FAIL retained individually |
| Pruners | Data-only Nop and Median configs; report/query order retained |
| Callback | Existing `SingleObjectiveEarlyStopping` behavior, with owned ask/tell stop flag; no arbitrary callback object or external logger replay |
| Duplicates | Effective-parameter identity, `allow` or explicit `prune`; attempted failures remain in the seen set |
| Concurrency | One owner thread; ordered batch asks/tells supported at completed barriers, not uncontrolled distributed arrival order |
| Checkpoint | No RUNNING trials; initial authorized WAITING warm-start queue may remain |
| Limits | 16 MB JSON and 100,000 events/budget ceiling; no opaque state serializer |

Unsupported sampler callback objects, pruners, seed `None`, unrecorded mutations,
corrupt/partial state or mismatched identities fail explicitly. Finish or
explicitly mark pending work FAIL/PRUNED before saving; a failed half-operation
poisons the session and cannot be checkpointed. Do not silently drop pending
work or claim equivalence to a uninterrupted successful evaluation.

## Usage

```python
from quantbt.optimization import SamplerConfig
from quantbt.optimization.continuation import ContinuationConfig, ExactStudySession

config = ContinuationConfig(
    sampler_config=SamplerConfig(name="tpe_legacy"),
    ranges={"window": {"kind": "integer", "low": 8, "high": 40}},
    seed=731, budget=100, cutoff="2024-01-01T00:00:00Z",
    strategy_identity="my-alpha-v3",
)
# Compute these identities from authoritative caller-owned run contracts.
# Use explicit reviewed 'off' identities for absent meta/history/basis state.
binding = {
    "market": market_digest, "calendar": calendar_digest,
    "accounting": economics_digest, "objective": objective_digest,
    "schedule": schedule_digest, "meta_snapshot": history_snapshot_digest,
    "meta_basis": model_basis_digest, "meta_task": task_digest,
}
session = ExactStudySession(config, binding=binding)
proposal = session.ask()
if proposal.duplicate:
    session.tell(proposal.number, state="PRUNED")
else:
    objective = evaluate_current_is(proposal.effective)
    session.tell(proposal.number, objective)
checkpoint_digest = session.save("checkpoints/study.json")

# In a fresh process, supply the original reviewed identities and digest.
session = ExactStudySession.load(
    "checkpoints/study.json", config=config, binding=binding,
    expected_digest=checkpoint_digest,
)
# Advance remaining work; never enqueue the old observations into another IS.
```

Keep the expected digest outside the file in a trusted run manifest. The
internal checksum detects damage, not authorship; caller bindings do not prove
the underlying data or history scientifically valid. Continue verifying meta
history/artifacts through their existing authorization/as-of contracts. The
checkpoint binds their exact identities; it does not deserialize a financial
account, strategy, history archive or model itself.

`report(number, value, step)` and `should_prune(number)` preserve intermediate
decisions. `tell(..., constraints=..., reason=...)` uses the existing shared
constraint convention. `trials`, `best_trial`, `stopped` and `witness()` expose
copied semantic state. No mutable Optuna study is exported for bypassing the
journal. A batch must keep its declared proposal and completion order; it must
not be rewritten as sequential asks/tells during restore.

## Durability And Cost

Writes use a POSIX local-file lock, temporary file, fsync, atomic replacement
and directory fsync. Replacing a checkpoint requires `previous_digest`; a stale
writer fails. The sidecar `.lock` file is intentional. NFS/distributed locks
and Windows writers are not certified. If failure occurs after replacement but
before acknowledgement, reconcile against the intended digest before retrying;
never overwrite by dropping the compare-and-swap guard.

Save retains compact parameters/observations, not market arrays/equity/fills.
Restore redoes sampler work for the recorded history, not financial execution:
cost depends on the number of events and sampler's own adaptive complexity.
It is **not O(1) RNG snapshot restore** and not a WFO acceleration claim. Existing
sampler performance and economic/scientific acceptance evidence is unchanged.

Run the [installed-package example](../../examples/optimization_exact_continuation.py)
for four-recipe fresh-process proof. See [the C04 report](QMSC04_REPORT.md) for
measured costs and exact local scope. Upstream [RDB resume documentation](https://optuna.readthedocs.io/en/v4.8.0/tutorial/20_recipes/001_rdb.html)
explains why trial storage and a reconstructed seed are not sampler-state
continuation; this module avoids importing serialized sampler objects.
