"""Read/revalidate a portable decision; no broker, reset, deployment or replay.

Run: python -m examples.wfo_meta_handoff --demo-support
"""

from __future__ import annotations

import argparse
import json

from examples.wfo_meta_selection import run_demo
from quantbt.optimization.meta_selection.common import digest
from quantbt.optimization.meta_selection.handoff import (
    dumps_handoff,
    export_fold_handoff,
    loads_handoff,
)
from quantbt.optimization.meta_selection.model import FitOutcome, schema_from_payload
from quantbt.optimization.meta_selection.selection import MetaSelector


def consume_reviewed(bundle, *, now):
    # In a real host these permissions, trusted ID and evidence come from its
    # reviewed store, not fields accepted blindly from an untrusted JSON file.
    witnesses = {
        o.output_ref: digest(o)
        for r in bundle.snapshot.revisions
        for o in [
            *(c.observation for c in r.task.candidates),
            *(c.observation for c in r.outcomes),
        ]
    }
    restored = loads_handoff(
        dumps_handoff(bundle),
        expected_handoff_id=bundle.handoff_id,
        available_as_of=now,
        authorized_corpora=bundle.snapshot.authorized_corpora,
        expected_family_id=bundle.task.family.family_id,
        verified_output_witnesses=witnesses,
        reviewed_revision_ids=tuple(r.revision_id for r in bundle.snapshot.revisions),
    )
    if restored.model is not None:
        # Revalidate the same frozen historical decision using the shared pure
        # selector, not a new live decision with backdated readiness/activation.
        model = restored.model
        proposal = MetaSelector().propose(
            restored.task,
            FitOutcome(model, "FIT_VALID", model.origin_count),
            schema=schema_from_payload(model.schema),
            ready_at=restored.decision.ready_at,
        )
        assert proposal.proposed_params == restored.decision.proposed_params
    return restored.read_params(available_as_of=now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-support", action="store_true")
    args = parser.parse_args()
    _, result, _ = run_demo("active", min_origins=1 if args.demo_support else 12)
    row = result.metadata["walk_forward"]["meta_selection"]["records"][-1]
    bundle = export_fold_handoff(result, fold_id=row["fold_id"])
    params = consume_reviewed(bundle, now=bundle.decision.ready_at)
    print(
        json.dumps(
            {
                "handoff_id": bundle.handoff_id,
                "selected_params": params,
                "model_id": bundle.decision.model_id,
                "effective_at": None,
                "host_state_mutations": 0,
                "live_trading_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
