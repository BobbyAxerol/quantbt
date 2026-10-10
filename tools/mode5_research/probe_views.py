"""Cold annual attribution of registered probes; no account or engine import.

Registration is stdlib-only. Numeric reduction explicitly loads the existing
panel/reporting owners through package namespaces without their runtime facades.
The resulting annual views are dependent current-knowledge development evidence.
"""

import argparse
import ast
from collections import Counter
from dataclasses import asdict, fields
import importlib
from importlib.machinery import ModuleSpec
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback
from types import ModuleType

from tools.mode5_research import selector_checkpoint as custody


ROOT = Path(__file__).resolve().parents[2]
MIB = 1024**2
REQUEST_SHA = "f23b1b3cae547cf6868c22bac743c4e73f22e2ebbb53004010133a23206bd3ba"
PANEL_SHA = "8de8ac106b6e299abd858d90d70e003ddf372bfc74c81c18544bf65974e177d7"
ANNUAL = ("2021", "2022", "2023")
ROLES = ("selection_probe", "local_validation")
THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
           "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "RAYON_NUM_THREADS")
UTILITY = dict(preference_id="m5081-primary-equal-year-v1", dd_weight=1., tail_weight=1.,
               drawdown_basis="scope_entry")
COMMON = dict(version="environment_floor_mean_v1", coefficients=dict(mean=.25),
    environment_ids=list(ANNUAL), weights=[1., 1., 1.], activity_penalty=0.,
    channel="ECONOMIC_UTILITY_V1", metric_contract="mode5.panel.economic_utility", unit="decimal_return",
    utility=UTILITY, risk_drawdown_max=.5, quality_utility_strictly_greater_than=0., minimum_daily_count=365,
    sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close",
    baseline="scope entry before first mark", account_reset=False,
    estimand="CONTINUOUS_PATH_ATTRIBUTION", independent_environments=False)
MISSING_LOCAL = [
    dict(status="MISSING_ANNUAL_LOCAL_REDUCER_AUTHORIZATION",
        requirement="versioned local reducer consuming environment_floor_mean_v1 for both center and neighbors",
        reason="canonical local_downside_v1 uses weighted_environment_mean_v1; substituting this aggregate changes its contract"),
    dict(status="MISSING_ANNUAL_LOCAL_PLAN_REFERENCE_BINDING",
        requirement="freeze annual local channel/AnalysisKey/reference identity, gamma, scale and probe qualification policy",
        reason="whole-path gamma/scale/quality registration is not an annual-local plan; no automatic inheritance"),
]
_ALLOWED = ("quantbt.metrics.report_contracts", "quantbt.metrics.reporting", "quantbt.mode5.artifacts",
            "quantbt.mode5.diagnostics", "quantbt.mode5.statistics", "quantbt.mode5.selection")
_PACKAGES = ("quantbt", "quantbt.metrics", "quantbt.mode5", "quantbt.mode5.diagnostics",
             "quantbt.mode5.statistics", "quantbt.mode5.selection", "tools.mode5_diagnostics")


def forbidden(name):
    if name.startswith("_quantbt_native") or name.startswith("quantbt.") and name not in _PACKAGES:
        return not any(name == p or name.startswith(p + ".") for p in _ALLOWED)
    return name.startswith("upgrade.local.")


class ColdImports:
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise ImportError("cold annual views prohibit runtime import: " + fullname)
        return None


def numeric_owner():
    bad = sorted(name for name in sys.modules if forbidden(name))
    if bad:
        raise RuntimeError("fresh cold process required: " + str(bad))
    if not any(isinstance(finder, ColdImports) for finder in sys.meta_path):
        sys.meta_path.insert(0, ColdImports())
    # Only package facades are bypassed; reporting/statistics implementation files
    # remain their original modules, pinned before analysis and checked afterwards.
    for name in _PACKAGES:
        if name not in sys.modules:
            package = ModuleType(name)
            base = ROOT / "src" if name.startswith("quantbt") else ROOT
            package.__path__ = [str(base / name.replace(".", "/"))]
            package.__spec__ = ModuleSpec(name, loader=None, is_package=True)
            package.__spec__.submodule_search_locations = package.__path__
            package._probe_views_cold_namespace = True
            sys.modules[name] = package
        elif not getattr(sys.modules[name], "_probe_views_cold_namespace", False):
            raise RuntimeError("fresh namespace required: " + name)
    return importlib.import_module("tools.mode5_research.panels")


def validate_common(policy):
    if policy != COMMON:
        raise ValueError("unapproved common annual aggregate/utility/unit/gate contract")
    return custody.digest(policy)


