"""Explicit cold readers for early controls and qualified empty-access evidence.

Caller pins and source approvals must be inherited from original sealed evidence,
not issued by this reader. No strategy, compiler, native library or account engine
is invoked. Early formats remain distinct from snapshot-bearing recovery_v1.
"""

from dataclasses import asdict, dataclass
from importlib import import_module
from io import BytesIO
from pathlib import Path
import pickle
import pickletools

import numpy as np
import pandas as pd

from quantbt import Fill, OrderSide
from quantbt.core.orders import OrderCommand
from quantbt.core.results import BacktestResultV2
from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, reduce_account
from tools.mode5_admission import conformance, ledger
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_diagnostics.identity import canonical, digest

from . import panels, recovery_cells as recovery
from .protocol import ResearchProtocol

EARLY_CONTROL_SCHEMA = "early_control_owner_admission_v1"
QUALIFIED_ACCESS_SCHEMA = "qualified_empty_access_admission_v1"
DISCLOSURE = (
    "Current-knowledge retrospective ingestion of original retained evidence. "
    "Not historical calibration, preregistration or independent OOS."
)
OWNER_LIMITATIONS = (
    "Original registered source identities are externally approved; early evidence has no retained source snapshots.",
    "Dated ledgers are cold projections of the sealed original owner, not originally retained JSON artifacts.",
    "Compiler, lifecycle and Python parity are retained original control claims; no financial reexecution or new runtime qualification.",
)
ACCESS_LIMITATIONS = (
    "Original access witness has no finance_driver field; finance authority is explicitly mapped from original recovery registration.",
    "Original terminal-audit and cold-account-verification dispositions are retained, not promoted by account reconciliation.",
)
_AUTHORITIES = {"original_registration", "design", "economic_config"}
_OWNER_TYPES = {
    "quantbt.core.results", "quantbt.core.types", "quantbt.core.orders", "quantbt.core.schema",
}
_PICKLE_GLOBALS = {
    "builtins": {"slice"},
    "datetime": {"timedelta", "timezone"},
    "numpy": {"dtype", "ndarray"},
    "numpy._core.multiarray": {"_reconstruct", "scalar"},
    "numpy.core.multiarray": {"_reconstruct", "scalar"},
    "pandas._libs.arrays": {"__pyx_unpickle_NDArrayBacked"},
    "pandas._libs.internals": {"_unpickle_block"},
    "pandas._libs.tslibs.timestamps": {"_unpickle_timestamp"},
    "pandas.core.arrays.datetimes": {"DatetimeArray"},
    "pandas.core.dtypes.dtypes": {"DatetimeTZDtype"},
    "pandas.core.frame": {"DataFrame"},
    "pandas.core.indexes.base": {"Index", "_new_Index"},
    "pandas.core.indexes.datetimes": {"DatetimeIndex", "_new_DatetimeIndex"},
    "pandas.core.indexes.range": {"RangeIndex"},
    "pandas.core.internals.managers": {"BlockManager", "SingleBlockManager"},
    "pandas.core.series": {"Series"},
    "quantbt.core.orders": {"Fill", "OrderCommand", "OrderAction", "OrderActivationPolicy", "Trade", "OrderIntent"},
    "quantbt.core.results": {"BacktestResultV2"},
    "quantbt.core.schema": {"LiquiditySide", "OrderSide", "OrderType", "TimeInForce"},
}


