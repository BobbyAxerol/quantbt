"""Sealed public bindings: scientific contracts are not mutable callbacks."""
from dataclasses import asdict, dataclass
import math

from .diagnostics.access import AccessPolicy, AccessWitness
from .diagnostics.identity import digest
from .dossier.dossier import Dossier
from .dossier.plans import CalibrationPlan
from .dossier.records import Record
from .statistics.tails import FrozenReference
from ..optimization.config import SamplerConfig
from ..optimization.parameter_space import NormalizedSearchSpace


@dataclass(frozen=True)
class CalibrationWindow:
    environment_id: str
    start_ns: int
    end_ns: int
    witness: AccessWitness

    def __post_init__(self):
        if (not self.environment_id or type(self.start_ns) is not int
                or type(self.end_ns) is not int or self.start_ns >= self.end_ns
                or not isinstance(self.witness, AccessWitness)
                or self.witness.start_ns > self.start_ns or self.witness.end_ns < self.end_ns):
            raise ValueError("bounded environment and complete availability witness required")


def calibration_context(*, data, strategy, execution_config, param_ranges, binding):
    """Cold-path identities shared by dossier construction and public preflight.

    This does not profile an alpha or choose a recipe. Existing diagnostic
    artifacts must still substantiate the resulting context.
    """
    from ..walkforward import _complete_data_hash
    from ..core.wfo_contracts import strategy_fingerprint
    from ..optimization.meta_selection.observer import economics_identity
    market_id = digest((_complete_data_hash(data), _complete_data_hash(execution_config.funding_rate)))
    return Record.of(dict(alpha=strategy_fingerprint(strategy), data=market_id,
        economics=economics_identity(execution_config),
        schema=NormalizedSearchSpace(param_ranges).identity,
        roles=digest(binding.data["windows"]), metrics=digest(binding.data["metrics"]),
        references=binding.data["reference"]["reference_id"], scope=binding.identity))


def calibration_binding(*, windows, reference, sampler, metrics, selection,
                        batch_size=1, local_offsets=(), warm_start=()):
    """Freeze explicit runtime inputs before the CalibrationPlan seal."""
    if not isinstance(reference, FrozenReference) or not isinstance(sampler, SamplerConfig):
        raise TypeError("typed frozen reference and shared SamplerConfig required")
    return Record.of(dict(schema="quantbt.mode5.public_binding.v1",
        windows=[asdict(w) for w in windows], reference=asdict(reference),
        sampler=sampler.metadata(), metrics=metrics, selection=selection,
        batch_size=batch_size, local_offsets=list(local_offsets), warm_start=list(warm_start)))


