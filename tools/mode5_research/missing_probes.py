"""Cold missing-neighbor registration and an adapter to the original finance owner.

Registration imports no financial runtime. One fresh process owns one exact
request; account instrumentation delegates unchanged calls and bills returns,
not forecasts. Covariance fit requests are prerequisites, never account specs.
"""

from contextlib import contextmanager
from copy import deepcopy
import json
import math
import signal
from time import perf_counter

from tools.mode5_baseline.isolation import canonical_digest
from tools.mode5_research.feedback_observer import FeedbackObserver, FrozenPins, file_pin
from tools.mode5_research.jobs import Candidate, _safe, _seal, verify_pins


SCHEMA = "mode5.missing_selector_accounts.v1"
ROUTES = {"A-RSI": "unchanged pct_equity legacy and direct owner",
          "A-SC": "unchanged event_driven Python callback"}
BASE = dict(start="2021-01-01", stop="2024-01-01",
            account_mode="continuous_development_2021_2023", max_feedback_runs=4096)
EXTRA = {"alpha", "symbol", "params", "candidate_id", "design_id", "proposal_row",
         "parent_candidate_id", "parent_design_id", "parent_panel_index",
         "neighborhood_center", "probe_direction", "probe_radius", "probe_seed", "role"}
RECIPE = dict(selection_radius=.1, validation_radius=.12, selection_seed=732,
              validation_seed=733, minimum_radius=.05, rho=.2, tau=.001,
              minimum_cloud=5, cloud_radius=.25)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def effective_id(metadata, params):
    """Validate already-effective values, without recasting or repairing requests."""
    require(not metadata["constraints"] and not metadata["inactive"],
            "this adapter requires the frozen unconditional RSI/SC domains")
    specs = metadata["parameters"]
    require(set(params) == {s["name"] for s in specs}, "effective parameter roster differs")
    for spec in specs:
        value = params[spec["name"]]
        require(not spec["active_if"], "conditional domains require a new adapter")
        if spec["fixed"]:
            require(type(value) is type(spec["fixed_value"]) and value == spec["fixed_value"],
                    "fixed parameter changed")
        elif spec["categories"]:
            require(any(type(value) is type(v) and value == v for v in spec["categories"]),
                    "category/cast differs")
        else:
            require(type(value) in (int, float) and math.isfinite(value), "nonfinite parameter")
            require(spec["low"] <= value <= spec["high"], "parameter outside original domain")
            if spec["kind"] == "integer":
                require(type(value) is int, "integer must already have the original cast")
    return canonical_digest(dict(schema=canonical_digest(metadata), effective=params))