@dataclass(frozen=True)
class EarlyCell(panels.VerifiedCell):
    """Shared panel account with its actual older schema and explicit coverage."""

    reader_schema: str
    source_limitations: tuple[str, ...]
    ledger_origin: str
    native_account_calls: int
    python_oracle_calls: int
    native_feedback_calls: int | None
    normal_native_calls: int | None

    @property
    def actual_execution_calls(self):
        return self.native_account_calls + self.python_oracle_calls

    @property
    def visited_bars(self):
        return self.actual_execution_calls * ((self.stop_ns-self.start_ns)//panels.HOUR_NS)

    @property
    def execution_work_metadata(self):
        full_passes = (self.normal_native_calls + self.python_oracle_calls
                       if self.reader_schema == EARLY_CONTROL_SCHEMA
                       else self.actual_execution_calls)
        return dict(visited_bars=self.visited_bars,
            reason=("ORIGINAL_FULL_MARKET_REQUEST_BARS"
                    if self.reader_schema == EARLY_CONTROL_SCHEMA
                    else "ORIGINAL_QUALIFIED_FULL_ACCOUNT_PASSES"),
            full_account_passes=full_passes,
            full_account_visited_bars=full_passes
                * ((self.stop_ns-self.start_ns)//panels.HOUR_NS),
            native_feedback_calls=self.native_feedback_calls,
            visited_bar_unit="submitted full market request bars, not internal kernel steps",
            internal_kernel_steps=None)

    @property
    def oracle_coverage(self):
        return "RETAINED_ORIGINAL_PYTHON_CONTROL_NO_NEW_EXECUTION"


def _require(condition, message):
    recovery._require(condition, message)


def _roster(pins):
    result = {}
    for pin in pins:
        recovery._pin(pin)
        _require(pin["path"] not in result or result[pin["path"]] == pin,
                 "conflicting original source identities")
        result[pin["path"]] = dict(pin)
    _require(bool(result), "nonempty original source roster required")
    return result


def supervisor_sibling_pins(supervisor_pin, cell_path, *, cutoff_ns):
    """Select original seals from the caller-pinned supervisor manifest."""
    supervisor = recovery._json(supervisor_pin, cutoff_ns)
    _require(supervisor["status"] == "PASS_NO_DELETION" and supervisor["fault"] is None
             and supervisor["all_owned_workers_reaped"] is True
             and supervisor["live_owned_financial_workers"] == 0
             and supervisor["source_market_written"] is False
             and supervisor["shared_active_scratch_touched"] is False
             and supervisor["deleted_paths"] == [], "original supervisor closure required")
    roster = _roster(supervisor["retained_manifest"])
    parent = Path(cell_path).resolve().parent
    result = {}
    for key, filename in (("cell", "cell.json"), ("request", "request.json"),
                          ("access", "development_access.json"), ("paths", "paths.npz"),
                          ("campaigns", "campaigns.json"), ("fills", "fills.json")):
        path = str(parent / filename)
        _require(path in roster, "original supervisor sibling seal missing")
        result[key] = roster[path]
    return result


def _inputs(path, pins, names, sibling_names, cutoff):
    _require(type(cutoff) is int and cutoff >= panels._ns("2024-01-01"),
             "explicit retrospective knowledge cutoff required")
    _require(names <= pins.keys(), "complete external original inventory required")
    supplied = {name: dict(pins[name]) for name in names}
    for pin in supplied.values():
        recovery._pin(pin)
    parent = Path(path).resolve().parent
    for name, filename in sibling_names.items():
        _require(Path(supplied[name]["path"]) == parent / filename, "orphan older-schema artifact")
    for filename in ("failure.json", "FAIL.json", "censored.json"):
        _require(not (parent / filename).exists(), "failed/censored evidence cannot be admitted")
    return supplied, parent


def _scope(request, pins, contract, cutoff, expected_index):
    original, design, config = (recovery._json(pins[name], cutoff) for name in
                                ("original_registration", "design", "economic_config"))
    protocol = ResearchProtocol(**original["protocol"])
    _require(original["protocol_id"] == protocol.identity
             and original["financial_outcomes_used_to_choose_design"] is False
             and original["forward_selection"] is False
             and (protocol.preload_start, protocol.development_start, protocol.development_stop)
                 == ("2020-01-01", "2021-01-01", "2024-01-01")
             and panels._ns(original["created_at"]) <= cutoff, "original continuous protocol required")
    _require(request["alpha"] == design["alpha"] and request["design_id"] == design["design_id"]
             and request["symbol"] == original["symbols"][request["alpha"]]
             and request["role"] == "NEUTRAL_BROAD_DISCOVERY"
             and request["account_mode"] == "continuous_development_2021_2023"
             and request["start"] == protocol.development_start and request["stop"] == protocol.development_stop
             and type(request["max_feedback_runs"]) is int and request["max_feedback_runs"] == 4096,
             "original request role/range/feedback contract differs")
    admitted = [row for row in design["rows"] if row["admitted"] is True]
    _require(type(expected_index) is int and 0 <= expected_index < len(admitted),
             "explicit original admitted index required")
    proposal = admitted[expected_index]
    _require(type(proposal["row_id"]) is int and type(request["proposal_row"]) is int
             and proposal["row_id"] == request["proposal_row"] and proposal["status"] == "READY"
             and proposal["role"] == "exploration" and proposal.get("duplicate_of") is None
             and proposal["candidate_id"] == request["candidate_id"]
             and canonical(proposal["effective"]) == canonical(request["params"])
             and sum(row["row_id"] == proposal["row_id"] for row in design["rows"]) == 1,
             "original admitted index/effective payload differs")
    for key in ("alpha", "candidate_id", "design_id", "symbol"):
        recovery._public_id(request[key])
    recovery._public_id(proposal["direction"])
    start, stop = panels._ns(request["start"]), panels._ns(request["stop"])
    account = config["account"]
    for key in ("initial_capital", "contract_size", "fee_rate", "leverage"):
        _require(type(account[key]) in (float, int) and np.isfinite(account[key])
                 and (account[key] >= 0 if key == "fee_rate" else account[key] > 0),
                 "original finite account economics required")
    _require(isinstance(contract, ReportingContractV1), "original typed reporting contract required")
    expected = ReportingContractV1(scope="full", unit="account_period", currency=contract.currency,
        baseline_equity=account["initial_capital"], baseline_time_ns=start-panels.HOUR_NS,
        scope_end_ns=stop-panels.HOUR_NS, sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
    _require(contract == expected and config["timeframe"] == "1h"
             and config["execution_contract"] == "event_lifecycle_v3_next_open"
             and config["terminal_policy"] == "mark_only_no_hidden_flatten"
             and account["use_funding"] is False, "original reporting/economic/clock contract differs")
    return protocol, proposal, config


def _market(approval, roster, cutoff):
    _require(roster.get(approval["path"]) == approval, "original market metadata authority differs")
    witness = recovery._json(approval, cutoff)["development"]
    _require(roster.get(witness["path"]) == witness, "original development witness differs")
    return witness


def _project_fills(rows, request):
    projected, objects = [], []
    start, stop = panels._ns(request["start"]), panels._ns(request["stop"])
    _require(isinstance(rows, (list, tuple)), "dated original fills required")
    for row in rows:
        stamp = panels._ns(row["timestamp"])
        _require(start <= stamp < stop and (stamp-start) % panels.HOUR_NS == 0
                 and row["symbol"] == request["symbol"] and row["side"] in {"buy", "sell"}
                 and row["liquidity"] in {"maker", "taker"}, "original fill semantics/calendar differs")
        recovery._public_id(row["order_id"])
        for key in ("qty", "price", "fee"):
            _require(type(row[key]) in (int, float) and np.isfinite(row[key])
                     and (row[key] >= 0 if key == "fee" else row[key] > 0), "invalid original fill economics")
        projected.append({key: row[key] for key in
                          ("timestamp", "symbol", "side", "qty", "price", "fee", "order_id", "liquidity")})
        objects.append(Fill(timestamp=pd.Timestamp(row["timestamp"]), symbol=row["symbol"],
            order_id=row["order_id"], side=OrderSide.BUY if row["side"] == "buy" else OrderSide.SELL,
            qty=row["qty"], price=row["price"], fee=row["fee"]))
    return projected, objects


def _account(pins, witness, request, config, contract, fills, cutoff, schema):
    start, stop = panels._ns(request["start"]), panels._ns(request["stop"])
    count, days = (stop-start)//panels.HOUR_NS, (stop-start)//panels.DAY_NS
    with np.load(BytesIO(recovery._sealed(pins["paths"], cutoff)), allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    required = {"times_ns", "equity", "positions", "fees", "funding", "turnover", "margin", "daily_returns"}
    _require(required <= arrays.keys(), "full original account streams required")
    times = arrays["times_ns"]
    _require(times.dtype == np.dtype("int64") and times.shape == (count,)
             and np.array_equal(times, np.arange(start, stop, panels.HOUR_NS)), "full hourly calendar required")
    for key in required - {"times_ns"}:
        values = arrays[key]
        shape = (days,) if key == "daily_returns" else (2*count,) if key == "margin" else (count,)
        _require(values.shape == shape and values.dtype.kind in "fiu" and np.isfinite(values).all(),
                 "finite full original account streams required")
    coverage = ReportingCoverageV1(result_identity=pins["paths"]["sha256"], producer=schema,
        profile="compact", ledger="omitted", retained_rows=0, dropped_rows=0,
        reason="original or owner-derived dated ledgers separately reconciled")
    observations = AccountObservations(times_ns=times, equity=arrays["equity"], coverage=coverage)
    observations = observations.with_derived_returns(contract, partial_mask=np.zeros(days, dtype=bool),
        witness="original continuous hourly marks; retrospective observed UTC account")
    _require(np.allclose(observations.returns.values, arrays["daily_returns"], rtol=0, atol=1e-12),
             "original daily account authority differs")
    report = reduce_account(observations, contract, backend="python")
    market = pd.read_csv(BytesIO(recovery._sealed(witness, cutoff)), compression="gzip",
                         usecols=["datetime", "symbol", "close"])
    calendar = pd.DatetimeIndex(pd.to_datetime(market["datetime"], utc=True))
    _require(np.array_equal(calendar.asi8, np.arange(panels._ns("2020-01-01"), stop, panels.HOUR_NS))
             and market["symbol"].eq(request["symbol"]).all(), "original market/preload calendar differs")
    close = market["close"].to_numpy(dtype=float)[-count:]
    projected, objects = _project_fills(fills, request)
    account = config["account"]
    actual = ledger.reconcile_fills(pd.DatetimeIndex(pd.to_datetime(times, utc=True)), close, objects,
        initial_capital=account["initial_capital"], contract_size=account["contract_size"], fee_rate=account["fee_rate"])
    for key in ("equity", "positions", "fees", "turnover"):
        _require(np.allclose(arrays[key], getattr(actual, key), rtol=0, atol=1e-8),
                 "original fill/account reconciliation differs")
    _require(not np.any(arrays["funding"]), "original zero-funding account required")
    campaigns = dict(closed=list(actual.closed_campaigns), open=list(actual.open_campaigns))
    pnl = sum(row["net_pnl"] for row in campaigns["closed"])
    pnl += sum(row["marked_net_pnl"] for row in campaigns["open"])
    _require(np.isclose(pnl, arrays["equity"][-1]-contract.baseline_equity, rtol=0, atol=1e-8),
             "original closed/open PnL differs")
    return arrays, observations, report, campaigns, projected, close


def _metrics(metrics, report, request):
    result = recovery._public_metrics(metrics)
    for source, target in (("account.total_return", "total_return"), ("drawdown.max_depth", "max_drawdown"),
                           ("period.sharpe", "sharpe")):
        expected, observed = report.metric(source).value, result[target]
        _require((expected is None and observed is None) or
                 (expected is not None and type(observed) in (int, float)
                  and np.isfinite(observed) and np.isclose(expected, observed, rtol=0, atol=1e-10)),
                 "original reported account metric differs")
    _require(result["daily_count"] == 1095 and result["account_mode"] == request["account_mode"],
             "original daily metric/report scope differs")
    return result


class _OwnerUnpickler(pickle.Unpickler):
    def __init__(self, stream):
        _require(type(stream) is BytesIO, "sealed in-memory original owner required")
        self._stream = stream
        super().__init__(stream)

    def load(self):
        start = self._stream.tell()
        # Cached pickle extensions bypass find_class, including its allowlist.
        for opcode, _, _ in pickletools.genops(self._stream):
            _require(opcode.name not in {"EXT1", "EXT2", "EXT4", "PERSID", "BINPERSID"},
                     "external original owner pickle reference rejected")
        self._stream.seek(start)
        return super().load()

    def find_class(self, module, name):
        _require(name in _PICKLE_GLOBALS.get(module, ()), "unsupported original owner pickle global")
        return getattr(import_module(module), name)

    def persistent_load(self, pid):
        raise ValueError("external original owner pickle reference rejected")


def _owner(pin, type_pins, cutoff):
    _require(set(type_pins) == _OWNER_TYPES, "explicit current typed-owner source approvals required")
    for name, approved in type_pins.items():
        _require(Path(approved["path"]).resolve() == Path(import_module(name).__file__).resolve(),
                 "typed owner source identity differs")
        recovery._sealed(approved, cutoff)
    _require(pin["bytes"] <= 32*1024**2, "bounded original owner required")
    stream = BytesIO(recovery._sealed(pin, cutoff))
    value = _OwnerUnpickler(stream).load()
    _require(stream.read(1) == b"" and type(value) is tuple and len(value) == 2
             and type(value[0]) is BacktestResultV2 and type(value[1]) is tuple
             and all(type(command) is OrderCommand for command in value[1]), "original owner/result tuple required")
    return value


def _cell(request, proposal, pins, witness, approvals, contract, cutoff, study, revision,
          arrays, observations, campaigns, fills, metrics, status, role, schema, limitations,
          native, python, feedback, normal, route, execution_id):
    recovery._public_id(study)
    recovery._public_id(revision)
    refs = {name: pin["sha256"] for name, pin in pins.items()}
    refs.update({"approved_source_"+str(i): pin["sha256"] for i, pin in
                 enumerate(sorted(approvals.values(), key=lambda p: p["path"]))})
    refs["development_data"] = witness["sha256"]
    if schema == EARLY_CONTROL_SCHEMA:
        refs.update(derived_campaigns=digest(campaigns), derived_fills=digest(fills))
    else:
        refs.update({"source."+name: approvals[name]["sha256"]
                     for name in ("alpha_source", "finance_driver", "orchestrator")})
    provenance = panels.CandidateProvenance(study, revision, request["alpha"], request["candidate_id"],
        digest(proposal["requested"]), digest(proposal["effective"]), proposal["direction"],
        (proposal["row_id"],), execution_id, request["design_id"], request["symbol"], role,
        DISCLOSURE + " " + " ".join(limitations), panels._ns("2020-01-01"), panels._ns(request["stop"]),
        cutoff, cutoff, route, tuple(sorted(refs.items())))
    buffers = tuple(FrozenBuffer.from_array(key, arrays[key]) for key in ("positions", "fees", "funding", "turnover"))
    return EarlyCell(provenance, panels._ns(request["start"]), panels._ns(request["stop"]), contract,
        observations, buffers, canonical(campaigns), canonical(fills), canonical(metrics), status, None,
        schema, limitations, "SEALED_OWNER_DERIVED" if schema == EARLY_CONTROL_SCHEMA else "ORIGINAL_SUPERVISOR_JSON",
        native, python, feedback, normal)


def load_early_control_cell(result_path, *, artifact_pins, approved_source_pins,
                            approved_owner_type_pins, expected_candidate_index,
                            contract, cutoff_ns, study_id, diagnostic_revision):
    """Read externally approved early full controls, including their original owner.

    Required seals: result, worker_registration, original_registration, design,
    economic_config, native_gate, paths, owner. Source approvals cover the whole
    original worker roster, including conformance/ledger used for cold projection.
    Historical helper identities may outlive live files; this is disclosed, not
    a claim that missing snapshots have been recovered. Typed-owner source pins
    separately authorize the current four public QuantBT serialization modules.
    """
    names = _AUTHORITIES | {"result", "worker_registration", "native_gate", "paths", "owner"}
    pins, parent = _inputs(result_path, artifact_pins, names,
        {"result": "result.json", "worker_registration": "registration.json", "paths": "paths.npz",
         "owner": "actual_owner.pkl"}, cutoff_ns)
    _require(Path(result_path).resolve() == Path(pins["result"]["path"]), "original result identity differs")
    result, worker = (recovery._json(pins[name], cutoff_ns) for name in ("result", "worker_registration"))
    _require(result["status"] == recovery.RECOVERY_STATUS and result["original_compiler_parity"] is True
             and result["typed_lifecycle_terminal_parity"] is True and result["future_tape_opened"] is False
             and result["clean_oos"] is False and result["panel_complete"] is False
             and result["paths"] == pins["paths"] and result["owner"] == pins["owner"]
             and "registration" not in result and "source_snapshots" not in worker,
             "completed original early control schema required")
    _require(worker["control"] is True and worker["python_oracle_calls_planned"] == 1
             and type(worker["python_oracle_calls_planned"]) is int
             and worker["guard_policy"] == "boundary_full_hash_v1" and worker["methodology_changed"] is False
             and worker["native_gate"] == pins["native_gate"] and worker["request"] == result["request"],
             "original early control registration differs")
    request = result["request"]
    protocol, proposal, config = _scope(request, pins, contract, cutoff_ns, expected_candidate_index)
    roster = _roster(worker["pins"])
    approvals = {name: dict(pin) for name, pin in approved_source_pins.items()}
    _require({"alpha_source", "finance_driver", "recovery_driver", "market_metadata", "conformance", "ledger"}
             <= approvals.keys(), "external early-control source approvals required")
    gate = recovery._json(pins["native_gate"], cutoff_ns)
    _require(gate["status"] == "PASS", "qualified original native gate required")
    native = gate["artifact"]
    for pin in [native, *(pins[name] for name in _AUTHORITIES), *approvals.values()]:
        recovery._pin(pin)
        _require(roster.get(pin["path"]) == pin, "original worker/caller source authority differs")
    recovery._sealed(native, cutoff_ns)
    for name, module in (("conformance", conformance), ("ledger", ledger)):
        _require(Path(approvals[name]["path"]).resolve() == Path(module.__file__).resolve(),
                 "cold projection helper source differs")
        recovery._sealed(approvals[name], cutoff_ns)
    witness = _market(approvals["market_metadata"], roster, cutoff_ns)
    allowed = _roster([native, witness, *(pins[name] for name in _AUTHORITIES), *approvals.values()])
    _require(roster == allowed, "orphan/unapproved early worker source identity")
    feedback, normal, python = (recovery._count(result[key], minimum) for key, minimum in
        (("native_feedback_calls", 1), ("final_native_calls", 1), ("python_oracle_calls", 0)))
    _require(normal == 2 and python == 1 and recovery._count(result["bar_steps"]) ==
             26280 + recovery._count(result["bar_retries"]), "complete original control/call coverage required")
    _require(type(result["accounting_residual"]) in (int, float)
             and np.isfinite(result["accounting_residual"]) and 0 <= result["accounting_residual"] <= 1e-8,
             "original accounting qualification differs")
    _require(np.isfinite([result["wall_seconds"], result["peak_rss_mib"]]).all()
             and 0 <= result["wall_seconds"] <= worker["cap_seconds"]
             and 0 <= result["peak_rss_mib"] <= protocol.worker_rss_cap_bytes/1024**2,
             "original resource coverage differs")
    owner, commands = _owner(pins["owner"], approved_owner_type_pins, cutoff_ns)
    _require(conformance.result_signature(owner) == result["result_hash"]
             and len(commands) == recovery._count(result["command_count"]), "original owner/lifecycle identity differs")
    raw_fills = conformance.representation(conformance.chronological_fills(owner))
    arrays, observations, report, campaigns, fills, close = _account(
        pins, witness, request, config, contract, raw_fills, cutoff_ns, EARLY_CONTROL_SCHEMA)
    times = arrays["times_ns"]
    for key in ("equity", "positions", "fees", "funding", "margin"):
        values = getattr(owner, key)
        _require(np.array_equal(values.index.asi8, times)
                 and np.array_equal(np.asarray(values).reshape(-1), arrays[key]), "owner/path prefix or stream differs")
    _require(np.array_equal(owner.diagnostics.index.asi8, times)
             and np.array_equal(np.asarray(owner.diagnostics.turnover).reshape(-1), arrays["turnover"])
             and np.array_equal(owner.closes.index.asi8, times)
             and np.array_equal(np.asarray(owner.closes).reshape(-1), close)
             and owner.symbols == [request["symbol"]]
             and owner.initial_capital == config["account"]["initial_capital"]
             and owner.leverage == config["account"]["leverage"]
             and owner.metadata["execution_contract_id"] == config["execution_contract"], "owner market/account identity differs")
    for key, count in (("fills", len(fills)), ("closed_campaigns", len(campaigns["closed"])),
                       ("open_campaigns", len(campaigns["open"]))):
        _require(recovery._count(result[key]) == count, "original control support differs")
    metrics = _metrics(result["metrics"], report, request)
    evidence = dict(pins)
    evidence.update({"owner_type_"+str(i): pin for i, pin in enumerate(approved_owner_type_pins.values())})
    return _cell(request, proposal, evidence, witness, approvals, contract, cutoff_ns, study_id, diagnostic_revision,
        arrays, observations, campaigns, fills, metrics, result["status"], "DEVELOPMENT_REVIEWED_RETROSPECTIVE",
        EARLY_CONTROL_SCHEMA, OWNER_LIMITATIONS, feedback+normal, python, feedback, normal,
        "incremental_actual_feedback_boundary_full_hash_v1", pins["result"]["sha256"])


def load_qualified_access_cell(cell_path, *, artifact_pins, approved_source_pins,
                               access_mapping, expected_candidate_index,
                               contract, cutoff_ns, study_id, diagnostic_revision):
    """Read the qualified zero-command schema without inventing an access field.

    In addition to original load_cell artifacts, supply economic_config,
    recovery_registration, qualified_receipt, supervisor_receipt, native_artifact.
    access_mapping explicitly supplies finance_driver, orchestrator and witness;
    each is checked against its actual original authority, never inserted into
    development_access.json. All sibling pins must come from supervisor_manifest.
    """
    names = _AUTHORITIES | {"cell", "request", "access", "paths", "campaigns", "fills", "resources", "analysis",
        "execution_budget", "recovery_registration", "qualified_receipt", "supervisor_receipt", "native_artifact"}
    pins, parent = _inputs(cell_path, artifact_pins, names,
        {"cell": "cell.json", "request": "request.json", "access": "development_access.json",
         "paths": "paths.npz", "campaigns": "campaigns.json", "fills": "fills.json"}, cutoff_ns)
    _require(Path(cell_path).resolve() == Path(pins["cell"]["path"]), "original cell identity differs")
    inherited = supervisor_sibling_pins(pins["supervisor_receipt"], cell_path, cutoff_ns=cutoff_ns)
    _require(all(pins[key] == pin for key, pin in inherited.items()), "caller/supervisor original seal differs")
    cell, request, access, registered, qualified, analysis, budget, resources = (
        recovery._json(pins[name], cutoff_ns) for name in
        ("cell", "request", "access", "recovery_registration", "qualified_receipt", "analysis", "execution_budget", "resources"))
    _require(cell["status"] == "PASS" and cell["clean_oos"] is False and cell["request"] == request
             and cell["path"] == pins["paths"] and qualified["cell"] == pins["cell"]
             and qualified["status"] == "PASS_CURRENT_ORIGINAL_NUMERIC_FILL_EVENT_PARITY"
             and registered["request"] == request and registered["original_request_unchanged"] is True
             and registered["source_schema_design_science_unchanged"] is True
             and registered["candidate_index"] == expected_candidate_index,
             "original qualified access/request authority differs")
    protocol, proposal, config = _scope(request, pins, contract, cutoff_ns, expected_candidate_index)
    approvals = {name: dict(pin) for name, pin in approved_source_pins.items()}
    _require({"alpha_source", "finance_driver", "orchestrator"} <= approvals.keys()
             and set(access_mapping) == {"finance_driver", "orchestrator", "witness"},
             "explicit original access/source mapping required")
    roster = _roster(registered["critical_sources"])
    _roster(approvals.values())
    _require(all(roster.get(pin["path"]) == pin for pin in approvals.values()),
             "orphan qualified source approval")
    for name in ("alpha_source", "finance_driver", "orchestrator"):
        _require(roster.get(approvals[name]["path"]) == approvals[name], "original qualified source differs")
        recovery._sealed(approvals[name], cutoff_ns)
    _require(access_mapping["finance_driver"] == approvals["finance_driver"] == registered["original_finance"]
             == qualified["original_finance"] and access_mapping["orchestrator"] == approvals["orchestrator"]
             == registered["controller_source"] == qualified["source"] == access["orchestrator"]
             and access_mapping["witness"] == access["witness"] and "finance_driver" not in access,
             "original access mapping differs; no manufactured access fields allowed")
    for key in ("qualified_recovery_identity", "qualified_empty_ledger_identity", "qualified_materialization_identity"):
        _require(qualified[key] == registered[key], "original qualification identity differs")
    _require(access["qualified_recovery_identity"] == registered["qualified_recovery_identity"]
             and access["future_tape_opened"] is False and access["original_contract_preserved"] is True
             and access["fresh_strategy_and_account"] is True and access["mutable_strategy_or_account_reused"] is False
             and access["allowed_stop"] == protocol.development_stop
             and access["signature_before"] == access["signature_after"] == registered["signature"]
             and access["shared_market_hash"] == access["signature_before"]["market"], "original access/signature differs")
    witness = access_mapping["witness"]
    _require(roster.get(witness["path"]) == witness and roster.get(pins["native_artifact"]["path"]) == pins["native_artifact"],
             "original development/native authority differs")
    recovery._sealed(pins["native_artifact"], cutoff_ns)
    for name in _AUTHORITIES:
        _require(roster.get(pins[name]["path"]) == pins[name], "original qualified design/economics authority differs")
    _require(resources["resource_protocol"] == asdict(protocol)
             and analysis["registration"] == pins["original_registration"]
             and analysis["execution_budget"] == pins["execution_budget"]
             and budget["original_registration"] == pins["original_registration"]
             and budget["original_resource_registration"] == pins["resources"]
             and analysis["role"] == "REVIEWED_EXPLORATORY_DEVELOPMENT"
             and analysis["clean_independent_claim"] is False and analysis["forward_snapshot_allowed"] is False
             and analysis["incomplete_matrix_is_complete_phase"] is False
             and analysis["screening"]["exact_sobol_claim"] is False and bool(analysis["outcome_timing_disclosure"]),
             "original exploratory analysis lineage differs")
    environment = analysis["environment_contract"]
    _require(environment["mode"] == "CONTINUOUS_PATH_ATTRIBUTION" and environment["account_reset"] is False
             and environment["annual_sharpe_average_is_whole_sharpe"] is False
             and environment["overlapping_families_independent"] is False
             and environment["annual_days"] == contract.annual_periods and environment["years"] == [2021, 2022, 2023],
             "original continuous attribution differs")
    for key in ("scientific_protocol_changed", "core_or_alpha_changed", "economic_outcome_filtering", "publication", "automatic_phase_promotion"):
        _require(budget[key] is False, "original execution extension changed science")
    _require(budget["numeric_threads_per_worker"] == 1 and type(budget["financial_workers"]) is int
             and budget["financial_workers"] >= 1, "original execution resources differ")
    for receipt in (analysis, budget):
        _require(panels._ns(receipt["created_at"]) <= cutoff_ns, "future original analysis authority")
        recovery._sealed(receipt["source"], cutoff_ns)
    fills = recovery._json(pins["fills"], cutoff_ns)
    original_campaigns = recovery._json(pins["campaigns"], cutoff_ns)
    _require(fills == [] and original_campaigns == {"closed": [], "open": []}, "qualified empty-ledger schema only")
    arrays, observations, report, campaigns, projected, _ = _account(
        pins, witness, request, config, contract, fills, cutoff_ns, QUALIFIED_ACCESS_SCHEMA)
    _require(canonical(campaigns) == canonical(original_campaigns)
             and cell["support"]["fills"] == cell["support"]["closed_campaigns"] == cell["support"]["open_campaigns"] == 0
             and cell["scored_bars"] == 26280 and cell["scored_days"] == 1095,
             "original qualified support/calendar differs")
    native, python = (recovery._count(qualified[key], 1) for key in
                      ("original_native_account_passes", "original_python_account_passes"))
    _require(native == 2 and python == 1 and qualified["added_financial_passes_for_supplement"] == 0
             and qualified["actual_account_passes"] == cell["actual_execution_calls"] == native+python
             and qualified["actual_account_bars"] == cell["visited_bars"] == 26280*(native+python),
             "original qualified account-call coverage differs")
    limitations = ACCESS_LIMITATIONS + (
        "Original terminal audit: " + recovery._public_id(qualified["terminal_audit_status"]),
        "Original cold account verification: " + recovery._public_id(qualified["cold_account_verification_status"]),
    )
    metrics = _metrics(cell["metrics"], report, request)
    return _cell(request, proposal, pins, witness, approvals, contract, cutoff_ns, study_id, diagnostic_revision,
        arrays, observations, campaigns, projected, metrics, cell["status"], analysis["role"],
        QUALIFIED_ACCESS_SCHEMA, limitations, native, python, None, None, cell["route"], cell["execution_key"])