@dataclass(frozen=True)
class Mode5Calibration:
    dossier: Dossier
    plan: CalibrationPlan
    catalog: object
    journal: object
    binding: Record

    def __post_init__(self):
        if not isinstance(self.dossier, Dossier) or not isinstance(self.plan, CalibrationPlan):
            raise TypeError("verified Dossier and CalibrationPlan required")
        if not isinstance(self.binding, Record):
            raise TypeError("immutable public binding required")
        self.plan.verify(self.dossier)
        if self.plan.record.data["status"] != "RESEARCHER_CHOICE":
            raise PermissionError("DEFER_CALIBRATION cannot authorize public search")
        if self.plan.record.data["recipe"]["retention"].get("runtime_binding_identity") != self.binding.identity:
            raise ValueError("runtime binding must be included in the sealed plan")
        self.validate_binding()

    @property
    def identity(self):
        return digest((self.dossier.record.identity, self.plan.record.identity, self.binding.identity))

    @property
    def windows(self):
        return tuple(CalibrationWindow(**{**w, "witness": AccessWitness(**w["witness"])})
                     for w in self.binding.data["windows"])

    @property
    def access(self):
        p = self.plan.record.data["recipe"]["reuse"]["selection_policy"]
        return AccessPolicy(**{**p, "roles": tuple(p["roles"]), "manifests": tuple(p["manifests"])})

    @property
    def reference(self):
        return FrozenReference(**self.binding.data["reference"])

    def validate_binding(self):
        b = self.binding.data
        if set(b) != {"schema", "windows", "reference", "sampler", "metrics", "selection", "batch_size", "local_offsets", "warm_start"}:
            raise ValueError("complete versioned binding fields required")
        if b["schema"] != "quantbt.mode5.public_binding.v1":
            raise ValueError("unsupported Mode5 binding schema")
        if tuple(w.environment_id for w in self.windows) != self.reference.environment_ids:
            raise ValueError("environment roster must exactly match frozen reference")
        for w in self.windows:
            self.access.require(w.witness)
        m = b["metrics"]
        if set(m) != {"bar_interval_ns", "currency", "annual_periods", "dd_weight", "tail_weight",
                      "tail_confidence", "min_daily_returns", "min_closed_records", "max_drawdown", "min_utility"}:
            raise ValueError("explicit metric/support/risk contract required")
        if type(m["bar_interval_ns"]) is not int or m["bar_interval_ns"] <= 0 or not m["currency"]:
            raise ValueError("explicit bar clock and currency required")
        if 86_400_000_000_000 % m["bar_interval_ns"]:
            raise NotImplementedError("daily observation coverage requires an exact divisor of a UTC day")
        for name in ("annual_periods", "dd_weight", "tail_weight", "tail_confidence", "max_drawdown", "min_utility"):
            if isinstance(m[name], bool) or not math.isfinite(m[name]):
                raise ValueError("finite metric/risk preferences required")
        if m["annual_periods"] <= 0 or min(m["dd_weight"], m["tail_weight"], m["max_drawdown"]) < 0 or not 0 <= m["tail_confidence"] < 1:
            raise ValueError("invalid metric/risk preferences")
        if any(type(m[n]) is not int or m[n] < 0 for n in ("min_daily_returns", "min_closed_records")):
            raise ValueError("nonnegative support counts required")
        recipe = self.plan.record.data["recipe"]
        if recipe["sampler"]["name"] != b["sampler"]["name"]:
            raise ValueError("sampler differs from sealed recipe")
        if len(recipe["sampler"]["seeds"]) != 1:
            raise NotImplementedError("one public study per seal; multi-seed experiments require separate plans")
        if (type(b["batch_size"]) is not int or b["batch_size"] < 1
                or (recipe["sampler"]["schedule"] == "sequential_exact" and b["batch_size"] != 1)
                or (recipe["sampler"]["schedule"] == "fixed_batch" and b["batch_size"] < 2)):
            raise ValueError("batch size differs from declared optimizer schedule")
        s = b["selection"]
        if set(s) != {"requested_selector", "minimum_improvement", "incumbent_params", "local_reference_id",
                      "local_reference_scale", "pareto_preference"}:
            raise ValueError("explicit selector/incumbent/local/preferences fields required")
        if s["requested_selector"] not in {recipe["selector"]["id"], "full_alpha_adaptive_invariant"}:
            raise ValueError("requested selector differs from explicit researcher choice")
        offsets = b["local_offsets"]
        if (len({o["probe_id"] for o in offsets}) != len(offsets)
                or any(set(o) != {"probe_id", "delta"} or not o["delta"] for o in offsets)):
            raise ValueError("distinct explicit local probes required")
        if recipe["probes"]["budget"] != len(offsets) * self.plan.record.data["search_budget"]:
            raise ValueError("local probe budget must cover each registered candidate")

    def preflight(self, engine, data, index, param_ranges):
        cfg = engine.config
        if (cfg.optimization_mode != "mode_5_full_robust" or cfg.optimization_schedule != "global"
                or cfg.scoring_backend != "endpoint" or cfg.meta_selection is not None):
            raise NotImplementedError("Mode5 diagnostics-first requires Mode5/global/endpoint; not Mode4 meta")
        if cfg.optuna_trials != self.plan.record.data["search_budget"] or cfg.optuna_early_stopping is not None:
            raise ValueError("public trial budget/stop policy differs from sealed plan")
        if cfg.parameter_constraints is not None or cfg.result_constraints is not None:
            raise NotImplementedError("unsealed mutable constraint callbacks are not accepted")
        if cfg.random_seed != self.plan.record.data["recipe"]["sampler"]["seeds"][0]:
            raise ValueError("resolved seed differs from sealed plan")
        if digest(cfg.sampler_warm_start) != digest(self.binding.data["warm_start"]):
            raise ValueError("warm-start coordinates/rights differ from sealed binding")
        if cfg.metadata.get("mode5_workers", 1) != 1:
            raise NotImplementedError("public Mode5 Python callback evaluation currently requires one worker")
        if cfg.sampler_config is None or cfg.sampler_config.metadata() != self.binding.data["sampler"]:
            raise ValueError("actual sampler configuration differs from sealed binding")
        scorer = engine.scorer
        if not hasattr(scorer, "mode5_metric_policy") or scorer.mode5_metric_policy is None:
            raise NotImplementedError("original endpoint result/retention witness required; arbitrary scalar scorer is unsupported")
        context = calibration_context(data=data, strategy=engine.strategy, execution_config=scorer.score_config,
                                      param_ranges=param_ranges, binding=self.binding)
        if context != Record.of(self.dossier.record.data["context"]):
            raise ValueError("stale dossier alpha/data/economics/schema/roles/metrics/reference/scope")
        space = NormalizedSearchSpace(param_ranges)
        sealed = self.plan.record.data["recipe"]["domain"]["ranges"]
        # Canonical JSON sorts map keys; declared dimension order is already
        # bound by the dossier's normalized schema identity, not JSON key order.
        ordered = {s.name: sealed[s.name] for s in space.specs if s.name in sealed}
        if set(param_ranges) != set(sealed) or space.identity != NormalizedSearchSpace(ordered).identity:
            raise ValueError("formal domain differs from sealed search ranges")
        step = self.binding.data["metrics"]["bar_interval_ns"]
        for w in self.windows:
            selected = index[(index.asi8 >= w.start_ns) & (index.asi8 <= w.end_ns)]
            if (not len(selected) or int(selected[0].value) != w.start_ns or int(selected[-1].value) != w.end_ns
                    or any(selected.asi8[1:] - selected.asi8[:-1] != step)):
                raise ValueError("environment clock/gaps differ from sealed exact scope")
        self.catalog.verify_current()
        self.dossier.verify(self.catalog)
        self.plan.verify(self.dossier)


def mode5_capabilities():
    return dict(schema="quantbt.mode5.capabilities.v1", opt_in="optimization_config.mode5_calibration",
        mode="mode_5_full_robust", schedule="global", scoring="original_endpoint_result",
        selectors=["full_dro_cvar", "full_sam_basin", "full_pareto_chebyshev", "full_alpha_adaptive_invariant"],
        sampler_registry="quantbt.optimization.samplers", meta_learning_activated=False,
        data_role="allowed_development_only", validation_claim="none_full_sample_calibration",
        legacy_behavior_changed=False, deployment_authorized=False)
