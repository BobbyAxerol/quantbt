"""Independent raw-observation reduction of saved candidate-level R/Q."""

import math

from .admission import load_corpus, pin, read
from .protocol import GROUPS


def check_economics(row, revision):
    candidates = {c.evaluation_id: c for c in revision.task.candidates}
    outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
    anchor = revision.task.anchor_candidate_evaluation_id
    winner = row["winner"]
    if row["anchor"] != anchor or winner not in candidates:
        raise ValueError("economic decision is not bound to current task")
    observations = (candidates[anchor].observation, candidates[winner].observation,
                    outcomes.get(anchor), outcomes.get(winner))
    actual = row["economics"]
    witnessed = all(o is not None and o.status.value == "VALID" for o in observations)
    if not witnessed:
        if (actual["status"] != "MISSING_OR_UNDEFINED_WINNER_WITNESS"
                or any(actual[k] is not None for k in ("R", "Q", "IS_effect"))
                or actual["winner_witness_exists"] != (winner in outcomes)):
            raise ValueError("missing/undefined winner was treated as an economic observation")
        return False
    ia, iw, oa, ow = (o.raw_sharpe for o in observations)
    expected = dict(anchor_is=ia, selected_is=iw, anchor_forward=oa,
                    selected_forward=ow, R=ia-oa-iw+ow, Q=ow-oa, IS_effect=ia-iw)
    if actual["status"] != "OBSERVED_KNOWN_WINNER" or actual["winner_witness_exists"] is not True:
        raise ValueError("known winner witness was lost")
    for key, value in expected.items():
        if (type(actual[key]) not in (int, float) or not math.isfinite(actual[key])
                or not math.isclose(actual[key], value, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError("raw candidate economic measurement differs: " + key)
    return True


def audit(output):
    result = read(output / "result.json")
    corpora = {g: load_corpus(g) for g in GROUPS}
    observed, missing = 0, 0
    by_group = {g: dict(observed=0, missing_or_undefined=0) for g in GROUPS}
    for row in result["rows"]:
        known = check_economics(row, corpora[row["group"]].revisions[row["fold"]])
        observed += int(known)
        missing += int(not known)
        by_group[row["group"]]["observed" if known else "missing_or_undefined"] += 1
    if observed + missing != 480:
        raise ValueError("full development decision roster required")
    return dict(schema="m4.ml04.raw-economic-measurement.v1", status="PASS",
                result=pin(output / "result.json"), observed=observed,
                missing_or_undefined=missing, by_group=by_group,
                interpretation="conditional known-witness development; not full-pool regret or admitted evaluation efficacy",
                new_financial_calls=0, new_optimizer_proposals=0, new_model_fits=0)