def sealed_bytes(record):
    custody.checked(record)
    data = Path(record["path"]).read_bytes()
    if len(data) != record["bytes"] or custody.hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("sealed input changed during read")
    return data


def sealed_json(record):
    return json.loads(sealed_bytes(record))


def indexed(records):
    result = {}
    for record in records:
        if record["path"] in result and result[record["path"]] != record:
            raise ValueError("conflicting retained pins")
        result[record["path"]] = record
    return result


def preference_check(result):
    prefs = result["preferences"]
    formula = [f for f in prefs["formulas"] if f["version"] == COMMON["version"]]
    if (len(formula) != 1 or formula[0]["coefficients"] != COMMON["coefficients"]
            or prefs["environment_weights"] != "equal positive 1.0 per annual environment; whole path not stacked into annual selectors"
            or any(prefs[k] != COMMON[k] for k in ("activity_penalty", "risk_drawdown_max",
                "quality_utility_strictly_greater_than", "minimum_daily_count"))):
        raise ValueError("original sealed preferences differ from authorized aggregate")
    for row in result["candidate_environment_rows"]:
        utility = next(m for m in row["metrics"] if m["metric_id"] == COMMON["metric_contract"])
        parts = dict(utility["components"])
        if utility["unit"] != COMMON["unit"] or utility["status"] == "VALID" and any(parts[k] != v for k, v in UTILITY.items()):
            raise ValueError("original sealed utility preference differs")


def register(parent, lane):
    parent, lane = Path(parent).resolve(), Path(lane).resolve()
    step = parent / "goal-step1"
    if lane != step / "annual-view01" or lane.exists():
        raise ValueError("new exact goal-step1/annual-view01 lane required")
    before = custody.resources(parent)
    if before["free_bytes"] < 5*1024**3 + 160*MIB or not before["free_inodes"]:
        raise ValueError("5 GiB reserve plus scratch/retained budget required")
    original_pin = custody.pin(step / "registration_01.json")
    original = sealed_json(original_pin)
    if len(original["protected_prior_files"]) != 4752:
        raise ValueError("exact historical 4,752-pin custody required")
    verified = custody.verify_prior(original)
    request_pin = custody.pin(step / "missing_evidence_requests_08.json")
    if request_pin["sha256"] != REQUEST_SHA:
        raise ValueError("accepted missing-request seal required")
    requests = sealed_json(request_pin)
    if [len(requests[a]["annual_view_requests"]) for a in ("rsi", "sc")] != [465, 174]:
        raise ValueError("exact 639 retained-path requests required")
    pool = indexed(original["protected_prior_files"])
    originals, conventions = {}, {}
    for alpha, filename in (("rsi", "analyst_results_02.json"), ("sc", "analyst_results_sc_01.json")):
        result_pin = pool[str(parent / filename)]
        result = sealed_json(result_pin)
        preference_check(result)
        row_pin = result["input_lineage"]["rows"]
        if pool[row_pin["path"]] != row_pin:
            raise ValueError("original panel producer rows lack prior custody")
        full = next(r for r in sealed_json(row_pin)["rows"] if r["environment_id"] == "whole_path")
        conventions[alpha] = full["raw_account_metrics"]["provenance"]["contract"]
        originals[alpha] = dict(result=result_pin, rows=row_pin, preferences=result["preferences"])
    if conventions["rsi"] != conventions["sc"]:
        raise ValueError("different original annual reporting conventions")
    prior_step = [custody.pin(p) for p in sorted(step.rglob("*")) if p.is_file()]
    sources = [ROOT / "tools/mode5_research/panels.py", ROOT / "tools/mode5_research/protocol.py",
               ROOT / "tools/mode5_research/selector_checkpoint.py"]
    for directory in ("src/quantbt/metrics/reporting", "src/quantbt/mode5/statistics",
                      "src/quantbt/mode5/selection", "src/quantbt/mode5/diagnostics",
                      "tools/mode5_diagnostics", "tools/mode5_statistics", "tools/mode5_selection"):
        sources.extend(sorted((ROOT / directory).glob("*.py")))
    sources.extend(ROOT / p for p in ("src/quantbt/metrics/report_contracts.py", "src/quantbt/mode5/artifacts.py"))
    software = [custody.pin(p) for p in sorted(set(sources))]
    if custody.pin(ROOT / "tools/mode5_research/panels.py")["sha256"] != PANEL_SHA:
        raise ValueError("original panel producer changed")
    return custody.write_new(lane / "registration_01.json", dict(
        schema="m5111_probe_annual_views_registration_v1", created_at=custody.now(),
        authority="owner annual-view-only sidecar following accepted 15c6422",
        outcome_timing="reviewed development; present custody, not retroactive preregistration or clean OOS",
        original_registration=original_pin, original_custody=verified, prior_step_files=prior_step,
        requests=request_pin, originals=originals, original_reporting_contract=conventions["rsi"],
        common_aggregate=COMMON, common_aggregate_identity=validate_common(COMMON),
        local_analysis_status="NOT_AUTHORIZED_MISSING_ANNUAL_LOCAL_POLICY", missing_local_policy=MISSING_LOCAL,
        resources_before=before, software=software,
        budget=dict(scratch_bytes=32*MIB, retained_bytes=128*MIB, reserve_bytes=5*1024**3),
        cleanup_inventory=dict(scratch_paths=[], eligible_deletions=[], retained_lane=str(lane),
            process_review="sandbox process view only; no workers or deletion",
            exclusions=["all prior evidence including failures", "all source/data", "all environments/caches"]),
        tests=[str(Path(sys.executable).absolute()), "-B", "-m", "unittest", "discover", "-s", "tests",
               "-p", "test_mode5_probe_views.py", "-v"],
        write_set=["tools/mode5_research/probe_views.py", "tests/test_mode5_probe_views.py",
                   "docs/mode5/M5_11_1_SELECTOR_ONLY.md", str(lane)],
        financial_executions=0, builds=0, installs=0, launches_authorized=False))


