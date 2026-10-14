"""Explicit qualification for one candidate's identical whole-IS shard score."""

from typing import Any


EXACT_IS_SHARD_REUSE_SCHEMA_V1 = "deterministic-is-shard-reuse-v1"


def qualifies_exact_is_shard_reuse(scorer: Any) -> bool:
    """Resolve a pure, no-argument scorer qualification; otherwise keep both calls.

    ``deterministic_is_shard_reuse_contract()`` must return exactly
    ``{"schema": "deterministic-is-shard-reuse-v1", "no_rng": True}``.
    V1 certifies that scoring is deterministic, context-independent and free
    of semantic side effects, input mutation and RNG reads/writes (including
    private generators and callbacks). The qualification hook itself is pure.
    Scoring the full-index slice of the same output must preserve account,
    seed and every metric/observation, not just Sharpe. Returned metric values
    must support detached copying. Physical work counters may still differ.

    This is caller qualification, not runtime proof of arbitrary user code.
    It authorizes no reuse across candidates, folds, calls or WFO runs.
    """
    try:
        hook = getattr(scorer, "deterministic_is_shard_reuse_contract", None)
        if not callable(hook):
            return False
        contract = hook()
        return (
            type(contract) is dict
            and set(contract) == {"schema", "no_rng"}
            and type(contract["schema"]) is str
            and contract["schema"] == EXACT_IS_SHARD_REUSE_SCHEMA_V1
            and contract["no_rng"] is True
        )
    except Exception:
        return False
