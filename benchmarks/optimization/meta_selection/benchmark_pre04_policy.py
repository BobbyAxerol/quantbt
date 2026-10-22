"""Software proposal/checkpoint cost, not sampler quality or economic parity."""

import argparse
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

import optuna

from quantbt.optimization import SamplerConfig
from quantbt.optimization.continuation import ContinuationConfig, ExactStudySession

RANGES = {"x": {"kind": "float", "low": .001, "high": 1., "log": True},
          "y": {"kind": "integer", "low": 1, "high": 19}, "fixed": 2}
BINDING = {k: "pre04-cost:"+k for k in ("market", "calendar", "accounting", "objective",
    "schedule", "meta_snapshot", "meta_basis", "meta_task")}


def advance(session, n):
    for _ in range(n):
        p = session.ask()
        if p.duplicate:
            session.tell(p.number, state="PRUNED")
        else:
            session.tell(p.number, float(p.effective["x"] - p.effective["y"]/100.))


def measured(policy, budget):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    config = ContinuationConfig(SamplerConfig(name="sobol", sobol_policy=policy), RANGES,
        731, budget, "2024-01-01T00:00:00Z", "public-synthetic-pre04-cost")
    t = time.perf_counter()
    session = ExactStudySession(config, binding=BINDING)
    prepare = time.perf_counter()-t
    t = time.perf_counter()
    advance(session, budget//2)
    first_half = time.perf_counter()-t
    t = time.perf_counter()
    text, sha = session.dumps()
    encode = time.perf_counter()-t
    t = time.perf_counter()
    resumed = ExactStudySession.loads(text, config=config, binding=BINDING, expected_digest=sha)
    restore = time.perf_counter()-t
    t = time.perf_counter()
    advance(session, budget-budget//2)
    last_half = time.perf_counter()-t
    advance(resumed, budget-budget//2)
    assert session.witness() == resumed.witness()
    return dict(policy=policy, attempts=budget, financial_calls=0, prepare_ms=prepare*1000,
        proposal_tell_ms=(first_half+last_half)*1000, checkpoint_encode_ms=encode*1000,
        restore_ms=restore*1000, checkpoint_bytes=len(text.encode()),
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024., exact_resume=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=("legacy_v1", "conditional_numeric_latent_v1"))
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(measured(args.child, args.budget), sort_keys=True))
        return
    rows = []
    for budget in (128, 600):
        for policy in ("legacy_v1", "conditional_numeric_latent_v1"):
            samples = []
            for _ in range(3):
                result = subprocess.run([sys.executable, "-m", __name__ if __name__ != "__main__"
                    else "benchmarks.optimization.meta_selection.benchmark_pre04_policy",
                    "--child", policy, "--budget", str(budget)], check=True, capture_output=True, text=True)
                sample = json.loads(result.stdout)
                samples.append(sample)
            fields = ("prepare_ms", "proposal_tell_ms", "checkpoint_encode_ms", "restore_ms", "peak_rss_mib")
            rows.append(dict(policy=policy, attempts=budget, samples=samples,
                median={k: statistics.median(s[k] for s in samples) for k in fields}))
    receipt = dict(schema="qms-pre04-policy-cost-v1", scope="proposal_and_owned_checkpoint_only",
        repetitions=3, threads=1, seed=731, financial_calls=0, whole_wfo_speed_claim=False,
        p95_claim=False, economic_claim=False, same_proposals_across_policies=False, rows=rows)
    if args.output:
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