def registered_request(requests, execution, evaluation):
    matches = [r for r in requests if r["execution_index"] == execution["index"]]
    if (len(matches) != 3 or {r["environment_id"] for r in matches} != set(ANNUAL)
            or execution["role"] not in ROLES):
        raise ValueError("three exact annual requests per registered role/execution required")
    for r in matches:
        if (any(r[k] != execution[k] for k in ("center", "role", "candidate_id"))
                or r["exact_execution_request"] != execution["request"]
                or r["source_cell"] != evaluation["cell"] or r["source_path"] != evaluation["paths"]
                or r["status"] != "MISSING_SEALED_ANNUAL_METRIC_VIEW"
                or r["request_type"] != "REDUCE_RETAINED_CONTINUOUS_PATH_NO_ACCOUNT_RERUN"
                or r["required_metrics"] != ["economic_utility", "net_return", "drawdown", "daily_loss_es", "daily_count"]):
            raise ValueError("sealed annual request/evaluation identity mismatch")
    return {r["environment_id"]: r for r in matches}


def probe_cell(execution, evaluation, probes, pool, contract, cutoff_ns):
    p = numeric_owner()
    import numpy as np
    cell = sealed_json(evaluation["cell"])
    request = execution["request"]
    center = next(c for c in probes["centers"] if c["center"] == execution["center"])
    neighborhood = next(n for n in probes["neighborhoods"] if n["neighborhood_id"] == execution["neighborhood_id"])
    proposal = next(r for r in neighborhood["rows"] if r["row_id"] == execution["row_id"])
    if (any(execution[k] != evaluation[k] for k in ("index", "center", "role", "candidate_id", "row_id"))
            or cell["request"] != request or cell["metrics"] != evaluation["metrics"]
            or cell["execution_key"] != evaluation["execution_key"] or cell["path"] != evaluation["paths"]
            or cell["status"] != "PASS" or cell["clean_oos"] is not False
            or request["role"] != execution["role"] or request["role"] not in ROLES
            or request["design_id"] != neighborhood["neighborhood_id"]
            or neighborhood["role"] != request["role"] or neighborhood["center"] != execution["center"]
            or request["candidate_id"] != proposal["candidate_id"] or proposal["status"] != "READY"
            or proposal["execution_index"] != execution["index"]
            or request["params"] != json.loads(proposal["point"]["effective_json"])
            or request["parent_candidate_id"] != center["candidate_id"]
            or request["parent_panel_index"] != center["panel_index"]
            or request["parent_design_id"] != probes["parent_design_id"]
            or (request["start"], request["stop"], request["account_mode"]) !=
                ("2021-01-01", "2024-01-01", "continuous_development_2021_2023")):
        raise ValueError("original admitted probe/request/center/role/metrics mismatch")
    if (request["probe_seed"] != neighborhood["seed"] or request["probe_radius"] != neighborhood["radius"]
            or request["proposal_row"] != execution["row_id"] or request["probe_direction"] != proposal["direction"]):
        raise ValueError("original neighborhood direction/seed/radius mismatch")
    parent = Path(evaluation["cell"]["path"]).parent
    pins = {name: pool[str(parent / filename)] for name, filename in
            (("request", "request.json"), ("access", "development_access.json"))}
    if sealed_json(pins["request"]) != request:
        raise ValueError("separately sealed request mismatch")
    access = sealed_json(pins["access"])
    if (access["future_tape_opened"] is not False or access["original_contract_preserved"] is not True
            or access["fresh_strategy_and_account"] is not True or access.get("mutable_strategy_or_account_reused") is True
            or access["allowed_stop"] != request["stop"] or access["role"] != request["role"]
            or access["signature_before"] != access["signature_after"]
            or access["shared_market_hash"] != probes["shared_market_hash"]
            or pool.get(access["witness"]["path"]) != access["witness"]):
        raise ValueError("original development access/source witness mismatch")
    critical = indexed(probes["critical_sources"])
    for name in ("finance_driver", "prepared", "orchestrator"):
        if name in access and critical.get(access[name]["path"]) != access[name]:
            raise ValueError("unsealed financial provenance (never imported)")
    start, stop = p._ns(request["start"]), p._ns(request["stop"])
    if stop > cutoff_ns or p._ns(probes["created_at"]) > cutoff_ns:
        raise PermissionError("future development or probe registration")
    if (contract.baseline_time_ns != start-p.HOUR_NS or contract.scope_end_ns != stop-p.HOUR_NS
            or contract.baseline_equity != 20000. or contract.sampling != "observed_daily_utc"
            or contract.annual_periods != 365. or contract.equity_clock != "bar_close"
            or contract.partial_periods != "include_disclosed" or contract.cashflows != "none"):
        raise ValueError("original continuous reporting contract required")
    if evaluation["cell"] != pool.get(evaluation["cell"]["path"]) or evaluation["paths"] != pool.get(evaluation["paths"]["path"]):
        raise ValueError("probe cell/path lacks historical independent custody")
    if Path(evaluation["paths"]["path"]) != parent / "paths.npz":
        raise ValueError("original path sibling required")
    with np.load(BytesIO(sealed_bytes(evaluation["paths"])), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if not {"times_ns", "equity", "positions", "daily_returns"} <= arrays.keys():
        raise ValueError("retained account streams required")
    times = arrays["times_ns"]
    count, days = (stop-start)//p.HOUR_NS, (stop-start)//p.DAY_NS
    if (times.dtype != np.dtype("int64") or times.shape != (count,)
            or not np.array_equal(times, np.arange(start, stop, p.HOUR_NS, dtype=np.int64))
            or cell["scored_bars"] != count or cell["scored_days"] != days
            or type(cell["actual_execution_calls"]) is not int or cell["actual_execution_calls"] < 1
            or cell["visited_bars"] != count*cell["actual_execution_calls"]
            or arrays["daily_returns"].shape != (days,) or not np.isfinite(arrays["daily_returns"]).all()):
        raise ValueError("complete chronological hours/days/account resource accounting required")
    for name in ("equity", "positions", "fees", "funding", "turnover"):
        if name in arrays and (arrays[name].shape != times.shape or not np.isfinite(arrays[name]).all()):
            raise ValueError("finite aligned retained stream required")
    coverage = p.ReportingCoverageV1(result_identity=evaluation["paths"]["sha256"],
        producer="sealed actual account path", profile="compact", ledger="omitted", retained_rows=0,
        dropped_rows=0, reason="campaign ledger is separately retained or unavailable")
    obs = p.AccountObservations(times_ns=times, equity=arrays["equity"], coverage=coverage)
    if np.all(obs.equity > 0):
        obs = obs.with_derived_returns(contract, partial_mask=np.zeros(days, dtype=bool),
            witness="sealed full-hour UTC days; original scope-entry valuation")
        if not np.allclose(obs.returns.values, arrays["daily_returns"], rtol=0, atol=1e-12):
            raise ValueError("retained daily returns differ from panel authority")
    raw = p.reduce_account(obs, contract, backend="python")
    for source, target in (("account.total_return", "total_return"), ("drawdown.max_depth", "max_drawdown"),
                           ("period.sharpe", "sharpe")):
        close(raw.metric(source).value, cell["metrics"][target], "original whole-path " + target)
    campaigns = fills = None
    for name in ("campaigns", "fills"):
        path = str(parent / (name + ".json"))
        if path in pool:
            pins[name] = pool[path]
            value = sealed_json(pool[path])
            if name == "campaigns":
                campaigns = value
            else:
                fills = value
    if campaigns is not None:
        if set(campaigns) != {"closed", "open"}:
            raise ValueError("sealed closed/open campaign schema required")
        for kind, records in campaigns.items():
            if len(records) != cell["support"][kind + "_campaigns"]:
                raise ValueError("campaign support mismatch")
            for r in records:
                end = p._ns(r["end"]) if kind == "closed" else stop-p.HOUR_NS
                if not start <= p._ns(r["start"]) <= end < stop:
                    raise ValueError("campaign outside account calendar")
        pnl = sum(r["net_pnl"] for r in campaigns["closed"]) + sum(r["marked_net_pnl"] for r in campaigns["open"])
        close(pnl, float(obs.equity[-1])-contract.baseline_equity, "campaign PnL", tolerance=1e-8)
    if fills is not None:
        fill_times = [p._ns(r["timestamp"]) for r in fills]
        if (len(fills) != cell["support"]["fills"] or fill_times != sorted(fill_times)
                or any(t < start or t >= stop for t in fill_times)):
            raise ValueError("fill support/calendar mismatch")
    if request["alpha"] == "A-SC" and (campaigns is None or fills is None):
        raise ValueError("SC retained ledgers cannot be omitted")
    refs = {"cell": evaluation["cell"]["sha256"], "paths": evaluation["paths"]["sha256"],
            **{name: pin["sha256"] for name, pin in pins.items()}, "development_data": access["witness"]["sha256"]}
    provenance = p.CandidateProvenance("m5111_goal_step1", "annual_view01", request["alpha"],
        request["candidate_id"], custody.digest(json.loads(proposal["point"]["requested_json"])),
        custody.digest(request["params"]), proposal["direction"], (request["proposal_row"],),
        cell["execution_key"], request["design_id"], request["symbol"], "REVIEWED_EXPLORATORY_DEVELOPMENT",
        "registered probe role " + request["role"] + "; reviewed development, not temporal OOS",
        p._ns("2020-01-01"), stop, cutoff_ns, cutoff_ns, cell["route"], tuple(sorted(refs.items())))
    buffers = tuple(p.FrozenBuffer.from_array(name, values) for name, values in sorted(arrays.items())
                    if name in {"positions", "fees", "funding", "turnover"})
    return p.VerifiedCell(provenance, start, stop, contract, obs, buffers,
        json.dumps(campaigns) if campaigns is not None else None, json.dumps(fills) if fills is not None else None,
        json.dumps(cell["metrics"]), "PASS", None)


def close(actual, expected, label, tolerance=1e-10):
    if ((actual is None) != (expected is None) or actual is not None and
            (not math.isfinite(actual) or not math.isfinite(expected) or not math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance))):
        raise ValueError(label + " differs from sealed authority")


