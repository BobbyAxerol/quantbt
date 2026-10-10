"""Thin Mode5 study/selection hooks on the existing public WFO evaluator."""
from dataclasses import replace
import math
from time import perf_counter

import numpy as np
import optuna

from .diagnostics.identity import AnalysisKey, digest
from .dossier.governance import require_formal_chronology
from .selection.advisory import AdvisoryDossier
from .selection.contracts import Candidate, Channel, Formula, LocalEvidence, Panel, Probe, SelectionPlan
from .selection.pareto import ParetoPreference
from .selection.selectors import select
from .statistics.contracts import MetricValue
from ..optimization.study_schedule import run_ordered_study


class Mode5NoSelectionError(ValueError):
    """No unsupported vector is routed into a final financial execution."""


class PublicMode5Runtime:
    def __init__(self, engine, calibration, data, index, param_ranges):
        self.engine, self.calibration, self.data, self.index = engine, calibration, data, index
        calibration.preflight(engine, data, index, param_ranges)
        recipe = calibration.plan.record.data["recipe"]
        obj = recipe["objective"]
        self.channel = Channel(**obj["channel"])
        if self.channel.name not in {"ECONOMIC_UTILITY_V1", "PSR_EVIDENCE_V1"}:
            raise NotImplementedError("legacy objective observations require explicit rescore, not scalar import")
        self.formula = Formula(obj["version"], self.channel, tuple(obj["coefficients"].items()))
        self.reference = calibration.reference
        b = calibration.binding.data
        self.preference = ParetoPreference(**b["selection"]["pareto_preference"]) if b["selection"]["pareto_preference"] else None
        self.context_id = digest(calibration.dossier.record.data["context"])
        incumbent = b["selection"]["incumbent_params"]
        incumbent_id = digest(incumbent) if incumbent is not None else None
        self.selection_plan = SelectionPlan(calibration.plan.record.identity, self.context_id, "formal_search_v1",
            self.formula, self.reference.identity, b["selection"]["requested_selector"],
            b["selection"]["minimum_improvement"], incumbent_id=incumbent_id,
            local_reference_id=b["selection"]["local_reference_id"],
            local_reference_scale=b["selection"]["local_reference_scale"],
            pareto_preference_identity=self.preference.identity if self.preference else None,
            access_identity=calibration.access.identity)
        self.rows, self.candidates, self.locals, self.params = [], {}, {}, {}
        self.observations = {}
        self.study = None
        self.started = perf_counter()
        self.evaluation_seconds = 0.
        self.metadata = dict(schema="quantbt.mode5.public_run.v1", status="PREFLIGHT_VALIDATED",
            dossier_id=calibration.dossier.record.identity, calibration_plan_id=calibration.plan.record.identity,
            runtime_binding_identity=calibration.binding.identity, validation_claim="none_full_sample_calibration",
            meta_learning_activated=False, automatic_routing=False, deployment_authorized=False,
            advisory_shortlist=calibration.dossier.record.data["recommendations"]["recipes"])

    def _panel(self, candidates):
        return Panel(self.context_id, "formal_search_v1", self.channel, self.reference,
            tuple(candidates), self.calibration.access, "fixed_panel", self.calibration.plan.record.identity)

    def _decision(self, candidates, locals, *, point_objective=False):
        kwargs = dict(local_evidence=tuple(locals), pareto_preference=self.preference)
        if self.selection_plan.requested_selector == "full_alpha_adaptive_invariant":
            c = self.calibration
            recipe = c.plan.record.data["recipe"]
            from .diagnostics.access import AccessWitness
            sources = c.catalog.manifest.data["sources"]
            witness = AccessWitness(**sources[0]["witness"])
            advice = AdvisoryDossier("mode5.advisory.v1", c.dossier.record.identity, self.context_id,
                tuple(s["sha256"] for s in sources), ((recipe["selector"]["id"], self.formula.identity),), witness)
            kwargs.update(dossier=advice, researcher_choice=recipe["selector"]["id"], override_reason=c.plan.record.data["reason"])
        plan = replace(self.selection_plan, incumbent_id=None) if point_objective else self.selection_plan
        return select(self._panel(candidates), plan, **kwargs)

    def _observe_point(self, params, folds, trial_id, *, stage):
        from ..walkforward import _slice_output_to_test
        started = perf_counter()
        tasks = []
        for w in self.calibration.windows:
            idx = self.index[(self.index.asi8 >= w.start_ns) & (self.index.asi8 <= w.end_ns)]
            fold = replace(folds[0], train_index=idx, test_index=idx,
                train_start=idx[0], train_end=idx[-1], test_start=idx[0], test_end=idx[-1],
                cutoff_timestamp=idx[-1], account_policy="reset_flat")
            prefix = self.engine._prepared_data_through(self.data, idx[-1], strategy_copy=False)
            output = self.engine._call_strategy(prefix, params, fold)
            tasks.append((_slice_output_to_test(output, idx), idx, fold, params, stage))
        raw = self.engine._score_strategy_outputs_with_scope(self.data, tasks, trial_id=trial_id,
            params=params, stage=stage, adaptive_optimizer=True, study_id=0)
        observations = tuple(r["mode5_observation"] for r in raw)
        self.evaluation_seconds += perf_counter()-started
        return observations

    def _candidate(self, params, observations):
        cid = digest(params)
        metrics = []
        analyses = []
        for w, row in zip(self.calibration.windows, observations, strict=True):
            raw = row["utility"] if self.channel.name == "ECONOMIC_UTILITY_V1" else row["psr"]
            metric = MetricValue(self.channel.metric_contract, self.channel.unit, raw["sample_count"],
                raw["value"], raw["status"], raw["reason"], tuple(raw["components"]))
            metrics.append(metric)
            analyses.append(AnalysisKey(row["account_identity"], w.environment_id,
                row["metric_contract"], self.reference.identity))
        return Candidate(cid, cid, tuple(metrics), tuple(analyses), tuple(w.witness for w in self.calibration.windows),
            digest(observations), True, all(r["risk_pass"] for r in observations),
            all(r["quality_pass"] for r in observations), all(r["support_pass"] for r in observations), True,
            0., activity_penalty_unit=self.channel.unit)

    def _local(self, candidate, params, folds, trial_id, space):
        offsets = self.calibration.binding.data["local_offsets"]
        if not offsets:
            return None
        probes = []
        for offset in offsets:
            try:
                requested = dict(params)
                for name, delta in offset["delta"].items():
                    requested[name] += delta
                effective = space.effective(requested)
            except (ValueError, TypeError, KeyError):
                value, status = None, "INVALID"
                analysis = AnalysisKey(digest((params, offset)), "invalid_probe", self.channel.identity, self.reference.identity)
            else:
                observed = self._observe_point(effective, folds, trial_id, stage="mode5.local_probe")
                point = self._candidate(effective, observed)
                valid = all(m.status == "VALID" for m in point.metrics) and point.risk_pass and point.support_pass
                value = float(np.average([m.value for m in point.metrics], weights=self.reference.weights)) if valid else None
                analysis = AnalysisKey(digest(observed), "weighted_environment_mean_v1",
                    self.channel.identity, self.reference.identity)
                status = "COMPLETE" if valid else "INVALID"
            probes.append(Probe(offset["probe_id"], value, status, analysis, self.calibration.windows[0].witness))
        s = self.calibration.binding.data["selection"]
        return LocalEvidence(candidate.candidate_id, self.channel, s["local_reference_id"], s["local_reference_scale"],
            "weighted_environment_mean_v1", tuple(o["probe_id"] for o in offsets), tuple(probes),
            "OBSERVED_REQUIRED_RADII", "SCHEMA_ONLY_REGISTERED", self.calibration.binding.identity,
            self.calibration.plan.record.data["recipe"]["validation"]["contract_id"])

    def optimize(self, data, folds, param_ranges, **kwargs):
        from ..walkforward import WalkForwardTrialRecord
        c, cfg = self.calibration, self.engine.config
        bridge = self.engine._sampler_bridges[0]
        incumbent = c.binding.data["selection"]["incumbent_params"]
        if incumbent is not None and not cfg.sampler_warm_start:
            raise ValueError("incumbent must be registered as a coordinate-only warm start within query budget")
        if incumbent is not None and digest(bridge.space.effective(cfg.sampler_warm_start[0]["params"])) != digest(incumbent):
            raise ValueError("first warm start must evaluate the frozen incumbent")
        start = c.journal.begin_search(c.dossier, c.plan, c.catalog, c.access, "public-study-0")
        chronology = require_formal_chronology(c.journal, c.dossier.record.identity, c.plan.record.identity,
                                              start.data["sealed_at_ns"])
        self.metadata.update(status="RUNNING", chronology=chronology.data)
        study = optuna.create_study(direction="maximize", sampler=bridge.observed, pruner=optuna.pruners.NopPruner())
        self.study = study
        bridge.enqueue(study, cfg.sampler_warm_start)
        seen = {}

        def evaluate(trial, suggested):
            requested, params = suggested
            cid = digest(params)
            row = dict(trial_id=trial.number, requested_params=requested, effective_params=params,
                       candidate_id=cid, state="RUNNING", evaluation_ref=None)
            self.rows.append(row)
            if cid in seen:
                row.update(state="PRUNED", reason="DUPLICATE_EFFECTIVE_PARAMS", evaluation_ref=seen[cid])
                trial.set_user_attr("qms_rejection_reason", "DUPLICATE_EFFECTIVE_PARAMS")
                raise optuna.TrialPruned("DUPLICATE_EFFECTIVE_PARAMS")
            try:
                observed = self._observe_point(params, folds, trial.number, stage="mode5.search")
                candidate = self._candidate(params, observed)
                local = self._local(candidate, params, folds, trial.number, bridge.space)
                self.candidates[cid], self.params[cid], self.observations[cid] = candidate, params, observed
                if local is not None:
                    self.locals[cid] = local
                decision = self._decision((candidate,), (local,) if local else (), point_objective=True)
                component = decision.metadata["component_rows"][0]
                row.update(evaluation_ref=digest(observed), observations=observed,
                    raw_sharpe=float(np.mean([r["raw_sharpe"] or 0. for r in observed])),
                    objective=component["score"], components=component, state="COMPLETE")
                seen[cid] = row["evaluation_ref"]
                if component["score"] is None:
                    row.update(state="PRUNED", reason="UNDEFINED_OBJECTIVE")
                    raise optuna.TrialPruned("UNDEFINED_OBJECTIVE")
                return component["score"]
            except optuna.TrialPruned:
                raise
            except Exception as exc:
                row.update(state="FAILED", error_type=type(exc).__name__)
                raise

        try:
            run_ordered_study(study, budget=cfg.optuna_trials, batch_size=c.binding.data["batch_size"],
                suggest=bridge.suggest, evaluate=evaluate,
                cancellation=cfg.metadata.get("mode5_cancellation"),
                deadline_seconds=cfg.metadata.get("mode5_deadline_seconds"))
            if not self.candidates:
                raise Mode5NoSelectionError("NO_SUPPORTED_CONFIGURATION: no evaluated candidate")
            choice = self._decision(self.candidates.values(), self.locals.values())
            self.metadata.update(decision=choice.metadata, selection_decision_id=choice.identity)
            cid = choice.metadata["chosen_candidate"]
            if cid is None:
                raise Mode5NoSelectionError("NO_SUPPORTED_CONFIGURATION; inspected gates retained in mode5_metadata")
            selected_params = self.params[cid]
            c.journal._append("CANDIDATES_FROZEN", {"candidate_ids": sorted(self.candidates), "plan_id": c.plan.record.identity})
            c.journal._append("SELECTION_SEALED", {"decision_id": choice.identity, "params_digest": cid,
                                                  "plan_id": c.plan.record.identity})
            replay = self._observe_point(selected_params, folds, -1, stage="mode5.selected_audit")
            expected = self.observations[cid]
            for a, b in zip(expected, replay, strict=True):
                if a["finance"] != b["finance"] or a["utility"] != b["utility"] or a["psr"] != b["psr"]:
                    raise ValueError("selected replay finance/components mismatch; no final vector allowed")
            self.metadata.update(status="SELECTED_REPLAY_VERIFIED", selected_params_digest=cid,
                selected_audit=replay, capability=dict(callbacks="strategy_owned_python", execution="original_endpoint"),
                selected_replay_retention="audit_requested_on_original_endpoint")
            c.preflight(self.engine, self.data, self.index, param_ranges)
            records = [WalkForwardTrialRecord(r["trial_id"], r["effective_params"],
                r.get("objective") if r.get("objective") is not None else -math.inf,
                r.get("raw_sharpe", 0.), 0., 0., 0., [], r["state"] != "COMPLETE",
                dict(stage="diagnostics_first_full_sample", state=r["state"],
                    objective_unit=self.channel.unit, evaluation_ref=r["evaluation_ref"])) for r in self.rows]
            selected = next(r for r in records if digest(r.params) == cid and not r.pruned)
            selected = replace(selected, selection_metadata={**selected.selection_metadata,
                "selected_by": choice.metadata["resolved_selector"], "mode5_diagnostics_first": self.metadata})
            return selected, records, [r for r in records if not r.pruned]
        except Exception as exc:
            self.metadata.update(status="FAILED_CLOSED", error_type=type(exc).__name__)
            exc.mode5_metadata = self.metadata
            raise
        finally:
            attempted = {r["trial_id"] for r in self.rows}
            for trial in study.trials:
                if trial.number not in attempted:
                    self.rows.append(dict(trial_id=trial.number, requested_params=dict(trial.params),
                        effective_params=None, candidate_id=None, evaluation_ref=None,
                        state="PRUNED" if trial.state == optuna.trial.TrialState.PRUNED else "FAILED",
                        reason=trial.user_attrs.get("termination", "NOT_EVALUATED")))
            self.rows.sort(key=lambda r: r["trial_id"])
            self.metadata.update(trial_ledger=self.rows, sampler=bridge.metadata(study),
                optimizer_schedule=c.plan.record.data["recipe"]["sampler"]["schedule"],
                batch_size=c.binding.data["batch_size"],
                candidate_sequence_equivalent_to_sequential=c.binding.data["batch_size"] == 1,
                trial_reports="one completed full candidate at step 0; NopPruner", meta_learning_activated=False)
            self.metadata["compute_bill"] = dict(elapsed_seconds=perf_counter()-self.started,
                successful_evaluation_seconds=self.evaluation_seconds,
                original_account_observations=self.engine.scorer.mode5_metric_policy.evaluations,
                effective_candidates=len(self.candidates), query_attempts=len(study.trials),
                heavy_trial_reports=0, equity_and_daily_inputs_retained=True,
                native_scalar_score_eligible=False, failed_cost_not_omitted_from_elapsed=True)
            c.catalog.verify_current()

    def close(self):
        self.data = self.index = self.engine = self.study = None
        self.candidates.clear()
        self.locals.clear()
        self.params.clear()
        self.observations.clear()
