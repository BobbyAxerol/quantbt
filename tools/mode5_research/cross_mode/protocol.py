"""Concrete review packets; constructing them never authorizes execution."""

from copy import deepcopy
from datetime import datetime, timezone

from .inventory import identity


def review_packet(cells, *, snapshot_id):
    """Freeze a bounded proposal from identity-admitted cells, without outcomes."""
    if (not isinstance(snapshot_id, str) or len(snapshot_id) != 64
            or any(c not in '0123456789abcdef' for c in snapshot_id)):
        raise ValueError("verified snapshot content identity required")
    if not isinstance(cells, list) or not 1 <= len(cells) <= 2:
        raise ValueError("one or two identity-admitted cells required")
    seen = set()
    for cell in cells:
        required = {"cell_id", "source_refs", "candidate_ids", "reference_ids",
                    "mode4_origins", "static_origins", "baseline", "readiness"}
        if (not isinstance(cell, dict) or not required <= cell.keys()
                or set(cell) - required - {"references"}):
            raise ValueError("concrete roster and dependency packet required")
        name = cell['cell_id']
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("distinct explicit cell identities required")
        seen.add(name)
        for key in ('source_refs', 'candidate_ids', 'reference_ids'):
            values = cell[key]
            if (not isinstance(values, list) or not values
                    or any(not isinstance(v, str) or not v for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError("distinct nonempty source/candidate/reference lists required")
        if len(cell['candidate_ids']) != 128 or len(cell['reference_ids']) > 32:
            raise ValueError("registered128-point panel and at most32 reference candidates required")
        if any(not isinstance(cell[key], dict) or not cell[key] for key in ('baseline', 'readiness')):
            raise ValueError("concrete baseline/readiness mappings required")
        if any(not isinstance(cell[key], list) or len(cell[key]) != 3
               for key in ('mode4_origins', 'static_origins')):
            raise ValueError("three concrete cutoffs/horizons per registered cell")
        cutoffs = []
        for origin in cell['mode4_origins']:
            cutoffs.append(_stamp(origin['cutoff']))
            if not isinstance(origin.get('windows'), dict) or not origin['windows']:
                raise ValueError("Mode4 origin requires its original windows")
        if cutoffs != sorted(set(cutoffs)):
            raise ValueError("distinct ordered Mode4 cutoffs required")
        previous = None
        for origin in cell['static_origins']:
            start = _stamp(origin['forward_start'])
            stop = _stamp(origin['forward_stop_exclusive'])
            if (_stamp(origin['cutoff']) != start or (stop-start).total_seconds() != 365*86400
                    or _stamp(origin['development_start']) >= start
                    or (previous is not None and start < previous)):
                raise ValueError("three ordered nonoverlapping365-day horizons and prior development required")
            previous = stop
    packet = dict(
        schema="quantbt.cross_mode.review_packet.v1", status="PROPOSED_FOR_OWNER_REVIEW",
        private_only=True, public_export_allowed=False,
        authority="M5-11.10 cold registration only; each subsequent phase needs approval",
        source_snapshot_id=snapshot_id, cells=deepcopy(cells),
        formula=dict(id="temporal_upper_regret_research_v1", utility="net_return - MDD - daily_loss_ES95",
            units="decimal_account_return", upper_tail_mass=0.20,
            temporal_views="complete_calendar_quarters_of_one_continuous_account",
            temporal_weights="scored_calendar_days_normalized",
            quarter_min_calendar_days=60, daily_loss_tail_confidence=0.95,
            near_optimal_daily_tolerance=0.00005,
            near_optimal_rule="delta_t = 0.00005 * actual_calendar_days_t",
            stable_region_use="explanation_only_no_ranking_or_tie_change",
            tie_rule="minimum absolute score tolerance 1e-10 then recorded effective-ID order",
            reference="up to32 calendar-spaced original native anchors; dedup and deterministic refill",
            prefix_reference="regenerate from permitted native anchors then source-ID-ordered IS candidates until32 unique; never backdate the current full-scope roster",
            reference_objective_values="measure under the exact continuous account contract; never import reset labels",
            negative_regret="preserve when a candidate exceeds the frozen finite reference"),
        admission=dict(initial_capital=20000.0, max_drawdown=0.50,
            min_whole_utility=0.0, finite_whole_sharpe=True,
            annual_min_daily_returns=180, min_closed_records=0,
            annual_utility_positive_gate=False, scored_start="2020-01-01T00:00:00+00:00",
            warmup="original pre-readiness flat convention; no invented pre2020 data",
            economics="exact source-specific sizing/clock/fees/funding/terminal contract retained",
            no_selection="reproducible rejection ledger; selected-account checks not applicable"),
        selection=dict(phase="M5-11.11", optimizer_proposals=0,
            treatment="old recorded static selector versus registered temporal regret on the same128-point panel",
            reference_accounts_cap=32 * len(cells),
            selected_replay_cap=2 * len(cells),
            extra_held_fee_accounts_cap=0,
            reference_geometry="original valid dictionaries only; no centroid generation",
            missing_utility_views="cold-reduce retained original paths only after exact source/path admission; no imputation"),
        sampler=dict(phase="M5-11.12", attempts_per_study=256, seed=731,
            early_stopping=False, warm_start_scores=False,
            study_count=8 * len(cells), proposal_cap=2048 * len(cells),
            mode5_studies_per_cell=2, mode4_studies_per_cell=6,
            extra_prefix_diagnostic_accounts_cap=384 * len(cells),
            mode4_meta="off in both isolation arms; no claim for changed-history Ridge",
            control="unassisted TPE with128 startup attempts; fresh matched control, not old default10 evidence",
            treatment="same TPE settings; first64 attempts enqueue permitted archive coordinates, then unrestricted TPE",
            global_exploration="at least64 random full-domain startup proposals remain after64 seed attempts",
            no_64_seeds="dedup/refill from permitted archive by fixed calendar/effective-ID order; if exhausted report prerequisite failure",
            historical_legacy="old default TPE retained as context only; do not call it the matched startup128 control",
            refresh="once at each study cutoff; no within-study outcome-driven archive refresh",
            fallback="unsupported geometry or inadmissible prior rejects the comparison cell; no silent alternative sampler",
            cost_scope="proposal cap excludes separately enumerated actual/reference/prefix accounts; all counted in financial work ledger"),
        chronology=dict(phase="M5-11.13", attempts_per_study=256, seed=731,
            procedure_count=2, origins_per_cell=3, prefix_proposal_cap=1536 * len(cells),
            extra_prefix_diagnostic_accounts_cap=384 * len(cells),
            forward_account_cap=6 * len(cells),
            forward_reference_account_cap=96 * len(cells),
            fixed_forward_days=365, independent_oos=False,
            comparison="old static procedure versus one frozen combined procedure; no interaction-effect claim",
            reference_clocks="membership/rule frozen before deployment; forward values measured after horizon for assessment only",
            reverse_direction_claim="three-cutoff sampler screen and prefix isolation only, not full rolling deployment"),
        inference=dict(confidence=0.95, bootstrap_draws=16384, seed=731,
            paired_calendar_block_months=3,
            primary_family="one regret and one absolute-quality contrast per admitted alpha",
            family_adjustment="Bonferroni simultaneous percentile intervals, actual declared contrast count",
            primary_effect="challenger minus baseline upper-tail regret; lower is better",
            primary_gate="upper simultaneous CI of delta_regret below0 AND lower CI of delta_mean_net_daily_return at least-0.00005",
            daily_quality_noninferiority_margin=0.00005,
            risk_gate="original DD<=50% mandate; report all DD changes and magnitudes",
            min_paired_return_days=365, min_complete_three_month_blocks=4,
            min_origin_count=3, min_expected_draws_per_ci_tail=10,
            alpha_weighting="equal alpha cell, then declared calendar weights; no pooled raw candidate labels",
            dependence="same sampled market-date blocks across arms/alphas; fixed-path intervals do not estimate search variance",
            insufficient_support="INCONCLUSIVE; no expanded seeds/ranges or outcome-driven gate revision"),
        rights=dict(mode5_to_mode4="whole dependency graph must be prefix-admitted; full-development dossiers forbidden",
            old_oos_new_selection="development for the new choice; old original role retained",
            held_evidence="assessment only; no reselection without a separate role amendment",
            publication="strictly before cutoff in the default historical policy",
            candidate_birth="record simulated discovery separately from wall generation; never backdate full-scope candidates"),
        resources=dict(cold_rss_bytes=512 * 1024**2, financial_aggregate_rss_bytes=2 * 1024**3,
            available_ram_floor_bytes=512 * 1024**2, workers=2, numeric_threads_per_study=1,
            series_retained_bytes=1024**3, disk_reserve_bytes=5 * 1024**3,
            wall_cap_seconds=8 * 3600, cpu_cap_seconds=16 * 3600,
            cap_semantics="proposed upper safety ceilings, not ETA; measured controls/audit peaks must admit each lane",
            new_control_financial_cap=4 * len(cells),
            finance_launch="only after phase approval, measured shared-resource admission and exact work/source seal"),
        production_adoption=False, automatic_next_phase=False, release=False,
    )
    packet["packet_id"] = identity(packet)
    return packet


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError("explicit timezone-aware timestamp required")
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError("timezone-aware protocol calendar required")
    return result.astimezone(timezone.utc)