def row_metadata(row):
    result = {f.name: asdict(getattr(row, f.name)) if f.name in {"provenance", "environment_baseline", "carried_watermark"}
              and getattr(row, f.name) is not None else getattr(row, f.name)
              for f in fields(row) if f.name not in {"metrics", "raw_account_metrics"}}
    result["metrics"] = [asdict(metric) for metric in row.metrics]
    result["raw_account_metrics"] = row.raw_account_metrics.to_metadata() if row.raw_account_metrics is not None else None
    return result


def annual_aggregate(rows, policy, *, role, expected_candidate=None, expected_execution=None):
    identity = validate_common(policy)
    if role not in (*ROLES, "center"):
        raise ValueError("registered center/probe role required")
    if len(rows) != 3 or [r["environment_id"] for r in rows] != list(ANNUAL):
        raise ValueError("complete ordered annual roster; no whole-path or survivor mean")
    candidates = {r["provenance"]["candidate_id"] for r in rows}
    executions = {r["provenance"]["execution_id"] for r in rows}
    if (len(candidates) != 1 or len(executions) != 1 or expected_candidate is not None and candidates != {expected_candidate}
            or expected_execution is not None and executions != {expected_execution}):
        raise ValueError("same actual candidate/account required")
    for row in rows:
        if role != "center" and row.get("role") != role or role == "center" and row.get("role") in ROLES:
            raise ValueError("validation/selection/center role cannot be relabeled")
        if (row["clean_oos"] is not False or row["estimand_id"] != COMMON["estimand"]
                or row["calendar_days"] != 365 or row["actual_bar_count"] != 8760
                or row["environment_baseline"]["as_of_ns"] != row["start_ns"]-3_600_000_000_000):
            raise ValueError("actual complete annual scope-entry view required")
        utility = next(m for m in row["metrics"] if m["metric_id"] == COMMON["metric_contract"])
        if utility["status"] == "VALID" and any(dict(utility["components"])[k] != v for k, v in UTILITY.items()):
            raise ValueError("annual utility preference differs")
    values = [custody.metric(row, "economic_utility") for row in rows]
    gates = {row["environment_id"]: custody.gates(row, policy) for row in rows}
    parts = score = None
    if all(value is not None for value in values):
        numeric_owner()
        from quantbt.mode5.selection.contracts import Channel, Formula
        from quantbt.mode5.selection.objectives import environment_components
        from quantbt.mode5.statistics.tails import FrozenReference
        channel = Channel(policy["channel"], policy["metric_contract"], policy["unit"])
        formula = Formula(policy["version"], channel, tuple(policy["coefficients"].items()))
        reference = FrozenReference(identity, ANNUAL, (.25, .25, .25), tuple(policy["weights"]), channel.identity, "annual_view01")
        parts = environment_components(values, reference, channel)
        score = parts["floor"] + formula.params["mean"]*parts["mean"] - policy["activity_penalty"]
        if not math.isfinite(score):
            raise ValueError("annual aggregate overflow")
    return dict(candidate_id=next(iter(candidates)), execution_id=next(iter(executions)), role=role,
        aggregate_identity=identity, formula_version=policy["version"], unit=policy["unit"], values=values,
        score=score, components=parts, gates=gates, eligible=score is not None and all(all(g.values()) for g in gates.values()),
        selection_input_authorized=role != "local_validation", local_selection_authorized=False,
        status="COMPLETE" if score is not None else "UNDEFINED_INPUT_RETAINED", independent=False)


