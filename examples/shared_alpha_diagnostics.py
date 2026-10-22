"""Synthetic pre-search diagnostics; no alpha, market loader or optimizer."""

from quantbt import AlphaDiagnostics, DiagnosticAdvice, DiagnosticContext, DiagnosticObservation
from quantbt.diagnostics import AccessPolicy, AccessWitness


def build_example_report():
    context = DiagnosticContext(alpha_id="synthetic-alpha-v1", market_id="synthetic-prefix-v1",
        economics_id="synthetic-account-v1", route_id="caller-endpoint",
        metric_units=(("quality", "synthetic_utility"), ("risk", "synthetic_risk")),
        primary_metric="quality", direction="maximize", generation_method="fixed_design_v1",
        outcome_blind_roster=True, activity_definition="synthetic_entry_count")
    access = AccessPolicy("example-prefix", ("synthetic",), ("example-tape",), 101, "diagnostic")
    diagnostics = AlphaDiagnostics({"window": (1, 12), "threshold": (0.0, 1.0)},
                                   context=context, access=access)
    rows = [DiagnosticObservation.from_params(geometry=diagnostics.geometry,
        params=dict(window=i+1, threshold=i/12),
        metrics=dict(quality=float(i), risk=-float(i)), evaluation_id=f"synthetic-{i}",
        context_id=context.identity, witness=AccessWitness("example-tape", "synthetic", 0, 100, 101),
        source_ref=f"synthetic-observation-{i}", activity_count=i) for i in range(12)]
    advice = (
        DiagnosticAdvice("sampler", "tpe_multivariate_group",
            "A compatible joint-search challenger; no superiority is inferred from dimension count.",
            ("geometry", "associations"), ("matched sampler comparison",)),
        DiagnosticAdvice("selector", "is_only_robust",
            "Keep the existing selector while local/regime support is unavailable.",
            ("coverage",), ("authorized local probes", "regime attribution")),
    )
    return diagnostics.analyze(rows, advice=advice, bootstrap_resamples=16)


if __name__ == "__main__":
    print(build_example_report().to_markdown())
