"""Continuous observation hooks on the existing Mode5 ask/tell runtime."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import optuna

from .continuous import ContinuousAccountReducer, ContinuousExecutionWitness
from .continuous_binding import ContinuousMode5Calibration
from .continuous_producer import qualify_producer, validate_result
from .continuous_retention import ContinuousAccountRetention
from .continuous_scope import ContinuousAccountScope
from .diagnostics.identity import digest
from .dossier.records import Record
from .evaluation import Mode5MetricPolicy
from .runtime import PublicMode5Runtime
from ..optimization.parameter_space import NormalizedSearchSpace


class ContinuousMode5MetricPolicy(Mode5MetricPolicy):
    """One scorer call, followed by dependent views of its actual account."""

    def __init__(self, calibration):
        if not isinstance(calibration, ContinuousMode5Calibration):
            raise TypeError("continuous metric policy requires its own versioned binding")
        super().__init__(calibration)
        self.contract = calibration.continuous_contract
        self.request = None
        self._producer = None
        self._producer_execution = None

    def bind_producer(self, scorer, strategy):
        if self.request is not None:
            raise RuntimeError("cannot replace producer during a continuous evaluation")
        execution = qualify_producer(scorer, strategy, self.contract)
        if scorer.mode5_metric_policy is not self:
            raise ValueError("continuous policy must belong to the original scorer")
        self._producer, self._producer_execution = scorer, execution

    @contextmanager
    def evaluation(self, data, params, *, stage):
        if self.request is not None:
            raise RuntimeError("mutable observation request cannot be shared across evaluations")
        self.request = self.contract.request(data, params,
            role="selection_probe" if stage == "mode5.local_probe" else "formal_search")
        try:
            yield
        finally:
            self.request = None

    def score(self, result, index):
        if self.request is None:
            # The final stitched-account report is not another optimizer query.
            return super().score(result, index)
        if self._producer is None or self._producer_execution is None:
            raise RuntimeError("continuous evaluation requires a qualified original producer")
        validate_result(result, self._producer_execution, self._producer.score_config)
        scored = super().score(result, index)
        c, request = self.contract, self.request
        produced = self._producer_execution.data
        equity = result.equity
        liquidated = bool(getattr(result, "liquidated", False))
        terminal = dict(equity=float(equity.iloc[-1]), liquidated=liquidated,
            terminal_policy=produced["terminal_policy"])
        if liquidated:
            bar = getattr(result, "liquidation_bar", None)
            if type(bar) is not int or not 0 <= bar < len(index):
                raise ValueError("actual liquidation bar required for continuous attribution")
            terminal["liquidated_at_ns"] = int(index[bar].value)
        execution = ContinuousExecutionWitness(request.identity, request.source_identity,
            request.data_identity, request.point.identity,
            digest((request.identity, scored["mode5_observation"]["finance"])),
            produced["backend"], Record.of(produced["clock"]),
            Record.of(produced["initial_state"]), Record.of(terminal))
        observed = ContinuousAccountReducer(c, self).observe(result, index, request=request,
            execution_witness=execution, whole_observation=scored["mode5_observation"])
        scored["mode5_continuous_observation"] = observed.to_metadata()
        scored["mode5_continuous_evaluation"] = observed
        return scored


class _EffectiveSpace:
    def __init__(self, original, geometry):
        self.original, self.geometry = original, geometry

    def __getattr__(self, name):
        return getattr(self.original, name)

    def effective(self, params):
        return self.geometry.resolve(params).params

    def candidate_key(self, params, *, strategy_identity):
        # Keep the shared hash algorithm/schema; only the effective builder differs.
        return NormalizedSearchSpace.candidate_key(self, params, strategy_identity=strategy_identity)


class _GeometryBridge:
    """Retain sampler draws/order; reject, never repair, an infeasible manifold."""

    def __init__(self, bridge, geometry):
        self.bridge, self.geometry = bridge, geometry
        self.space = _EffectiveSpace(bridge.space, geometry)

    def __getattr__(self, name):
        return getattr(self.bridge, name)

    def suggest(self, trial):
        requested, params = self.bridge.suggest(trial)
        proposal = trial.user_attrs
        trial.set_user_attr("qms_proposal_candidate_id", proposal.get("qms_candidate_id"))
        trial.set_user_attr("qms_proposal_effective", deepcopy(proposal.get("qms_effective")))
        if "qms_latent" in proposal:
            trial.set_user_attr("qms_proposal_latent", deepcopy(proposal["qms_latent"]))
        try:
            point = self.geometry.resolve(params)
        except ValueError as error:
            trial.set_user_attr("qms_rejection_reason", "EFFECTIVE_GEOMETRY_REJECTED")
            trial.set_user_attr("mode5_geometry_error", str(error))
            trial.set_user_attr("qms_effective", {})
            trial.set_user_attr("qms_candidate_id", None)
            trial.set_user_attr("qms_effective_active_mask", None)
            raise optuna.TrialPruned("EFFECTIVE_GEOMETRY_REJECTED") from error
        trial.set_user_attr("qms_effective", point.params)
        trial.set_user_attr("qms_candidate_id", self.space.candidate_key(
            point.params, strategy_identity=self.bridge.strategy_identity))
        trial.set_user_attr("qms_effective_active_mask", {s.name: s.name in point.params for s in self.geometry.specs})
        trial.set_user_attr("mode5_effective_geometry_identity", self.geometry.identity)
        trial.set_user_attr("mode5_effective_point_identity", point.identity)
        return requested, point.params

    def metadata(self, study):
        metadata = self.bridge.metadata(study)
        trials = {trial.number: trial for trial in study.get_trials(deepcopy=False)}
        for row in metadata["rows"]:
            attrs = trials[row["trial_id"]].user_attrs
            row.update(proposal_candidate_id=attrs.get("qms_proposal_candidate_id"),
                proposal_effective_params=attrs.get("qms_proposal_effective"),
                proposal_latent=attrs.get("qms_proposal_latent"),
                effective_active_mask=attrs.get("qms_effective_active_mask"))
        return {**metadata, "effective_geometry_identity": self.geometry.identity,
            "constraint_policy": "reject_no_silent_sort", "rng_draws_added_by_geometry": 0}


class PublicContinuousMode5Runtime(PublicMode5Runtime):
    """Same optimizer and selectors; execution is once over all development."""

    def __init__(self, engine, calibration, data, index, param_ranges):
        if not isinstance(calibration, ContinuousMode5Calibration):
            raise TypeError("explicit continuous calibration required")
        super().__init__(engine, calibration, data, index, param_ranges)
        self.scope = ContinuousAccountScope.from_contract(calibration.continuous_contract, index)
        self.policy = engine.scorer.mode5_metric_policy
        if not isinstance(self.policy, ContinuousMode5MetricPolicy):
            raise TypeError("original scorer must bind continuous observation retention")
        self.policy.bind_producer(engine.scorer, engine.strategy)
        self.metadata.update(schema="quantbt.mode5.public_run.continuous.v1",
            environment_account_policy="CONTINUOUS_PATH_ATTRIBUTION", annual_account_resets=0,
            financial_scope="one_original_scorer_account_per_effective_query",
            native_feedback_passes="original financial provider; not inferred from scorer-call count",
            account_scope=self.scope.metadata())
        self.whole_observations = {}
        self.continuous_observations = {}
        self.account_observations = {}

    def _observe_point(self, params, folds, trial_id, *, stage):
        from time import perf_counter
        from ..walkforward import _slice_output_to_test
        started = perf_counter()
        self.scope.require_full_index(self.index)
        idx = self.scope.scored_index
        fold = replace(folds[0], train_index=idx, test_index=idx,
            train_start=idx[0], train_end=idx[-1], test_start=idx[0], test_end=idx[-1],
            cutoff_timestamp=idx[-1], account_policy="carry_position")
        prefix = self.engine._prepared_data_through(self.data, idx[-1], strategy_copy=False)
        output = self.engine._call_strategy(prefix, params, fold)
        task = (_slice_output_to_test(output, idx), idx, fold, params, stage)
        with self.policy.evaluation(prefix, params, stage=stage):
            scored = self.engine._score_strategy_outputs_with_scope(self.data, [task], trial_id=trial_id,
                params=params, stage=stage, adaptive_optimizer=True, study_id=0)
        if len(scored) != 1:
            raise ValueError("one original scorer account required")
        row = scored[0]["mode5_continuous_observation"]
        observations = tuple(row["annual_views"])
        if tuple(v["environment_id"] for v in observations) != tuple(w.environment_id for w in self.calibration.windows):
            raise ValueError("continuous view roster differs from sealed selector environments")
        self.whole_observations[digest(params)] = row["whole"]
        if self.calibration.binding.data["continuous"]["quality_floor_comparison"] == "strict_greater_v1":
            floor = self.calibration.binding.data["metrics"]["min_utility"]
            observations = tuple({**v, "quality_pass": v["utility"]["value"] is not None
                and v["utility"]["value"] > floor, "quality_floor_comparison": "strict_greater_v1"}
                for v in observations)
        cid = digest(params)
        query_id = digest((stage, trial_id, cid, row["identity"]))
        self.continuous_observations[query_id] = row
        self.account_observations[query_id] = scored[0]["mode5_continuous_evaluation"]
        parent = next((r for r in reversed(self.rows) if r["trial_id"] == trial_id and r["state"] == "RUNNING"), None)
        if parent is not None:
            if stage == "mode5.local_probe":
                parent.setdefault("local_probe_observations", []).append(dict(
                    candidate_id=cid, continuous_observation_ref=query_id, observations=observations,
                    evaluation_ref=digest(observations), whole_observation=row["whole"]))
            else:
                parent.update(observations=observations, whole_observation=row["whole"],
                    continuous_observation_ref=query_id, evaluation_ref=digest(observations))
        self.evaluation_seconds += perf_counter()-started
        unsupported = tuple(dict(environment_id=v["environment_id"],
            status=v.get("metric_contract_status"), reason=v.get("null_reason"))
            for v in observations if v.get("metric_contract") is None)
        if unsupported:
            reason = "UNAVAILABLE_ANNUAL_METRIC_CONTRACT"
            if parent is not None:
                parent.update(state="PRUNED", reason=reason, scientific_reason=dict(
                    stage=stage, candidate_id=cid, unsupported_views=unsupported))
            self.observations[cid] = observations
            raise optuna.TrialPruned(reason)
        return observations

    def _reconcile_ledger(self):
        for row in self.rows:
            whole = row.get("whole_observation", self.whole_observations.get(row.get("candidate_id")))
            if whole is not None:
                values = [v["raw_sharpe"] for v in row.get("observations", ())]
                row["annual_mean_raw_sharpe"] = (sum(values)/len(values)
                    if values and all(v is not None for v in values) else None)
                row["raw_sharpe"] = row["raw_whole_sharpe"] = whole["raw_sharpe"]
            if row["state"] == "RUNNING":
                row.update(state="FAILED", reason="INTERRUPTED_BEFORE_TERMINAL_TRIAL_STATE")
        self.metadata.update(environment_account_policy="CONTINUOUS_PATH_ATTRIBUTION", annual_account_resets=0,
            raw_whole_sharpe={k: v["raw_sharpe"] for k, v in self.whole_observations.items()},
            whole_observations=dict(self.whole_observations),
            continuous_observations=dict(self.continuous_observations), trial_ledger=self.rows)

    def optimize(self, data, folds, param_ranges, **kwargs):
        original = self.engine._sampler_bridges[0]
        self.engine._sampler_bridges[0] = _GeometryBridge(original, self.calibration.continuous_contract.geometry)
        try:
            answer = super().optimize(data, folds, param_ranges, **kwargs)
            self._reconcile_ledger()
            selected, records, completed = answer
            by_id = {r["trial_id"]: r for r in self.rows}
            adjusted = {r.trial_id: replace(r, mean_is_sharpe=by_id[r.trial_id].get("raw_sharpe"))
                        for r in records}
            selected = replace(selected, mean_is_sharpe=by_id[selected.trial_id].get("raw_sharpe"))
            self.metadata.update(environment_account_policy="CONTINUOUS_PATH_ATTRIBUTION", annual_account_resets=0,
                raw_whole_sharpe={k: v["raw_sharpe"] for k, v in self.whole_observations.items()})
            return selected, [adjusted[r.trial_id] for r in records], [adjusted[r.trial_id] for r in completed]
        except BaseException as error:
            error.mode5_continuous_accounts = self.detach_account_retention()
            raise
        finally:
            try:
                self._reconcile_ledger()
            finally:
                self.engine._sampler_bridges[0] = original

    def detach_account_retention(self):
        retention = ContinuousAccountRetention(tuple(self.account_observations.items()))
        self.metadata["continuous_account_retention"] = retention.metadata()
        return retention

    def close(self):
        super().close()
        self.whole_observations.clear()
        self.continuous_observations.clear()
        self.account_observations.clear()
        self.scope = None
        if self.policy is not None:
            self.policy.request = self.policy._producer = self.policy._producer_execution = None
            self.policy = None