def verify_reconciliation(rows, cell):
    whole, *annual = rows
    if [r["environment_id"] for r in rows] != ["whole_path", *ANNUAL]:
        raise ValueError("producer must return full plus three actual annual views")
    for name, retained in (("net_return", "total_return"), ("drawdown", "max_drawdown"),
                           ("sharpe", "sharpe"), ("daily_loss_es", "daily_loss_es"), ("economic_utility", "economic_utility")):
        close(custody.metric(whole, name), json.loads(cell.original_metrics_json)[retained], "whole-path " + name)
    close(sum(r["money_pnl"] for r in annual), whole["money_pnl"], "annual monetary PnL", tolerance=1e-8)
    returns = [custody.metric(r, "net_return") for r in annual]
    if all(r is not None for r in returns):
        close(math.prod(1+r for r in returns)-1, custody.metric(whole, "net_return"), "annual compounded net return")
    previous = cell.contract.baseline_equity
    for row in annual:
        close(row["environment_baseline"]["equity"], previous, "actual carried annual entry")
        previous += row["money_pnl"]
    for name in ("fees", "funding", "turnover"):
        whole_metric = next(m for m in whole["metrics"] if m["metric_id"] == "mode5.panel."+name)
        if whole_metric["value"] is not None:
            close(sum(next(m["value"] for m in r["metrics"] if m["metric_id"] == "mode5.panel."+name) for r in annual),
                  whole_metric["value"], "annual " + name, tolerance=1e-8)
    if whole["fills"] is not None:
        if sum(r["fills"] for r in annual) != whole["fills"] or sum(r["closed_campaigns"] for r in annual) != whole["closed_campaigns"]:
            raise ValueError("annual fill/closure attribution mismatch")


