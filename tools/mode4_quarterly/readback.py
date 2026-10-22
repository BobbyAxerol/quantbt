"""Cold fixed-control readback; no optimizer, simulation or economic claims."""

from collections import defaultdict
from hashlib import sha256
import json
from statistics import mean, median

from .admission import ControlTiming, forecast


def summarize_alpha_controls(rows, *, native_sha256):
    """Check a complete eight-control early/late x low/high x repeat tranche.

    Only a fixed allowlist is exported. Source parameters, raw prices, account
    outcomes and metric values do not enter this timing report. Observed maxima
    provide a conservative admission scenario, not a future timing bound.
    """
    rows = tuple(rows)
    if (len(rows) != 8 or len({row.get("alpha") for row in rows}) != 1
            or len(native_sha256) != 64 or any(c not in "0123456789abcdef" for c in native_sha256)):
        raise ValueError("one complete alpha control tranche and artifact digest required")
    expected = {(activity, stop, repeat) for activity in ("low", "high")
                for stop in ("2022-01-01", "2026-01-01") for repeat in (0,1)}
    actual = {(row.get("activity"),row.get("stop"),row.get("repeat")) for row in rows}
    if actual != expected:
        raise ValueError("missing/duplicated fixed control strata")
    timings, grouped = [], defaultdict(list)
    for row in rows:
        if (row.get("status") != "PASS_FIXED_CONTROL_TIMING_NOT_FULL_STUDY"
                or row.get("role") != "is" or row.get("no_optimizer") is not True
                or row.get("scored_bars") != 8760 or row.get("scored_days") != 365):
            raise ValueError("successful exact 365D fixed timing controls required")
        identity = sha256(json.dumps(dict(native=native_sha256,
            source=row.get("research_source"),market=row.get("market"),
            source_params=row.get("original_params_source"),stop=row["stop"]),
            sort_keys=True).encode()).hexdigest()
        timings.append(ControlTiming(row["alpha"], "is", row["elapsed_seconds"],
            row["peak_rss_mib"], row.get("includes_preparation"), identity))
        grouped[(row["activity"],row["stop"])].append(row["elapsed_seconds"])
    durations = [row.elapsed_seconds for row in timings]
    groups = [dict(activity=key[0],stop=key[1],repeats=len(values),
        minimum_seconds=min(values),median_seconds=median(values),maximum_seconds=max(values))
        for key,values in sorted(grouped.items())]
    partial = forecast(timings)
    attempts = 19 * 128 * (1 if timings[0].alpha == "A-RSI" else 2)
    return dict(schema="mode4.quarterly.fixed-control-readback.v1",
        alpha=timings[0].alpha, control_count=8, groups=groups,
        measured=dict(minimum_seconds=min(durations),median_seconds=median(durations),
            mean_seconds=mean(durations),maximum_seconds=max(durations),
            maximum_process_peak_rss_mib=max(row.peak_rss_mib for row in timings)),
        whole_work_admission=partial,
        median_search_sensitivity_seconds=attempts*median(durations)/4,
        status=partial["status"], optimizer_calls=0, meta_fits=0,
        scientific_result="NOT_RUN_NO_QUARTERLY_R_OR_Q",
        recommendation="KEEP_DEFAULT_UNTIL_MATCHED_RESEARCH_IS_ADMITTED",
        phase_complete=False, proof_scope="FIXED_CONTROL_TIMING_NOT_ECONOMIC_OR_ENGINE_PARITY")