def collect_missing(bundle, parents, geometries):
    """Use only READY missing schema-floor rows, not panel/annual replay requests."""
    collected, covariance, seen = [], [], set()
    for key, alpha, symbol in (("rsi", "A-RSI", "ETHUSDT"), ("sc", "A-SC", "BTCUSDT")):
        manifest = bundle[key]["bounded_neighborhood_manifest"]
        design, metadata = parents[alpha], geometries[alpha]
        geometry_id = canonical_digest(metadata)
        require(manifest["parent_geometry_id"] == design["schema_id"] == geometry_id,
                "original domain identity differs")
        require(all(manifest["recipe"][k] == v for k, v in RECIPE.items()), "probe recipe changed")
        require(not manifest["launches_authorized"], "expected a cold, unlaunched request bundle")
        roster = [r for r in design["rows"] if r["admitted"]]
        require(len(roster) == 128 and len({r["candidate_id"] for r in roster}) == 128,
                "original parent roster differs")
        neighborhoods = {n["neighborhood_id"]: n for n in manifest["neighborhoods"]}
        require(len(neighborhoods) == len(manifest["neighborhoods"]), "duplicate neighborhood")
        require(manifest["request_count"] == len(manifest["executions"]), "request count differs")
        for entry in manifest["executions"]:
            request = deepcopy(entry["request"])
            require(set(request) == set(BASE) | EXTRA, "unexpected economic/request overrides")
            require(all(request[k] == v for k, v in BASE.items()), "development scope/budget changed")
            require(request["alpha"] == alpha and request["symbol"] == symbol, "original symbol differs")
            require(entry["request_sha256"] == canonical_digest(request), "exact request digest differs")
            require(entry["status"] == "MISSING_ACCOUNT_EVALUATION" and not entry["launch_authorized"],
                    "only genuinely missing cold requests may be registered")
            require(not entry["compatible_coordinate_role_matches"],
                    "reuse match requires an independent manifest/account qualification first")
            index = request["parent_panel_index"]
            require(type(index) is int and 0 <= index < len(roster), "parent index differs")
            require(request["parent_candidate_id"] == roster[index]["candidate_id"] and
                    request["parent_design_id"] == design["design_id"], "parent identity differs")
            require(request["candidate_id"] == effective_id(metadata, request["params"]),
                    "effective candidate identity differs")
            neighborhood = neighborhoods[request["design_id"]]
            require(neighborhood["original_index"] == index and
                    neighborhood["parent_candidate_id"] == request["parent_candidate_id"],
                    "neighborhood parent differs")
            row = next(r for r in neighborhood["rows"] if r["row_id"] == request["proposal_row"])
            require(row["status"] == "READY" and row["effective"] == request["params"] and
                    row["candidate_id"] == request["candidate_id"] and
                    row["direction"] == request["probe_direction"] and
                    row["execution_index"] == entry["index"], "frozen probe coordinate differs")
            role = request["role"]
            require(role in {"selection_probe", "local_validation"} and
                    role == entry["role"] == neighborhood["role"], "probe role differs")
            prefix = "selection" if role == "selection_probe" else "validation"
            require(request["probe_radius"] == neighborhood["radius"] == RECIPE[prefix + "_radius"] and
                    request["probe_seed"] == neighborhood["seed"] == RECIPE[prefix + "_seed"] and
                    request["neighborhood_center"] == entry["center"] == neighborhood["center"] and
                    request["design_id"] == entry["neighborhood_id"] and
                    request["proposal_row"] == entry["row_id"] and
                    request["candidate_id"] == entry["candidate_id"], "role/radius/seed identity differs")
            coordinate = (alpha, request["candidate_id"], role)
            require(coordinate not in seen, "duplicate effective coordinate/role")
            seen.add(coordinate)
            analysis = dict(schema=SCHEMA, request_sha256=canonical_digest(request),
                            annual_views=["2021", "2022", "2023"],
                            annual_policy="continuous_path_attribution_no_account_reset",
                            scope="supplementary_schema_floor_not_whole_128_local_qualification")
            collected.append(dict(cell_id=f"{key}-{index:03d}-{entry['index']:03d}",
                                  request=request, analysis_id=canonical_digest(analysis), analysis=analysis))
        for request in manifest["covariance_requests"]:
            index = request["original_index"]
            require(request["candidate_id"] == roster[index]["candidate_id"] and
                    request["geometry_id"] == geometry_id and
                    request["candidate_roster"] == [r["candidate_id"] for r in roster],
                    "covariance parent/roster differs")
            require(not request["financial_launch_authorized"] and
                    request["status"] == "FIT_AND_EXACT_DIRECTIONS_NOT_REGISTERED",
                    "covariance directions must not be implied by pending fit requests")
            require(all(request["recipe"][k] == RECIPE[k] for k in
                        ("rho", "tau", "cloud_radius", "minimum_cloud", "selection_radius",
                         "validation_radius", "selection_seed", "validation_seed")), "covariance policy differs")
            covariance.append(dict(alpha=alpha, exact_request=deepcopy(request),
                                   expected_design_id=canonical_digest(dict(alpha=alpha, request=request)),
                                   status="PENDING_MEASURED_FIT_AND_PRIOR_DIRECTION_SEAL",
                                   account_specs=[], financial_executions=0,
                                   inheritance="existing m5-06 geometry and active_neighbors_v1; no replacement RNG",
                                   gate="measure original eligible same-branch .25 cloud, full rank/minimum 5; "
                                        "seal exact role-specific directions before any union execution; "
                                        "sparse/singular fallback requires measured evidence"))
    return collected, covariance