def analyze(registration, lane, attempt):
    original = sealed_json(registration["original_registration"])
    inputs, _ = custody.load_inputs(original)
    requests = sealed_json(registration["requests"])
    pool = indexed(original["protected_prior_files"])
    p = numeric_owner()
    contract = p.ReportingContractV1(**registration["original_reporting_contract"])
    policy = registration["common_aggregate"]
    if validate_common(policy) != registration["common_aggregate_identity"]:
        raise ValueError("common annual policy seal changed")
    utility = p.UtilityPolicy(**policy["utility"])
    cutoff = p._ns(registration["created_at"])
    outputs, aggregate_rows, closures, counts = {}, [], [], {}
    for alpha, (result, probes, evaluations, _) in inputs.items():
        preference_check(result)
        for record in probes["critical_sources"]:
            custody.checked(record)
        reducer = next((r for r in probes["critical_sources"] if Path(r["path"]).name == "reduction.py"), None)
        if alpha == "rsi":
            tree = ast.parse(sealed_bytes(reducer))
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "expected_shortfall"]
            if len(calls) != 1 or ast.literal_eval(calls[0].args[1]) != .95:
                raise ValueError("original daily ES confidence differs")
        evaluations = {r["index"]: r for r in evaluations}
        if set(evaluations) != {e["index"] for e in probes["executions"]} or len(evaluations) != len(probes["executions"]):
            raise ValueError("all registered executions required, no survivor subset")
        annual_rows, whole_rows, overlaps = [], [], []
        for execution in probes["executions"]:
            evaluation = evaluations[execution["index"]]
            request_by_year = registered_request(requests[alpha]["annual_view_requests"], execution, evaluation)
            cell = probe_cell(execution, evaluation, probes, pool, contract, cutoff)
            rows = [row_metadata(r) for r in p.continuous_annual_rows(cell, utility_policy=utility, backend="python")]
            verify_reconciliation(rows, cell)
            for row in rows:
                row.update(alpha=alpha, execution_index=execution["index"], center=execution["center"],
                    role=execution["role"], source_cell=evaluation["cell"], source_path=evaluation["paths"],
                    common_aggregate_identity=registration["common_aggregate_identity"])
            whole_rows.append(rows[0])
            annual_rows.extend(rows[1:])
            aggregate_rows.append(dict(alpha=alpha, center=execution["center"], execution_index=execution["index"],
                **annual_aggregate(rows[1:], policy, role=execution["role"], expected_candidate=execution["candidate_id"],
                                   expected_execution=cell.provenance.execution_id)))
            for row in rows[1:]:
                closures.append(dict(alpha=alpha, execution_index=execution["index"], role=execution["role"],
                    candidate_id=execution["candidate_id"], environment_id=row["environment_id"],
                    request_identity=custody.digest(request_by_year[row["environment_id"]]), row_identity=custody.digest(row),
                    status="VERIFIED_ANNUAL_VIEW", daily_count=row["calendar_days"],
                    required_metric_bindings=dict(daily_count="calendar_days; raw_account_metrics.period.count (when qualified)",
                                                  other="mode5.panel.{economic_utility,net_return,drawdown,daily_loss_es}")))
        grid = custody.grid_for(result)
        for center in probes["centers"]:
            cid = center["candidate_id"]
            center_rows = [grid[cid, year] for year in ANNUAL]
            if any(r["index"] != center["panel_index"] for r in center_rows):
                raise ValueError("original center annual index mismatch")
            aggregate_rows.append(dict(alpha=alpha, center=center["center"], panel_index=center["panel_index"],
                **annual_aggregate(center_rows, policy, role="center", expected_candidate=cid)))
            role_sets = {role: {r["point"]["effective_json"] for n in probes["neighborhoods"]
                if n["center"] == center["center"] and n["role"] == role for r in n["rows"] if r["status"] == "READY"}
                for role in ROLES}
            overlaps.append(dict(center=center["center"], selection_ready=len(role_sets[ROLES[0]]),
                validation_ready=len(role_sets[ROLES[1]]), ready_overlap=len(role_sets[ROLES[0]] & role_sets[ROLES[1]]),
                held_distinct=len(role_sets[ROLES[1]]-role_sets[ROLES[0]]), independent=False, clean_oos=False))
        expected = 465 if alpha == "rsi" else 174
        if len(annual_rows) != expected or sum(o["ready_overlap"] for o in overlaps) != (42 if alpha == "rsi" else 13):
            raise ValueError("annual request cardinality or dependent role overlap changed")
        counts[alpha] = dict(annual_views=len(annual_rows), whole_path_checks=len(whole_rows), centers=len(probes["centers"]),
            roles=dict(Counter(row["role"] for row in annual_rows)), overlap=overlaps)
        outputs[alpha] = custody.write_new(lane / f"{alpha}_annual_views_{attempt}.json", dict(
            schema="m5111_probe_annual_views_v1", status="PASS", annual_rows=annual_rows, whole_path_checks=whole_rows,
            registration=custody.pin(lane / "registration_01.json"), common_aggregate_identity=registration["common_aggregate_identity"],
            counts=counts[alpha], financial_executions=0, clean_oos=False))
    if len(closures) != 639 or len({(r["alpha"], r["execution_index"], r["environment_id"]) for r in closures}) != 639:
        raise ValueError("all and only 639 annual requests must close")
    aggregates = custody.write_new(lane / f"common_aggregates_{attempt}.json", dict(
        schema="m5111_common_annual_aggregate_inputs_v1", policy=policy, aggregate_identity=validate_common(policy),
        rows=aggregate_rows, local_analysis_status=registration["local_analysis_status"], missing_policy=MISSING_LOCAL,
        canonical_local_mean_substitution_authorized=False, annual_local_decision=None, full_panel_local_contest=False))
    return custody.write_new(lane / f"closure_{attempt}.json", dict(schema="m5111_annual_view_request_closure_v1",
        created_at=custody.now(), status="PASS", requests=registration["requests"], outputs=outputs, aggregates=aggregates,
        verified_annual_views=639, request_closures=closures, counts=counts,
        missing_local_policy=MISSING_LOCAL, annual_local_decision=None, future_neighbor_account_requests=195,
        future_neighbor_annual_views=585, covariance_design_requests=4, financial_executions=0, builds=0,
        full_panel_local_contest=False, full_goal_complete=False))


