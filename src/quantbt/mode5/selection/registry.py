"""Machine-readable version/semantics inventory, separate from calibration recipes."""
from quantbt.mode5.diagnostics.identity import digest
from .contracts import FORMULAS


def formula_registry():
    definitions = {
        "environment_floor_mean_v1": "min(v) + mean_coefficient * weighted_mean(v) - activity_penalty",
        "legacy_floor_mean_regret_v1": "min(v) - mean_coefficient * weighted_mean(benchmark-v) - activity_penalty",
        "legacy_spec_1_1_quantile": "floor_coefficient * min(v) + tail_coefficient * linear_quantile(v,alpha) - dispersion_coefficient * unweighted_midpoint_MAD(v) - activity_penalty",
        "environment_lower_tail_v2": "floor_coefficient * min(v) + tail_coefficient * lower_probability_mass_mean(v,alpha) - dispersion_coefficient * weighted_lower_tie_MAD(v) - activity_penalty",
        "finite_panel_minimax_regret_v1": "-max(benchmark-economic_utility) - activity_penalty",
        "local_downside_v1": "weighted_mean(center) - gamma * max(0,weighted_mean(center)-min(probe_aggregates)) - activity_penalty",
        "unified_same_channel_v1": "floor_coefficient * min(v) + mean_coefficient * weighted_mean(v) - dispersion_coefficient * population_weighted_SD(v) - fragility_coefficient * local_downside - activity_penalty",
        "pareto_chebyshev_v1": "-max(weight * frozen_normalized_gap) - rho * sum(weight * frozen_normalized_gap) - activity_penalty",
    }
    rows = {version: dict(family=family, required_coefficients=coefficients, definition=definitions[version])
            for version, (family, coefficients) in FORMULAS.items()}
    body = dict(schema="mode5.formulas.v1", formulas=rows,
        units="all scalar components and penalties have the explicitly selected channel unit",
        null_policy="retain incomplete/failed rows; no favorable default or silent environment drop",
        tie_policy="candidate_id_lexicographic_v1", references="frozen per stage; full-panel revision for changes",
        local_scope="schema union optional covariance; finite observed probes, not a global robust ball",
        pareto_scope="post-selection on actual generation; no NSGA-II generation or hypervolume claim",
        public_activation=False)
    return dict(body, identity=digest(body))
