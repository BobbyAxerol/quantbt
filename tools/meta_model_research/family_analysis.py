"""Cold, descriptive development reduction; no IO, fitting or nomination policy.

Inputs are JSON-shaped screening/replay results. Only allowlisted aggregates
leave this boundary: model state, parameters, IDs and free text stay private.
"""

from collections import Counter
from collections.abc import Mapping
from itertools import product
import math

from quantbt.optimization.meta_selection.common import utc

from .analysis import moments
from .family_protocol import ROSTER
from .protocol import GROUPS


VERSION = "m4.ml03.development-analysis.v1"
PANELS = ("base", "union")
FOLDS = tuple(range(13, 25))
METRICS = (
    "y_mae",
    "q_mae",
    "y_spearman",
    "q_spearman",
    "y_pair_accuracy",
    "q_pair_accuracy",
    "y_calibration_slope",
    "q_calibration_slope",
    "y_calibration_intercept",
    "q_calibration_intercept",
)
ECONOMICS = ("R", "IS_effect", "Q")
REASONS = {
    "INSUFFICIENT_VARIATION_OR_COMPARABLE_PAIRS",
    "NO_SERVED_PREDICTIONS",
    "NO_VALID_LABELED_PANEL_ROWS",
    "FIT_FAILED_RETAINED",
    "NOT_REPORTED",
}
NOMINATION_REASONS = {
    "FAMILY_CALIBRATION_ORIGIN_SUPPORT_INSUFFICIENT",
    "FAMILY_CALIBRATION_COMPLETE_BLOCKS_INSUFFICIENT",
    "SUPPORTED_GROUP_CHRONOLOGICAL_DEVELOPMENT_SCREEN",
}


def _error(reason):
    raise ValueError("MLR03_ANALYSIS_" + reason)


def _json_finite(value, depth=0):
    if depth > 32:
        _error("INPUT_DEPTH_INVALID")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                _error("INPUT_MAPPING_INVALID")
            _json_finite(child, depth + 1)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _json_finite(child, depth + 1)
    elif type(value) in (int, float):
        if not math.isfinite(value):
            _error("NONFINITE")
    elif value is not None and type(value) not in (str, bool):
        _error("INPUT_NOT_JSON")


def _number(value, *, nonnegative=False):
    if value is not None and (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or (nonnegative and value < 0)
    ):
        _error("METRIC_INVALID")
    return value


def _stats(values):
    values = tuple(values)
    result = moments(_number(v) for v in values)
    return dict(result, missing=len(values) - result["n"])


def _mapping(row, key):
    value = row.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _error("ROW_MAPPING_INVALID")
    return value


def _validate_row(row):
    if "loss" not in row or not isinstance(row.get("status"), str):
        _error("ROW_FIELDS_INVALID")
    loss = _number(row["loss"], nonnegative=True)
    served = _mapping(row, "served_metrics")
    training = _mapping(row, "training")
    for key in METRICS + ("y_mse", "q_mse"):
        _number(
            served.get(key), nonnegative=key in ("y_mae", "q_mae", "y_mse", "q_mse")
        )
    for key in ("served_y_mse", "train_origin_macro_mse"):
        _number(training.get(key), nonnegative=True)
    if "y_mse" in served and served["y_mse"] != loss:
        _error("LOSS_BINDING_INVALID")
    if (
        served.get("q_mse") is not None
        and loss is not None
        and not math.isclose(served["q_mse"], loss, rel_tol=1e-12, abs_tol=1e-12)
    ):
        _error("Y_Q_LOSS_IDENTITY_INVALID")
    _mapping(row, "null_reasons")
    _mapping(row, "metric_null_reasons")
    if row["status"] == "FIT_FAILED_RETAINED" and (
        loss is not None
        or any(v is not None for v in served.values())
        or any(
            training.get(k) is not None
            for k in ("served_y_mse", "train_origin_macro_mse")
        )
    ):
        _error("FAILED_ROW_HAS_METRICS")
    for key in ("snapshot_id", "anchor", "winner"):
        if key in row and (not isinstance(row[key], str) or not row[key].strip()):
            _error("IDENTITY_INVALID")
    stamps = {
        k: utc(row[k])
        for k in ("cutoff", "label_available_at", "revision_available_at")
        if k in row
    }
    if (
        "label_available_at" in stamps
        and "revision_available_at" in stamps
        and stamps["revision_available_at"] < stamps["label_available_at"]
    ):
        _error("LABEL_REVISION_CLOCK_INVALID")
    economics = _mapping(row, "economics")
    values = [_number(economics.get(k)) for k in ECONOMICS]
    if any(v is not None for v in values):
        if any(v is None for v in values):
            _error("PARTIAL_ECONOMIC_COORDINATES")
        if not math.isclose(
            values[0], values[1] + values[2], rel_tol=1e-12, abs_tol=1e-12
        ):
            _error("R_IS_Q_IDENTITY_INVALID")
        if economics.get("winner_witness_exists") is not True:
            _error("ECONOMIC_WITNESS_INVALID")
    if (
        "winner_witness_exists" in economics
        and type(economics["winner_witness_exists"]) is not bool
    ):
        _error("ECONOMIC_WITNESS_INVALID")


