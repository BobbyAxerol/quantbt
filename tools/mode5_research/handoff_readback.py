"""Bounded retained-evidence readback, not archive admission or execution authority.

``readback`` takes an explicit repository root. Only the eight declared metadata
files are opened; nested receipt paths, private code and account files are never
followed. References address decoded JSON, while their hashes pin stored bytes.
"""

import gzip
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import stat
from types import MappingProxyType

from quantbt.mode5.dossier.records import Record

from .cross_mode.disposition import restore_no_finance_handoff


SCHEMA = "quantbt.mode5.handoff_readback.v1"
BASE = "upgrade/private/mode5_upgrade_v1/"
MIB = 1024**2
# Each tuple is (repository-relative path, stored-byte cap, decoded-byte cap).
SOURCES = MappingProxyType({
    "c05": (BASE + "m5-11-9/attempt-01/C05/report.json.gz", MIB // 2, 4 * MIB),
    "formal": (BASE + "m5-11-9/attempt-01/continuation-20261021/formal-cold-readback.json",
               MIB // 8, MIB // 8),
    "c06": (BASE + "m5-11-9/attempt-01/C06/complete.json", MIB // 16, MIB // 16),
    "inventory": (BASE + "m5-11-10/attempt-03/inventory-summary.json", 2 * MIB, 2 * MIB),
    "disposition": (BASE + "m5-11-13/attempt-01/handoff-v2.json", MIB // 16, MIB // 16),
    "assistance_final": (BASE + "m5-11-12/attempt-01/final-qualification.json", MIB // 16, MIB // 16),
    "assistance_work": (BASE + "m5-11-12/attempt-01/actual-work-ledger.json", MIB // 16, MIB // 16),
    "assistance": (BASE + "m5-11-12/attempt-01/readback-16-1792539179546444213.json.gz",
                   MIB // 2, 2 * MIB),
})
MAX_STORED_BYTES = 4 * MIB
MAX_DECODED_BYTES = 10 * MIB
MAX_RECORD_BYTES = 8 * MIB
MAX_LIMITS = 32
ALPHAS = ("A-RSI", "A-SC", "A-HMA", "A-HASH", "A-VWAP", "N1", "N2")
ARMS = ("raw-tpe", "recipe-tpe", "recipe-challenger")
FORMULA_UNITS = MappingProxyType({
    "raw_whole_daily_sharpe": "retained_sharpe",
    "environment_floor_mean_v1": "decimal_return",
    "environment_lower_tail_v2": "decimal_return",
    "pareto_chebyshev_v1": "reference_normalized_utility",
})
LIMITS = (
    "Retained full-development descriptive evidence; no independent validation or deployment authority.",
    "Source hashes identify bytes, not scientific truth, current archive rights or historical availability.",
    "Only the eight metadata sources are verified; their nested account/source receipt pins are not followed.",
    "An archive is optional; its absence does not invalidate the separate Mode 5 context or recipe path.",
    "Annual views and overlapping states are not independent replications; partial years remain partial.",
    "Finite held observations do not certify a basin; legacy missing ledgers are not zero.",
    "Historical upstream blockers remain historical; final C05/C06 do not rewrite old receipts.",
    "Static utility/regret and monthly Sharpe R/Q do not qualify the deferred whole procedure.",
)
_MISSING = object()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key in retained metadata")
        value[key] = item
    return value


def _nonfinite(_value):
    raise ValueError("nonfinite retained metadata")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        _nonfinite(value)
    return result


def _int(value):
    if len(value) > 32:
        raise ValueError("oversized JSON integer in retained metadata")
    return int(value)


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite,
                          parse_float=_float, parse_int=_int)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("invalid bounded metadata JSON") from error


def _path(*parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _typed(value, kind, where, nullable=False):
    if value is None and nullable:
        return value
    if kind == "number":
        valid = type(value) in (int, float) and math.isfinite(value)
    elif kind == "count":
        valid = type(value) is int and value >= 0
    elif kind is str:
        valid = type(value) is str and bool(value.strip())
    else:
        valid = type(value) is kind
    if not valid:
        raise ValueError("unexpected scalar/container type at " + where)
    return value


class _Document:
    def __init__(self, value, pin):
        self.value = _typed(value, dict, pin["source_id"])
        self.pin = pin

    def _at(self, pointer):
        value = self.value
        try:
            for part in pointer[1:].split("/") if pointer else ():
                part = part.replace("~1", "/").replace("~0", "~")
                value = value[int(part)] if type(value) is list else value[part]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError("missing metadata at " + self.pin["source_id"] + pointer) from error
        return value

    def get(self, pointer, kind, *, nullable=False):
        return _typed(self._at(pointer), kind, self.pin["source_id"] + pointer, nullable)

    def ref(self, pointer):
        self._at(pointer)
        return dict(source=self.pin["source_id"], pointer=pointer, sha256=self.pin["sha256"])

    def fact(self, pointer, kind, unit, *, nullable=False, expected=_MISSING, status=None):
        value = self.get(pointer, kind, nullable=nullable)
        if expected is not _MISSING and (type(value) is not type(expected) or value != expected):
            raise ValueError("unexpected retained contract at " + self.pin["source_id"] + pointer)
        return dict(value=value, unit=unit, status=status or ("UNAVAILABLE" if value is None else "OBSERVED"),
                    ref=self.ref(pointer))


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


class _Reader:
    def __init__(self, root):
        if not isinstance(root, Path):
            raise TypeError("explicit repository root Path required")
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("repository root must be a directory")
        self.stored = self.decoded = 0
        self.stamps = {}

    def load(self, source):
        relative, stored_cap, decoded_cap = SOURCES[source]
        path = self.root / relative
        current = self.root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("symlinked retained metadata is not permitted")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or path.resolve(strict=True) != path:
            raise ValueError("regular metadata inside the repository root required")
        if before.st_size > stored_cap:
            raise MemoryError("stored metadata byte cap exceeded")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise ValueError("metadata changed before read")
            stored = stream.read(stored_cap + 1)
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise ValueError("metadata changed during read")
        if len(stored) != before.st_size or _stamp(path.lstat()) != _stamp(before):
            raise ValueError("metadata replaced during read")
        self.stored += len(stored)
        if self.stored > MAX_STORED_BYTES:
            raise MemoryError("aggregate stored metadata byte cap exceeded")
        compressed = relative.endswith(".gz")
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
                raw = stream.read(decoded_cap + 1)
        else:
            raw = stored
        self.decoded += len(raw)
        if len(raw) > decoded_cap or self.decoded > MAX_DECODED_BYTES:
            raise MemoryError("decoded metadata byte cap exceeded")
        pin = dict(source_id=source, path=relative, bytes=len(stored), sha256=sha256(stored).hexdigest(),
                   decoded_bytes=len(raw), encoding="gzip-json" if compressed else "json")
        document = _Document(_decode(raw), pin)
        self.stamps[path] = _stamp(before)
        return document

    def unchanged(self):
        for path, stamp in self.stamps.items():
            if _stamp(path.lstat()) != stamp or path.resolve(strict=True) != path:
                raise ValueError("metadata changed within readback")


def _fields(doc, pointer, specifications):
    value = doc.get(pointer, dict)
    return {key: doc.fact(pointer + _path(key), kind, unit, nullable=nullable)
            for key, kind, unit, nullable in specifications if key in value}


def _metric(doc, pointer):
    status = doc.get(pointer + "/status", str)
    value = doc.get(pointer + "/value", "number", nullable=True)
    if (status == "VALID") != (value is not None):
        raise ValueError("metric validity/value mismatch at " + pointer)
    unit = doc.get(pointer + "/unit", str)
    return dict(value=doc.fact(pointer + "/value", "number", unit, nullable=True, status=status),
                status=doc.fact(pointer + "/status", str, "status"),
                reason=doc.fact(pointer + "/reason", str, "reason", nullable=True),
                unit=doc.fact(pointer + "/unit", str, "unit"),
                metric_id=doc.fact(pointer + "/metric_id", str, "identity"),
                sample_count=doc.fact(pointer + "/sample_count", "count", "observations"))


def _account(doc, pointer):
    result = _fields(doc, pointer, (
        ("account_identity", str, "identity", False), ("environment_id", str, "calendar_view", False),
        ("start_ns", "count", "UTC_ns", False), ("stop_ns", "count", "UTC_ns_exclusive", False),
        ("initial_capital", "number", "account_quote_currency", False),
        ("baseline_equity", "number", "account_quote_currency", False),
        ("final_equity", "number", "account_quote_currency", False),
        ("money_pnl", "number", "account_quote_currency", True),
        ("net_return", "number", "decimal_return", True),
        ("raw_sharpe", "number", "retained_sharpe", True),
        ("max_drawdown", "number", "positive_fraction", True),
        ("daily_loss_es", "number", "positive_decimal_daily_loss", True),
        ("daily_count", "count", "days", False), ("partial_days", "count", "days", False),
        ("quality_pass", bool, "boolean", False), ("risk_pass", bool, "boolean", False),
        ("support_pass", bool, "boolean", False), ("metric_contract", str, "identity", False),
    ))
    for required in ("net_return", "raw_sharpe", "max_drawdown", "daily_loss_es", "daily_count"):
        if required not in result:
            raise ValueError("incomplete retained account summary at " + pointer)
    result["utility"] = _metric(doc, pointer + "/utility")
    return result


def _winner(doc, pointer, candidate):
    result = dict(candidate_id=doc.fact(pointer + "/candidate_id", str, "identity", expected=candidate),
                  status=doc.fact(pointer + "/status", str, "status",
                                  expected="QUALIFIED_REGISTERED_FINITE_WINNER_CHECKS"),
                  basin_certified=doc.fact(pointer + "/basin_certified", bool, "boolean", expected=False),
                  evidence_ref=doc.ref(pointer + "/evidence"))
    for scenario in ("center", "double_fee"):
        base = pointer + "/" + scenario
        annual = doc.get(base + "/annual", list)
        if len(annual) != 7:
            raise ValueError("seven retained annual views required")
        summaries = [_account(doc, base + _path("annual", i)) for i in range(7)]
        ids = [doc.get(base + _path("annual", i, "environment_id"), str) for i in range(7)]
        whole = _account(doc, base + "/whole")
        if len(set(ids)) != 7 or sum(row["daily_count"]["value"] for row in summaries) != whole["daily_count"]["value"]:
            raise ValueError("annual support must partition one continuous account")
        result[scenario] = dict(whole=whole, annual=summaries, summary=_fields(doc, base, (
            ("common_eligible", bool, "boolean", False), ("positive_years", "count", "calendar_views", False),
            ("positive_year_denominator", "count", "calendar_views", False),
            ("annual_floor_return", "number", "decimal_return", True),
            ("annual_floor_utility", "number", "decimal_return", True),
            ("worst_annual_dd", "number", "positive_fraction", True),
            ("undefined_annual_returns", "count", "calendar_views", False),
            ("undefined_annual_utilities", "count", "calendar_views", False),
        )))
        partial = doc.get(base + "/partial_calendar_environments", list)
        if (len(partial) > 7 or any(type(item) is not str for item in partial)
                or len(set(partial)) != len(partial) or not set(partial) <= set(ids)):
            raise ValueError("partial calendar labels must belong to the retained annual roster")
        result[scenario]["partial_calendar_environments"] = [
            doc.fact(base + _path("partial_calendar_environments", i), str, "calendar_view")
            for i in range(len(partial))]
        result[scenario]["activity"] = _fields(doc, base + "/activity", (
            ("fills", "count", "fills", True), ("closed_campaigns", "count", "campaigns", True),
            ("open_campaigns", "count", "campaigns", True),
            ("fee_sum", "number", "account_quote_currency", True),
            ("exposure_fraction", "number", "fraction", True),
            ("cost_ledger", str, "status", False), ("limitation", str, "limitation", False),
        ))
    held = pointer + "/held_whole_utility"
    expected = doc.get(held + "/expected_unique_probes", "count")
    valid = doc.get(held + "/valid_probes", "count")
    if valid > expected:
        raise ValueError("held support exceeds its retained roster")
    result["held"] = _fields(doc, held, (
        ("status", str, "status", False), ("expected_unique_probes", "count", "probes", False),
        ("valid_probes", "count", "probes", False), ("center_utility", "number", "decimal_return", True),
        ("quality_survival_fraction", "number", "fraction", True),
        ("empirical_worst_utility", "number", "decimal_return", True),
        ("lower_tail_utility", "number", "decimal_return", True),
    ))
    result["geometric_coverage"] = _fields(doc, pointer + "/geometric_coverage", (
        ("status", str, "status", False), ("raw_rows", "count", "probes", False),
        ("unique_effective", "count", "points", False), ("infeasible", "count", "points", False),
    ))
    result["full_mandate_survival"] = doc.fact(pointer + "/full_mandate_survival", "number", "fraction", nullable=True)
    return result


def _archive(doc, alpha):
    alias = "A-" + alpha if alpha in ("N1", "N2") else alpha
    roster = doc.get("/mode4", dict)
    result = dict(status="INVENTORIED_NOT_ADMITTED" if alias in roster else "NO_ARCHIVE",
                  roster_ref=doc.ref("/mode4"), authority="NOT_ASSESSED", quantities={})
    if alias in roster:
        result["quantities"] = {key: doc.fact(_path("mode4", alias, key), "count", unit) for key, unit in (
            ("origins", "overlapping_origins"), ("candidates", "retained_IS_candidates"),
            ("acquired_forward", "acquired_forward_observations"),
            ("unique_recorded_coordinates", "recorded_coordinates_not_independent_samples"))}
        dispositions = doc.get(_path("mode4", alias, "forward_dispositions"), dict)
        known = {"VALID", "NO_VARIANCE", "UNDEFINED", "FAILED", "MISSING"}
        if not set(dispositions) <= known:
            raise ValueError("unknown retained forward disposition")
        result["forward_dispositions"] = {key: doc.fact(
            _path("mode4", alias, "forward_dispositions", key), "count", "observations")
            for key in ("VALID", "NO_VARIANCE", "UNDEFINED", "FAILED", "MISSING") if key in dispositions}
    if alias in doc.get("/exclusions", dict):
        result["scope_limit"] = doc.fact(_path("exclusions", alias), str, "limitation")
    return result


def _alphas(doc, inventory):
    doc.fact("/schema", str, "schema", expected="quantbt.mode5_upgrade.phase_report.v1")
    doc.fact("/status", str, "status", expected="COMPLETE_REGISTERED_SEVEN_ALPHA_COLD_SYNTHESIS")
    for name in ("independent_oos", "original_winners_changed"):
        doc.fact(_path(name), bool, "boolean", expected=False)
    scope = doc.get("/alpha_scope", list)
    if any(type(alpha) is not str for alpha in scope) or len(scope) != 7 or set(scope) != set(ALPHAS):
        raise ValueError("exact seven-alpha retained scope required")
    if set(doc.get("/numeric_results", dict)) != set(ALPHAS):
        raise ValueError("seven distinct alpha summaries required")
    common_limits = doc.get("/limitations", list)
    if len(common_limits) > MAX_LIMITS:
        raise MemoryError("retained limitation roster cap exceeded")
    result = {}
    for alpha in ALPHAS:
        base = _path("numeric_results", alpha)
        row = doc.get(base, dict)
        entry = dict(status=doc.fact(base + "/status", str, "status"),
                     scope={key: doc.fact(base + _path("scope", key), str, unit) for key, unit in (
                         ("symbol", "instrument"), ("timeframe", "timeframe"),
                         ("start", "UTC_inclusive"), ("stop_exclusive", "UTC_exclusive"),
                         ("economic_contract", "contract"))},
                     diagnostics=_fields(doc, base + "/diagnostics", (
                         ("registered_cells", "count", "diagnostic_configurations", False),
                         ("unique_effective_points", "count", "points", False),
                         ("common_eligible", "count", "configurations", False),
                         ("no_trade", "count", "configurations", False))),
                     studies={}, winners={}, archive=_archive(inventory, alpha),
                     limits=[doc.fact(_path("limitations", i), str, "limitation")
                             for i in range(len(common_limits))],
                     regime_ref=doc.ref(base + "/regimes"))
        for field in ("limitation", "attribution_boundary"):
            if field in row:
                entry["limits"].append(doc.fact(base + _path(field), str, "limitation"))
        doc.fact(base + "/diagnostics/registered_cells", "count", "diagnostic_configurations", expected=128)
        if alpha == "A-HMA":
            doc.fact(base + "/status", str, "status", expected="NO_SELECTION")
            entry["common_eligible"] = doc.fact(base + "/common_eligible", "count", "configurations", expected=0)
            entry["formal_disposition"] = doc.fact(base + "/formal_disposition", str, "status",
                                                 expected="NO_ELIGIBLE_COHORT_NO_NEW_SEARCH")
            if (doc.get(base + "/arms", dict)
                    or "studies" in row and doc.get(base + "/studies", dict)):
                raise ValueError("HMA cannot acquire a fabricated formal winner")
        else:
            expected = {"raw-tpe", "floor-tpe", "floor-cma"} if alpha == "A-RSI" else set(ARMS)
            if set(doc.get(base + "/studies", dict)) != expected or set(doc.get(base + "/arms", dict)) != expected:
                raise ValueError("exact retained per-alpha arm roster required")
            for arm in sorted(expected):
                pointer = base + _path("studies", arm)
                formula = doc.get(pointer + "/objective", str)
                if formula not in FORMULA_UNITS:
                    raise ValueError("unknown retained objective unit contract")
                states = doc.get(pointer + "/states", dict)
                counts = {state: doc.fact(pointer + _path("states", state), "count", "attempts")
                          for state in states if state in {"COMPLETE", "PRUNED", "FAIL"}}
                if set(counts) != set(states) or sum(f["value"] for f in counts.values()) != 256:
                    raise ValueError("terminal study counts must retain 256 attempts")
                candidate = doc.get(pointer + "/candidate_id", str)
                entry["studies"][arm] = dict(
                    attempts=doc.fact(pointer + "/attempts", "count", "attempts", expected=256), states=counts,
                    candidate_id=doc.fact(pointer + "/candidate_id", str, "identity"),
                    objective=doc.fact(pointer + "/objective", str, "formula"),
                    objective_unit=FORMULA_UNITS[formula], sampler=doc.fact(pointer + "/sampler", str, "sampler"),
                    completion_ref=doc.ref(pointer + "/complete"))
                entry["winners"][arm] = _winner(doc, base + _path("arms", arm), candidate)
        result[alpha] = entry
    return result


def _formal(doc, c06, c05):
    doc.fact("/status", str, "status", expected="PASS_COLD_SEALED_FORMAL_SUMMARY_AND_RECIPE_ARITHMETIC")
    for key in ("financial_executions", "optimizer_proposals", "changed_winners"):
        doc.fact(_path(key), "count", "count", expected=0)
    c06.fact("/status", str, "status", expected="COMPLETE_REGISTERED_M5119_RESEARCH_SCOPE")
    rows = doc.get("/rows", list)
    if len(rows) != 9:
        raise ValueError("all nine final formal studies required")
    roster, output, totals, indexed = set(), [], {"COMPLETE": 0, "PRUNED": 0}, {}
    for i in range(len(rows)):
        pointer = _path("rows", i)
        alpha, arm = doc.get(pointer + "/alpha", str), doc.get(pointer + "/arm", str)
        key = (alpha, arm)
        if alpha not in {"A-SC", "A-HASH", "A-VWAP"} or arm not in ARMS or key in roster:
            raise ValueError("distinct registered nine-study roster required")
        roster.add(key)
        states = doc.get(pointer + "/states", dict)
        if set(states) != {"COMPLETE", "PRUNED"}:
            raise ValueError("explicit final formal states required")
        for state in totals:
            count = doc.get(pointer + _path("states", state), "count")
            totals[state] += count
            if count != c05.get(_path("numeric_results", alpha, "studies", arm, "states", state), "count"):
                raise ValueError("formal/C05 count mismatch")
        if sum(states.values()) != 256:
            raise ValueError("256 terminal formal attempts required")
        formula = doc.get(pointer + "/formula", str)
        registered_formula = c05.get(_path("numeric_results", alpha, "studies", "recipe-tpe", "objective"), str)
        if formula not in FORMULA_UNITS or formula != registered_formula:
            raise ValueError("saved recipe formula required for common-formula comparison")
        row = dict(alpha=alpha, arm=arm, ref=doc.ref(pointer),
                   formula=doc.fact(pointer + "/formula", str, "formula"),
                   saved_formula_score=doc.fact(pointer + "/frozen_recipe_cold_score", "number", FORMULA_UNITS[formula]),
                   recorded_objective=doc.fact(pointer + "/recorded_objective", "number",
                                               "retained_sharpe" if arm == "raw-tpe" else FORMULA_UNITS[formula]),
                   winner_unchanged=doc.fact(pointer + "/winner_unchanged", bool, "boolean", expected=True))
        output.append(row)
        indexed[key] = row
    if len(roster) != 9:
        raise ValueError("all nine final formal studies required")
    counts = {key: doc.fact(_path(key), "count", "attempts", expected=value) for key, value in (
        ("attempts", 2304), ("complete", totals["COMPLETE"]), ("pruned", totals["PRUNED"]))}
    for key in ("attempts", "complete", "pruned"):
        c06.fact(_path("formal_work", key), "count", "attempts", expected=counts[key]["value"])
    counts["unique_within_study"] = c06.fact("/formal_work/unique_within_study", "count", "within_study_points")
    examples = {}
    for alpha in ("A-HASH", "A-VWAP"):
        scores = {arm: indexed[(alpha, arm)]["saved_formula_score"] for arm in ARMS}
        if len({indexed[(alpha, arm)]["formula"]["value"] for arm in ARMS}) != 1:
            raise ValueError("counterexample formulas must match within alpha")
        examples[alpha] = dict(status="DESCRIPTIVE_SAVED_FORMULA_COMPARISON", scores=scores,
            raw_exceeds_recipe={arm: dict(value=scores["raw-tpe"]["value"] > scores[arm]["value"],
                operation="greater_than", input_refs=[scores["raw-tpe"]["ref"], scores[arm]["ref"]])
                for arm in ("recipe-tpe", "recipe-challenger")})
    return dict(counts=counts, rows=output, counterexamples=examples)


def _linked_pin(doc, pointer, target):
    pin = doc.get(pointer, dict)
    if set(pin) != {"path", "bytes", "sha256"}:
        raise ValueError("exact linked metadata pin required")
    for name in ("path", "sha256"):
        doc.fact(pointer + _path(name), str, "identity", expected=target.pin[name])
    doc.fact(pointer + "/bytes", "count", "bytes", expected=target.pin["bytes"])


def _observation(doc, pointer):
    status = doc.get(pointer + "/status", str)
    value = doc.get(pointer + "/raw_sharpe", "number", nullable=True)
    if status not in {"VALID", "NO_VARIANCE", "UNDEFINED", "MISSING", "INVALID", "INSUFFICIENT_SUPPORT"}:
        raise ValueError("unknown retained Sharpe measurement status")
    if status == "VALID" and value is None:
        raise ValueError("Sharpe status/value mismatch")
    # Legacy NO_VARIANCE observations retain a numeric zero. It is source data,
    # not a valid Sharpe; paired validity comes from status, never its sentinel.
    return dict(status=doc.fact(pointer + "/status", str, "status"),
                raw_sharpe=doc.fact(pointer + "/raw_sharpe", "number", "retained_sharpe", nullable=True, status=status),
                support=_fields(doc, pointer, (
                    ("sample_count", "count", "observations", False),
                    ("activity_count", "count", "activity", False),
                    ("window_start", str, "retained_window_start", False),
                    ("window_end", str, "retained_window_end", False),
                    ("metric_contract_id", str, "identity", False),
                    ("economics_id", str, "identity", False))))


def _assistance(doc, final, work, c05):
    final.fact("/status", str, "status", expected="COMPLETE_LOCAL_REGISTERED_RESEARCH_SCOPE")
    doc.fact("/status", str, "status", expected="COMPLETE_FINANCIAL_READBACK_QUALIFICATION_SEPARATE")
    work.fact("/status", str, "status", expected="COMPLETE_ACTUAL_WORK_LEDGER")
    _linked_pin(final, "/readback", doc)
    _linked_pin(final, "/work", work)
    for key in ("public_default_changes", "next_phase_authorized", "remote_or_release"):
        final.fact(_path(key), bool, "boolean", expected=False)
    final.fact("/model_fits", "count", "fits", expected=0)
    work.fact("/logical_study_slots", "count", "attempts", expected=4096)
    expected = {(alpha, direction, fold, arm) for alpha in ("N1", "N2") for arm in ("baseline", "treatment")
                for direction, folds in (("MODE4_TO_MODE5", (None,)), ("MODE5_TO_MODE4", (0, 28, 56)))
                for fold in folds}
    studies, indexed = [], {}
    if len(doc.get("/studies", list)) != 16 or len(doc.get("/pairs", list)) != 8:
        raise ValueError("sixteen studies and eight matched pairs required")
    for i in range(16):
        pointer = _path("studies", i)
        alpha, direction, arm = (doc.get(pointer + _path(k), str) for k in ("alpha", "direction", "arm"))
        fold = doc.get(pointer + "/fold", "count", nullable=True)
        key = (alpha, direction, fold, arm)
        if key not in expected or key in indexed:
            raise ValueError("exact distinct bidirectional study roster required")
        row = dict(alpha=alpha, direction=direction, fold=fold, arm=arm, ref=doc.ref(pointer),
                   attempts=doc.fact(pointer + "/attempts", "count", "attempts", expected=256),
                   quantities=_fields(doc, pointer, (
                       ("unique", "count", "effective_points", False),
                       ("duplicate_attempts", "count", "attempts", False),
                       ("branches_observed", "count", "branches", False),
                       ("warm_start_slots", "count", "proposal_slots", False),
                       ("sampled_startup_slots", "count", "proposal_slots", False),
                       ("physical_search_account_calls", "count", "owner_invocations", False),
                       ("financial_receipt_reuses", "count", "receipt_reuses", False),
                       ("fills", "count", "fills", True),
                       ("forward_exposure", "number", "fraction", True))))
        states = doc.get(pointer + "/counts", dict)
        if not states or not set(states) <= {"COMPLETE", "PRUNED", "FAIL"}:
            raise ValueError("known terminal assistance dispositions required")
        row["counts"] = {state: doc.fact(pointer + _path("counts", state), "count", "attempts")
                         for state in states}
        if sum(item["value"] for item in row["counts"].values()) != 256:
            raise ValueError("assistance dispositions must retain 256 attempts")
        if direction == "MODE4_TO_MODE5":
            selected = pointer + "/selected"
            formula = c05.get(_path("numeric_results", alpha, "studies", "recipe-tpe", "objective"), str)
            row["static"] = dict(
                objective=doc.fact(selected + "/objective", "number", FORMULA_UNITS[formula]),
                formula=c05.fact(_path("numeric_results", alpha, "studies", "recipe-tpe", "objective"), str, "formula"),
                candidate_id=doc.fact(selected + "/candidate_id", str, "identity"),
                fixed_dictionary=doc.fact(selected + "/fixed_dictionary", bool, "boolean", expected=True),
                min_annual_utility=doc.fact(selected + "/min_annual_utility", "number", "decimal_return"),
                activity=_fields(doc, selected, (
                    ("fills", "count", "fills", False),
                    ("closed_campaigns", "count", "campaigns", False),
                    ("exposure", "number", "fraction", False),
                    ("positive_return_years", "count", "calendar_views", False),
                    ("positive_utility_years", "count", "calendar_views", False))),
                whole=_account(doc, selected + "/whole"))
        else:
            row["is"] = _observation(doc, pointer + "/is_observation")
            row["forward"] = _observation(doc, pointer + "/forward_observation")
        indexed[key] = row
        studies.append(row)
    if set(indexed) != expected or len(final.get("/studies", list)) != 16:
        raise ValueError("all sixteen matched studies required")
    pairs, seen = [], set()
    for i in range(8):
        pointer = _path("pairs", i)
        alpha, direction = (doc.get(pointer + _path(k), str) for k in ("alpha", "direction"))
        fold = doc.get(pointer + "/fold", "count", nullable=True)
        key = (alpha, direction, fold)
        if (*key, "baseline") not in indexed or key in seen:
            raise ValueError("distinct matched pair identity required")
        seen.add(key)
        baseline, treatment = (indexed[(*key, arm)] for arm in ("baseline", "treatment"))
        row = dict(alpha=alpha, direction=direction, fold=fold, ref=doc.ref(pointer),
                   status=doc.fact(pointer + "/status", str, "status", expected="COMPLETE_MATCHED_PAIR"),
                   study_refs=[baseline["ref"], treatment["ref"]])
        if direction == "MODE4_TO_MODE5":
            for field, selected_field, unit in (
                ("delta_objective", "objective", baseline["static"]["objective"]["unit"]),
                ("delta_min_annual_utility", "min_annual_utility", "decimal_return")):
                row[field] = doc.fact(pointer + _path(field), "number", unit)
                difference = treatment["static"][selected_field]["value"] - baseline["static"][selected_field]["value"]
                if not math.isclose(row[field]["value"], difference, rel_tol=0., abs_tol=1e-10):
                    raise ValueError("static matched delta differs from saved objectives")
        else:
            statuses = [baseline["is"]["status"]["value"], treatment["is"]["status"]["value"],
                        baseline["forward"]["status"]["value"], treatment["forward"]["status"]["value"]]
            if doc.get(pointer + "/statuses", list) != statuses:
                raise ValueError("paired statuses differ from saved observations")
            is_valid, q_valid = all(s == "VALID" for s in statuses[:2]), all(s == "VALID" for s in statuses[2:])
            for field, valid in (("IS_supported", is_valid), ("Q_supported", q_valid), ("R_supported", is_valid and q_valid)):
                row[field] = doc.fact(pointer + _path(field), bool, "boolean", expected=valid)
            for field, valid, observations in (("delta_IS", is_valid, "is"), ("Q", q_valid, "forward")):
                row[field] = doc.fact(pointer + _path(field), "number", "retained_sharpe_difference", nullable=True,
                                      status="VALID" if valid else "UNDEFINED")
                value = row[field]["value"]
                if (value is not None) != valid:
                    raise ValueError("undefined paired metric must retain null")
                if valid:
                    difference = treatment[observations]["raw_sharpe"]["value"] - baseline[observations]["raw_sharpe"]["value"]
                    if not math.isclose(value, difference, rel_tol=0., abs_tol=1e-10):
                        raise ValueError("paired metric differs from saved Sharpe observations")
            valid = is_valid and q_valid
            row["R"] = doc.fact(pointer + "/R", "number", "retained_sharpe_difference", nullable=True,
                                 status="VALID" if valid else "UNDEFINED")
            if (row["R"]["value"] is not None) != valid:
                raise ValueError("undefined R must retain null")
            if valid and not math.isclose(row["R"]["value"], row["Q"]["value"] - row["delta_IS"]["value"],
                                          rel_tol=0., abs_tol=1e-10):
                raise ValueError("saved R must equal Q minus delta_IS")
            row["measurement_status"] = doc.fact(pointer + "/measurement_status", str, "status",
                expected="VALID_PAIRED_SHARPE" if valid else "UNDEFINED_PAIRED_SHARPE")
            row["statuses"] = [doc.fact(pointer + _path("statuses", j), str, "status") for j in range(4)]
        pairs.append(row)
    if len(seen) != 8:
        raise ValueError("all eight bidirectional pairs required")
    return dict(status=final.fact("/status", str, "status"), scope=doc.fact("/scope", str, "scope"),
                inference=doc.fact("/inference", str, "limitation"), studies=studies, pairs=pairs,
                work=_fields(work, "", (
                    ("logical_study_slots", "count", "proposal_slots", False),
                    ("prefix_diagnostic_distinct_accounts", "count", "accounts", False),
                    ("total_actual_owner_financial_invocations", "count", "owner_invocations", False),
                    ("optimizer_reruns_of_completed_studies", "count", "reruns", False),
                    ("account_count_convention", str, "limitation", False),
                    ("wall_time_warning", str, "limitation", False))),
                inherited_archive=_fields(work, "/inherited_archive", (
                    ("origins_per_alpha", "count", "overlapping_origins", False),
                    ("attempted_source_pool_slots_per_alpha", "count", "historical_source_slots", False),
                    ("acquisition_cost", str, "limitation", False))))


def _disposition(doc):
    restore_no_finance_handoff(doc.value)
    return dict(status=doc.fact("/status", str, "status"),
                whole_procedure=doc.fact("/whole_procedure_qualification", str, "status", expected="NOT_EVALUATED"),
                independent_validation=doc.fact("/independent_validation", bool, "boolean", expected=False),
                methods=[dict(ref=doc.ref(_path("methods", i)), **{
                    key: doc.fact(_path("methods", i, key), str, "status" if key in ("decision", "support") else "identity")
                    for key in ("cell_id", "method_id", "decision", "support")})
                    for i in range(len(doc.get("/methods", list)))],
                gates=[{key: doc.fact(_path("gates", i, key), str, "status")
                        for key in ("gate_id", "scope", "status")} for i in range(10)])


def readback(root: Path) -> Record:
    """Read the final retained snapshot under a repository root, without writes.

    This source-specific sidecar does not admit archives, compile a recipe or
    execute an alpha. A missing per-alpha archive remains an explicit NO_ARCHIVE
    observation. The source-wide final metadata files themselves are required.
    """
    reader = _Reader(root)
    docs = {name: reader.load(name) for name in SOURCES}
    inventory = docs["inventory"]
    inventory.fact("/schema", str, "schema", expected="m51110.inventory.v2")
    result = dict(schema=SCHEMA, status="COLD_RETAINED_METADATA_READBACK", private_only=True,
                  public_export_allowed=False,
                  archive_authority="NOT_ASSESSED", independent_validation=False, archive_required=False,
                  sources=[doc.pin for doc in docs.values()],
                  alphas=_alphas(docs["c05"], inventory),
                  formal=_formal(docs["formal"], docs["c06"], docs["c05"]),
                  assistance=_assistance(docs["assistance"], docs["assistance_final"],
                                         docs["assistance_work"], docs["c05"]),
                  disposition=_disposition(docs["disposition"]), limits=list(LIMITS),
                  work=dict(financial_invocations=0, optimizer_proposals=0, model_fits=0,
                            metadata_files=len(docs), stored_bytes=reader.stored, decoded_bytes=reader.decoded))
    payload = _canonical(result)
    if len(payload.encode("utf-8")) > MAX_RECORD_BYTES:
        raise MemoryError("readback record byte cap exceeded")
    reader.unchanged()
    return Record(payload)


def main(argv=None):
    """Print JSON only; callers own explicit receipt persistence and access policy."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="explicit repository root")
    args = parser.parse_args(argv)
    print(readback(args.root).payload)


if __name__ == "__main__":
    main()