def job_specs(entries, *, driver, registration, executable, cwd, pins, env=()):
    """Split cold specs by parent so each stays within jobs' bounded JSON reader."""
    pins = list(FrozenPins([*pins, file_pin(registration)]).records)
    groups = {}
    for entry in entries:
        request = entry["request"]
        required = ["result.json", "accounting_qualification.json", "actual/cell.json",
                    "actual/request.json", "actual/paths.npz", "actual/development_access.json"]
        if request["alpha"] == "A-SC":
            required += ["actual/fills.json", "actual/campaigns.json", "actual/order_events.json"]
        candidate = Candidate.create(entry["cell_id"], request,
            [str(executable), "-B", str(driver), "worker", "--registration", str(registration),
             "--registration-pin", json.dumps(file_pin(registration), sort_keys=True),
             "--cell", entry["cell_id"]], cwd, pins, result_file="result.json",
            required_outputs=tuple(required), env=(("M5_ATTEMPT", "attempt-01"), *env))
        base = entry["cell_id"].rsplit("-", 1)[0]
        part = 1
        group = base
        value = candidate.to_dict()
        while len(json.dumps([*groups.get(group, []), value], indent=2)) > 3 * 1024**2:
            require(groups.get(group), "one candidate exceeds bounded custody JSON cap")
            part += 1
            group = f"{base}-part{part:02d}"
        groups.setdefault(group, []).append(value)
    return groups


@contextmanager
def observe_original_accounts(finance, observer, alpha):
    """Only this worker's module globals are wrapped; original routes are untouched."""
    endpoint, engine = finance.QuantBTEndpoint, finance.BacktestEngine

    class Endpoint:
        def __init__(self, original, owner):
            self.original, self.owner = original, owner

        def backtest(self, *args, **kwargs):
            return observer.execute(self.owner, self.original.backtest, *args,
                                    bars=lambda result: len(result.equity), **kwargs)

    class Factory:
        @staticmethod
        def pct_equity(**kwargs):
            require(alpha == "A-RSI", "unexpected account owner")
            return Endpoint(endpoint.pct_equity(**kwargs), "RSI.pct_equity_owner")

        @staticmethod
        def event_driven(**kwargs):
            require(alpha == "A-SC" and kwargs.get("backend") == "python" and
                    kwargs.get("profile") == "audit", "original SC callback route required")
            return Endpoint(endpoint.event_driven(**kwargs), "SC.original_BarCloseBinding_owner")

    def direct(*args, **kwargs):
        require(alpha == "A-RSI", "unexpected direct account owner")
        return observer.execute("RSI.direct_owner", engine, *args,
                                bars=lambda instance: len(instance.result.equity), **kwargs)

    finance.QuantBTEndpoint, finance.BacktestEngine = Factory, direct
    try:
        yield
    finally:
        finance.QuantBTEndpoint, finance.BacktestEngine = endpoint, engine


def validate_parent(context, request):
    original = context.request(request["parent_panel_index"])
    require(all(original[k] == request[k] for k in (*BASE, "alpha", "symbol")),
            "immutable original request context differs")
    require(original["candidate_id"] == request["parent_candidate_id"] and
            original["design_id"] == request["parent_design_id"], "original parent differs")
    require(context.config == context.finance.CONFIG == context.finance.static_binding.CONFIG,
            "original financial economics differ")


