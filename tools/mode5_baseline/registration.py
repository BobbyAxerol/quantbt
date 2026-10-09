"""Freeze information rights and unresolved preconditions before market work."""

from __future__ import annotations

from datetime import datetime
import math

from .isolation import canonical_digest


HYPOTHESES = (
    ("EH-01", "Environment floor", "matched lower-tail net utility", "exposure-only reduction"),
    ("EH-02", "Active local robustness", "held-probe downside with acceptable center", "sampler density"),
    ("EH-03", "Pareto trade-off", "held-environment mandate utility", "reference weights"),
    ("EH-04", "PSR evidence ranking", "frequency-correct threshold coverage", "sample-size preference"),
    ("EH-05", "Sampler consequences", "paired quality/coverage/work", "independent fallback or single seed"),
    ("EH-06", "Adaptive parameter effect", "clamp-active versus inactive sensitivity", "short-window low effect"),
    ("EH-07", "Conditional local stability", "branch/warmup/amendment matched utility", "different scored calendar"),
    ("EH-08", "Campaign tails", "net campaign versus account tail", "partial fills counted independently"),
    ("EH-09", "Exposure concentration", "net contribution outside dominant episode", "one market-long shock"),
    ("EH-10", "Useful forward decay", "fixed-parameter forward utility AND decay", "lower IS without forward gain"),
    ("EH-11", "Advisory governance", "whole-process held-decision utility", "winner lookup or adaptive radar scale"),
    ("EH-12", "Computational reuse", "cold/warm exact components/decisions/accounting", "stale rights or mutable state"),
)


def study_registration(alpha_ids: list[str], guide_sha: str) -> dict:
    questions = [{"id": key, "question": question, "primary_estimand": estimand,
                  "rival_explanation": rival, "scope": "development diagnostics only",
                  "test_phase": "M5-03..11", "status": "REGISTERED_NOT_TESTED",
                  "permitted_claim": "within registered alpha/domain/horizon only"}
                 for key, question, estimand, rival in HYPOTHESES]
    support = {alpha: {
        "status": "UNRESOLVED_REQUIRES_OWNER_REVIEW_BEFORE_MARKET_WORK",
        "is_start": None, "is_end": None, "forward_start": None, "forward_end": None,
        "min_scored_is_days": None, "min_scored_forward_days": None,
        "minimum_accepted_orders": None, "minimum_fills": None,
        "minimum_closed_campaigns": None, "minimum_independent_origins": None,
        "minimum_tail_support": None, "minimum_meaningful_effect": None,
        "confidence_policy": None, "execution_clock": None, "sizing": None,
        "costs": None, "warmup": None, "terminal_policy": None,
        "proposal": "derive calendar/event thresholds from admission holding/opportunity profile; approve before results",
        "extension_policy": "predeclared calendar/opportunity-only revision; never effect/significance stopping",
    } for alpha in alpha_ids}
    result = {"schema": "quantbt.mode5_baseline.study_registration.v1", "guide_sha256": guide_sha,
              "scope": "M5-01 source and artifact research-contract freeze",
              "hypotheses": questions, "alpha_support": support,
              "baseline_policy": "legacy Mode5 + historical artifact controls; formal configs sealed M5-09",
              "sampler_design": {"recipes": ["tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"],
                                 "seed": None, "paired_seed_design": "PENDING_REVIEW", "meta": "off"},
              "risk_policy": "net costs, actual accepted execution, no forced trades/positive results",
              "data_rights": {"reviewed_2024": "EXPLORATORY_REVIEWED_2024",
                              "fullset_presets": "REFERENCE_ONLY_SELECTION_ADJUSTED",
                              "other_history": "CONTAMINATION_UNKNOWN_NOT_UNTOUCHED"},
              "resource": {"phase_incremental_bytes": 64 * 1024 * 1024,
                           "minimum_free_bytes": 5 * 1024**3, "processes": 1,
                           "threads": 1, "phase_market_evaluations": 0,
                           "market_budget": "REQUIRES_SEPARATE_PHASE_APPROVAL"},
              "no_auto_deploy": True, "market_authorized": False,
              "final_calibration_plan": "NOT_SEALED_FUTURE_M5_09"}
    return result | {"registration_id": canonical_digest(result)}


def authorize_economic_run(registration: dict, alpha: str) -> None:
    payload = {k: v for k, v in registration.items() if k != "registration_id"}
    if canonical_digest(payload) != registration.get("registration_id"):
        raise ValueError("registration changed without revision")
    support = registration["alpha_support"][alpha]
    if (not registration.get("market_authorized") or support["status"] != "APPROVED"
            or any(value is None for key, value in support.items() if key != "proposal")):
        raise ValueError("UNRESOLVED_ECONOMIC_PRECONDITION: no market run authorized")
    numeric = ("min_scored_is_days", "min_scored_forward_days", "minimum_accepted_orders",
               "minimum_fills", "minimum_closed_campaigns", "minimum_independent_origins",
               "minimum_tail_support", "minimum_meaningful_effect")
    if any(isinstance(support[key], bool) or not isinstance(support[key], (int, float))
           or not math.isfinite(support[key]) or support[key] <= 0 for key in numeric):
        raise ValueError("INVALID_ECONOMIC_SUPPORT: positive finite thresholds required")
    dates = [datetime.fromisoformat(support[key]) for key in
             ("is_start", "is_end", "forward_start", "forward_end")]
    if not dates[0] < dates[1] < dates[2] < dates[3]:
        raise ValueError("INVALID_ECONOMIC_CALENDAR: ordered disjoint scored windows required")
    if ((dates[1]-dates[0]).total_seconds()/86400 < support["min_scored_is_days"]
            or (dates[3]-dates[2]).total_seconds()/86400 < support["min_scored_forward_days"]):
        raise ValueError("INSUFFICIENT_ECONOMIC_DURATION")