def _index(result, *, baseline=False):
    schema = "m4.ml02.fixed-pool-replay.v1" if baseline else "m4.ml03.finite-screen.v1"
    if not isinstance(result, Mapping) or result.get("schema") != schema:
        _error("SOURCE_VERSION_INVALID")
    _json_finite(result)
    rows = result.get("rows")
    if not isinstance(rows, (list, tuple)):
        _error("ROWS_INVALID")
    indexed = {}
    for row in rows:
        if not isinstance(row, Mapping):
            _error("ROW_INVALID")
        if baseline and (row.get("policy") != "P0" or row.get("fold") not in FOLDS):
            continue
        key = (row.get("panel"), row.get("group"), row.get("fold"))
        if (
            type(key[2]) is not int
            or key[0] not in PANELS
            or key[1] not in GROUPS
            or key[2] not in FOLDS
        ):
            _error("ROSTER_KEY_INVALID")
        if not baseline:
            if row.get("code") not in ROSTER:
                _error("ROSTER_CODE_INVALID")
            key += (row["code"],)
        if key in indexed:
            _error("DUPLICATE_KEY")
        _validate_row(row)
        indexed[key] = row
    expected = set(product(PANELS, GROUPS, FOLDS))
    if not baseline:
        expected = {key + (code,) for key in expected for code in ROSTER}
    if set(indexed) != expected:
        _error("INCOMPLETE_ROSTER")
    return indexed


def _match(row, base):
    checked = 0
    failed = row["status"] == "FIT_FAILED_RETAINED"
    for key in (
        "snapshot_id",
        "anchor",
        "cutoff",
        "label_available_at",
        "revision_available_at",
    ):
        if key not in row and failed:
            continue
        if key not in row and key not in base:
            continue
        if key not in row or key not in base:
            _error("MATCHED_BINDING_MISSING")
        a, b = row[key], base[key]
        if key.endswith("_at") or key == "cutoff":
            a, b = utc(a), utc(b)
        if a != b:
            _error("MATCHED_BINDING_MISMATCH")
        checked += 1
    return checked


def _train_loss(row):
    training = _mapping(row, "training")
    return training.get("served_y_mse", training.get("train_origin_macro_mse"))