def execute_one(entry, *, output, progress, pins, context_factory, qualify, validate_context,
                clock=perf_counter):
    """Dependency-injected for cold tests; production supplies original PreparedResearch.

    Failure receipts retain completed-owner lower bounds even when validation
    subsequently fails. SIGTERM/INT unwind; SIGKILL/power loss remain supervisor
    censored attempts, never resumable financial state.
    """
    output = _safe(output)
    output.mkdir(parents=True, exist_ok=False)
    started = clock()
    request = deepcopy(entry["request"])
    frozen = FrozenPins(pins)
    context = None
    signature = None
    economics = None

    def guard():
        frozen.verify()
        if context is not None:
            require(context.signature() == signature, "immutable development context mutated")
            require(canonical_digest(context.config) == economics and
                    context.config == context.finance.CONFIG == context.finance.static_binding.CONFIG,
                    "original account economics mutated")

    old_handlers = {}

    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"worker interrupted by signal {signum}")

    with FeedbackObserver(progress, guard=guard, clock=clock) as observer:
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                old_handlers[signum] = signal.signal(signum, interrupt)
            observer.emit("worker_started", request_sha256=canonical_digest(request))
            frozen.verify()
            context = observer.call("load_original_context", context_factory, request["alpha"])
            signature = context.signature()
            economics = canonical_digest(context.config)
            observer.call("validate_original_context", validate_context, context, request)
            validate_parent(context, request)
            actual = output / "actual"
            with observe_original_accounts(context.finance, observer, request["alpha"]):
                row = observer.call("original_finance_execute", context.finance.execute, deepcopy(request), actual)
            _seal(actual / "development_access.json", dict(witness=context.witness,
                allowed_stop=request["stop"], future_tape_opened=False, original_contract_preserved=True,
                finance_driver=file_pin(context.finance.__file__), shared_market_hash=signature,
                mutable_strategy_or_account_reused=False, exact_request_sha256=canonical_digest(request)))
            expected = 2 if request["alpha"] == "A-RSI" else 1
            require(observer.completed_passes == row["actual_execution_calls"] == expected and
                    observer.completed_account_bars == row["visited_bars"] == expected * 26280,
                    "returned account billing differs")
            require(row["request"] == request and row["route"] == ROUTES[request["alpha"]] and
                    row["scored_bars"] == 26280 and row["scored_days"] == 1095 and not row["clean_oos"],
                    "original route/request/calendar differs")
            qualification = observer.call("qualify_persisted_account", qualify, context, request, actual)
            require(qualification["status"] == "PASS", "account qualification failed")
            _seal(output / "accounting_qualification.json", qualification)
            guard()
            artifacts = [file_pin(p) for p in sorted(actual.iterdir()) if p.is_file()]
            artifacts.append(file_pin(output / "accounting_qualification.json"))
            result = dict(schema=SCHEMA, status="PASS", request=request,
                request_sha256=canonical_digest(request), analysis_id=entry["analysis_id"],
                analysis=entry["analysis"], analysis_status="REGISTERED_NOT_YET_ANALYZED",
                actual_execution_calls=observer.completed_passes, visited_bars=observer.completed_account_bars,
                accounting_qualification=qualification, artifact_pins=artifacts,
                elapsed_seconds=clock() - started, work=observer.summary(),
                future_tape_opened=False, clean_oos=False)
            _seal(output / "result.json", result)
            observer.emit("worker_complete", status="PASS")
            return result
        except BaseException as error:
            result = dict(schema=SCHEMA, status="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAULT",
                request=request, request_sha256=canonical_digest(request), analysis_id=entry["analysis_id"],
                actual_execution_calls=observer.completed_passes, visited_bars=observer.completed_account_bars,
                counts_are="completed_owner_lower_bounds; in-flight work unknown, not zero",
                elapsed_seconds=clock() - started, work=observer.summary(),
                error_type=type(error).__name__, error=str(error), accounting_qualification="NOT_QUALIFIED",
                artifact_pins=[file_pin(p) for p in sorted(output.rglob("*")) if p.is_file()])
            if not (output / "result.json").exists():
                _seal(output / "result.json", result)
            observer.emit("worker_fault", status=result["status"], error_type=type(error).__name__)
            raise
        finally:
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)


def verify_artifacts(result):
    """Cold verification is not adoption: jobs also requires its completed manifest."""
    require(result["status"] == "PASS" and result["accounting_qualification"]["status"] == "PASS",
            "unqualified completed path")
    require(canonical_digest(result["request"]) == result["request_sha256"], "request changed")
    verify_pins(result["artifact_pins"])


def read_json(path):
    return json.loads(_safe(path).read_text())
