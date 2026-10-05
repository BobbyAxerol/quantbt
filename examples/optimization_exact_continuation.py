"""Exact owned sampler continuation, using a toy objective, not an alpha claim.

Run from an installed package: python examples/optimization_exact_continuation.py
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from quantbt.optimization import SamplerConfig
from quantbt.optimization.continuation import ContinuationConfig, ExactStudySession

RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")
BINDING = {key: key + ":toy-example-v1" for key in (
    "market", "calendar", "accounting", "objective", "schedule",
    "meta_snapshot", "meta_basis", "meta_task")}


def configuration(recipe):
    return ContinuationConfig(
        sampler_config=SamplerConfig(name=recipe, constraint_mode="post_filter"),
        ranges={"z": {"kind": "float", "low": -2., "high": 2.},
                "a": {"kind": "integer", "low": 1, "high": 9}},
        seed=731, budget=48, cutoff="2024-01-01T00:00:00Z",
        strategy_identity="toy-example-v1", duplicate_policy="allow",
        result_constraints=True,
        pruner={"name": "median", "kwargs": {"n_startup_trials": 3}},
    )


def advance(session, count):
    for _ in range(count):
        proposal = session.ask()
        value = 4. - (proposal.effective["z"] - .5)**2 - proposal.effective["a"] / 10
        session.report(proposal.number, value, 0)
        if session.should_prune(proposal.number):
            session.tell(proposal.number, state="PRUNED", reason="PRUNER")
        elif proposal.number % 11 == 7:
            session.tell(proposal.number, state="FAIL", reason="EXPLICIT_TOY_FAILURE")
        else:
            session.tell(proposal.number, value, constraints=(-1.,))


def prove(recipe, workspace):
    cfg = configuration(recipe)
    full = ExactStudySession(cfg, binding=BINDING)
    advance(full, 48)
    partial = ExactStudySession(cfg, binding=BINDING)
    advance(partial, 23)
    path = workspace / (recipe + ".json")
    expected_digest = partial.save(path)
    resumed_json = subprocess.check_output(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--resume", recipe,
         "--checkpoint", str(path), "--digest", expected_digest], cwd=workspace, text=True)
    resumed = json.loads(resumed_json.splitlines()[-1])
    assert resumed == full.witness()
    # A separately owned in-process resume is also available to the caller.
    restored = ExactStudySession.load(path, config=cfg, binding=BINDING, expected_digest=expected_digest)
    assert restored.witness() == partial.witness()
    return dict(recipe=recipe, attempts=48, split=23, journal_sha256=expected_digest,
                fresh_process_exact=True, best_trial=full.best_trial.number,
                states=sorted({trial.state.name for trial in full.trials}))


if __name__ == "__main__":
    import argparse
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", choices=RECIPES)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--digest")
    args = parser.parse_args()
    if args.resume:
        session = ExactStudySession.load(args.checkpoint, config=configuration(args.resume),
                                         binding=BINDING, expected_digest=args.digest)
        advance(session, 25)
        print(json.dumps(session.witness(), sort_keys=True))
    else:
        with tempfile.TemporaryDirectory(prefix="quantbt-continuation-") as workspace:
            matrix = [prove(recipe, Path(workspace)) for recipe in RECIPES]
        print(json.dumps(dict(matrix=matrix, economic_claim=False, publication=False), sort_keys=True))