def _metric_cell(rows):
    cell = dict(
        calendar_origins=len(rows),
        failed_fits=sum(r["status"] == "FIT_FAILED_RETAINED" for r in rows),
        train_served_loss=_stats(_train_loss(r) for r in rows),
        served_loss=_stats(r["loss"] for r in rows),
    )
    for metric in METRICS:
        cell[metric] = _stats(_mapping(r, "served_metrics").get(metric) for r in rows)
    cell["origin_macro_rmse"] = (
        math.sqrt(cell["served_loss"]["mean"])
        if cell["served_loss"]["mean"] is not None
        else None
    )
    nulls = {}
    for metric in ("y_mse",) + METRICS:
        counts = Counter()
        for row in rows:
            value = (
                row["loss"]
                if metric == "y_mse"
                else _mapping(row, "served_metrics").get(metric)
            )
            if value is None:
                reasons = _mapping(row, "null_reasons") or _mapping(
                    row, "metric_null_reasons"
                )
                reason = reasons.get(
                    metric,
                    "FIT_FAILED_RETAINED"
                    if row["status"] == "FIT_FAILED_RETAINED"
                    else "NOT_REPORTED",
                )
                counts[
                    reason
                    if isinstance(reason, str) and reason in REASONS
                    else "OTHER_PRIVATE_REASON"
                ] += 1
        nulls[metric] = dict(sorted(counts.items()))
    cell["null_reason_counts"] = nulls
    for metric in ECONOMICS:
        cell[metric + "_vs_native"] = _stats(
            _mapping(r, "economics").get(metric) for r in rows
        )
    return cell


def _paired(rows, baseline):
    values = {
        key: []
        for key in (
            "delta_mse",
            "matched_current_mse",
            "matched_P0_mse",
            "relative_mse_change_percent",
            "delta_R",
            "delta_IS_effect",
            "delta_Q",
        )
    }
    counts = Counter(
        dict(
            compared_winner=0,
            changed_winner=0,
            known_new_winner=0,
            missing_new_winner=0,
            undefined_new_winner=0,
            uncompared_winner=0,
            unknown_new_winner_witness=0,
        )
    )
    bindings = 0
    for row, base in zip(rows, baseline):
        bindings += _match(row, base)
        paired = row["loss"] is not None and base["loss"] is not None
        a, b = (row["loss"], base["loss"]) if paired else (None, None)
        values["matched_current_mse"].append(a)
        values["matched_P0_mse"].append(b)
        values["delta_mse"].append(a - b if paired else None)
        values["relative_mse_change_percent"].append(
            100 * (a - b) / b if paired and b > 0 else None
        )
        for metric in ECONOMICS:
            a, b = (_mapping(r, "economics").get(metric) for r in (row, base))
            values["delta_" + metric].append(
                a - b if a is not None and b is not None else None
            )
        if "winner" not in row or "winner" not in base:
            counts["uncompared_winner"] += 1
        else:
            counts["compared_winner"] += 1
            if row["winner"] != base["winner"]:
                counts["changed_winner"] += 1
                economics = _mapping(row, "economics")
                witness = economics.get("winner_witness_exists")
                if witness is False:
                    counts["missing_new_winner"] += 1
                elif witness is None:
                    counts["unknown_new_winner_witness"] += 1
                elif economics.get("Q") is None:
                    counts["undefined_new_winner"] += 1
                else:
                    counts["known_new_winner"] += 1
    result = {key: _stats(items) for key, items in values.items()}
    current, base = (
        result[key]["mean"] for key in ("matched_current_mse", "matched_P0_mse")
    )
    result["relative_mse_change_percent_from_matched_means"] = (
        100 * (current - base) / base if base is not None and base > 0 else None
    )
    result["winner_counts"] = dict(counts)
    result["matched_identity_checks"] = bindings
    return result


def _macro_stats(stats):
    result = _stats(s["mean"] for s in stats)
    # Do not silently redefine the registered four-group macro when a group is absent.
    if result["missing"]:
        result["mean"] = result["median"] = None
    return result