def verify_registration(registration):
    original = sealed_json(registration["original_registration"])
    verified = custody.verify_prior(original)
    for record in [*registration["prior_step_files"], *registration["software"]]:
        custody.checked(record)
    return dict(original=verified, prior_step_files_verified=len(registration["prior_step_files"]),
                software_verified=len(registration["software"]), hash_failures=0)


def run(lane, attempt):
    if len(attempt) != 2 or not attempt.isdigit():
        raise ValueError("two-digit append-only attempt required")
    registration_pin = custody.pin(lane / "registration_01.json")
    registration = sealed_json(registration_pin)
    before = custody.resources(lane)
    if before["free_bytes"] < registration["budget"]["reserve_bytes"] + 160*MIB:
        raise ValueError("reserve plus incremental budget required")
    for name in THREADS:
        if os.environ.get(name) != "1":
            raise ValueError("single-thread controlled numeric environment required: " + name)
    previous = [custody.pin(p) for p in sorted(lane.rglob("*")) if p.is_file()]
    prereg = custody.write_new(lane / f"cold_run_registration_{attempt}.json", dict(created_at=custody.now(),
        registration=registration_pin, source=custody.pin(__file__), tests=custody.pin(ROOT / "tests/test_mode5_probe_views.py"),
        previous_lane_files=previous, numeric_threads={name: os.environ[name] for name in THREADS},
        command=registration["tests"], financial_imports_authorized=False, financial_launches_authorized=False))
    status, error, closure, verified = "FAIL", None, None, None
    try:
        verified = verify_registration(registration)
        closure = analyze(registration, lane, attempt)
        test_env = os.environ | {"PROBE_VIEW_FIXTURE_ROOT": str(lane / f"cold-fixtures-{attempt}")}
        tests = subprocess.run(registration["tests"], env=test_env, text=True, capture_output=True, check=False)
        custody.write_new(lane / f"tests_{attempt}.json", dict(command=registration["tests"],
            returncode=tests.returncode, stdout=tests.stdout, stderr=tests.stderr))
        if tests.returncode:
            raise ValueError("focused cold suite failed; log retained")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        custody.write_new(lane / f"failure_{attempt}.json", dict(created_at=custody.now(), error=error,
            traceback=traceback.format_exc(), phase_pass=False))
    finally:
        try:
            verified = verify_registration(registration)
            for record in previous:
                custody.checked(record)
            custody.checked(sealed_json(prereg)["tests"])
            custody.checked(sealed_json(prereg)["source"])
            if any(forbidden(name) for name in sys.modules):
                raise ValueError("prohibited runtime module loaded")
        except Exception as exc:
            status, error = "FAIL", str(exc)
        retained = [custody.pin(p) for p in sorted(lane.rglob("*")) if p.is_file()]
        retained_bytes = sum(p["bytes"] for p in retained)
        after = custody.resources(lane)
        if retained_bytes >= 128*MIB or after["free_bytes"] < 5*1024**3:
            status, error = "FAIL", "retained/reserve budget failed"
        cleanup = custody.write_new(lane / f"cleanup_{attempt}.json", dict(created_at=custody.now(), status=status,
            error=error, registration=registration_pin, cold_run_registration=prereg, closure=closure,
            prior_custody=verified, retained_manifest=retained, retained_bytes_before_receipt=retained_bytes,
            retained_cap_pass=retained_bytes < 128*MIB, reserve_pass=after["free_bytes"] >= 5*1024**3,
            resources_before=before, resources_after=after, deleted_paths=[], deleted_bytes=0, scratch_bytes=0,
            preserved_environment=".maturin/qms08/release-regression-v1", financial_executions=0, builds=0,
            imported_quantbt_modules=sorted(name for name in sys.modules if name.startswith("quantbt")),
            observed_free_byte_change=after["free_bytes"]-before["free_bytes"], observed_change_attributable=False))
    if status != "PASS":
        raise ValueError(error)
    return dict(status=status, closure=closure, cleanup=cleanup, retained_bytes=retained_bytes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "run"))
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--lane", type=Path, required=True)
    parser.add_argument("--attempt", default="01")
    args = parser.parse_args()
    result = register(args.parent, args.lane) if args.command == "register" else run(args.lane.resolve(), args.attempt)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