def _macro(cells):
    keys = (
        ("train_served_loss", "served_loss")
        + METRICS
        + tuple(k + "_vs_native" for k in ECONOMICS)
    )
    result = {key: _macro_stats(c[key] for c in cells) for key in keys}
    result["origin_macro_rmse"] = (
        math.sqrt(result["served_loss"]["mean"])
        if result["served_loss"]["mean"] is not None
        else None
    )
    result["calendar_origins"] = sum(c["calendar_origins"] for c in cells)
    result["failed_fits"] = sum(c["failed_fits"] for c in cells)
    result["supported_loss_origins"] = {
        g: c["served_loss"]["n"] for g, c in zip(GROUPS, cells)
    }
    paired = [c["paired_vs_P0"] for c in cells]
    result["paired_vs_P0"] = {
        key: _macro_stats(c[key] for c in paired)
        for key in (
            "delta_mse",
            "matched_current_mse",
            "matched_P0_mse",
            "relative_mse_change_percent",
            "delta_R",
            "delta_IS_effect",
            "delta_Q",
        )
    }
    current, base = (
        result["paired_vs_P0"][key]["mean"]
        for key in ("matched_current_mse", "matched_P0_mse")
    )
    result["paired_vs_P0"]["relative_mse_change_percent_from_matched_means"] = (
        100 * (current - base) / base
        if current is not None and base is not None and base > 0
        else None
    )
    result["paired_vs_P0"]["winner_counts"] = {
        key: sum(c["winner_counts"][key] for c in paired)
        for key in paired[0]["winner_counts"]
    }
    return result


def _nominees(result, panel):
    nominations = result.get("nominees")
    if not isinstance(nominations, Mapping) or set(nominations) != set(PANELS):
        _error("NOMINEES_INVALID")
    records = nominations[panel]
    if not isinstance(records, Mapping) or set(records) != set(GROUPS):
        _error("NOMINEES_INVALID")
    safe = {}
    for group in GROUPS:
        record = records[group]
        if not isinstance(record, Mapping):
            _error("NOMINEES_INVALID")
        codes = record.get("nominees")
        policy = record.get("policy")
        if (
            not isinstance(codes, (list, tuple))
            or len(codes) > 2
            or any(code not in ROSTER for code in codes)
            or len(set(codes)) != len(codes)
            or policy not in ("P0", "RESEARCH_NOMINEES")
            or (policy == "P0") != (not codes)
        ):
            _error("NOMINEES_INVALID")
        reason = record.get("reason")
        safe[group] = dict(
            policy=policy,
            nominees=list(codes),
            economic_promotion=False,
            reason=reason
            if isinstance(reason, str) and reason in NOMINATION_REASONS
            else "OTHER_PRIVATE_REASON",
        )
    return safe


def summarize_development(result, baseline_result):
    """Return sanitized origin-then-equal-group development moments.

    Requires all 480 screen cells, including null/failed cells, and all 96 P0
    development cells. A full ML-02 replay is allowed; other policies/folds are
    not comparators. Relative MSE change is (challenger-P0)/P0 * 100; zero P0
    denominators remain null. No confidence intervals or new shortlist is made.
    """
    rows = _index(result)
    baseline = _index(baseline_result, baseline=True)
    summaries = {}
    for panel in PANELS:
        cells, base_cells = {}, {}
        for group in GROUPS:
            bases = [baseline[panel, group, fold] for fold in FOLDS]
            base_cells[group] = _metric_cell(bases)
            cells[group] = {}
            for code in ROSTER:
                subset = [rows[panel, group, fold, code] for fold in FOLDS]
                cell = _metric_cell(subset)
                cell["paired_vs_P0"] = _paired(subset, bases)
                cells[group][code] = cell
        summaries[panel] = dict(
            cells=cells,
            baseline=base_cells,
            macro={code: _macro([cells[g][code] for g in GROUPS]) for code in ROSTER},
            nominees=_nominees(result, panel),
        )
    summary = dict(
        schema=VERSION,
        scope="descriptive_development_only",
        summaries=summaries,
        required_rows=480,
        baseline_P0_development_rows=96,
        nomination_source="result.nominees",
        shortlist_computed=False,
        numerical_economic_ci=False,
        economic_intervals=None,
        public_activation=False,
        economic_promotion=False,
        label_scope="known_registered_panel_and_available_winners_only",
        relative_mse_change="100*(challenger-P0)/P0; negative means lower loss",
        macro_weighting="origin_mean_then_equal_four_groups; absent_group_macro_is_null",
    )
    _json_finite(summary)
    return summary
