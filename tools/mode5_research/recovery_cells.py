"""Cold, explicitly pinned recovery ingestion; never an execution/requalification.

The caller supplies seals and approved source identities from qualified controls.
Source approval uses the original identities; retained snapshots are read instead
of requiring still-running or subsequently amended source files to be unchanged.
"""

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import Fill, OrderSide
from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, reduce_account
from tools.mode5_admission.ledger import reconcile_fills
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_statistics.contracts import MetricValue

from .panels import CandidateProvenance, VerifiedCell, DAY_NS, HOUR_NS, _ns, _read
from .protocol import ResearchProtocol

RECOVERY_STATUS = "PASS_FINAL_COMPILER_AND_ACCOUNTING"
RECOVERY_SCHEMA = "incremental_recovery_v1"
DISCLOSURE = (
    "Current-knowledge retrospective recovery ingestion; outcomes already exist. "
    "Not historical calibration, preregistration or independent OOS."
)
_REQUIRED = {
    "result", "worker_registration", "original_registration", "design",
    "economic_config", "native_gate", "paths", "campaigns", "fills",
}
_METRICS = {
    "total_return", "max_drawdown", "sharpe", "annualized_growth", "daily_count",
    "daily_loss_es", "daily_volatility", "economic_utility", "exposed_bars", "fees",
    "return_status", "utility_horizon", "account_mode", "psr",
}


@dataclass(frozen=True)
class RecoveryCell(VerifiedCell):
    """VerifiedCell-compatible account with explicit recovery/oracle coverage."""

    native_feedback_calls: int
    normal_native_calls: int
    python_oracle_calls: int

    @property
    def recovery_schema(self):
        return RECOVERY_SCHEMA

    @property
    def actual_execution_calls(self):
        return self.native_feedback_calls + self.normal_native_calls + self.python_oracle_calls

    @property
    def visited_bars(self):
        return self.actual_execution_calls * ((self.stop_ns - self.start_ns) // HOUR_NS)

    @property
    def oracle_coverage(self):
        return ("FRESH_ORIGINAL_PYTHON_CONTROL" if self.python_oracle_calls else
                "INHERITED_CONTROL_SOURCE_APPROVAL_NO_FRESH_PYTHON_ORACLE")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pin(pin):
    _require(isinstance(pin, dict) and set(pin) == {"path", "bytes", "sha256"},
             "exact caller pin required")
    _require(isinstance(pin["path"], str) and Path(pin["path"]).is_absolute()
             and type(pin["bytes"]) is int and pin["bytes"] >= 0
             and isinstance(pin["sha256"], str) and len(pin["sha256"]) == 64
             and all(c in "0123456789abcdef" for c in pin["sha256"]), "invalid caller pin")
    return canonical(pin)


def _sealed(pin, cutoff):
    _pin(pin)
    data = _read(pin)
    _require(Path(pin["path"]).stat().st_mtime_ns <= cutoff, "artifact beyond knowledge cutoff")
    return data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _json(pin, cutoff):
    value = json.loads(_sealed(pin, cutoff), object_pairs_hook=_unique)
    canonical(value)
    return value


def _public_id(value):
    _require(isinstance(value, str) and 0 < len(value) <= 256
             and all(c.isascii() and (c.isalnum() or c in "_.:-") for c in value),
             "public identifier required, not a path or free-form payload")
    return value


def _count(value, minimum=0):
    _require(type(value) is int and value >= minimum, "exact nonnegative count required")
    return value


def _public_metrics(metrics):
    result = {key: metrics[key] for key in metrics.keys() & _METRICS}
    numbers = _METRICS - {"account_mode", "return_status", "utility_horizon", "psr"}
    for key in numbers & result.keys():
        value = result[key]
        _require(value is None or (type(value) in (int, float) and np.isfinite(value)),
                 "public account metric must be numeric or unavailable")
    if "return_status" in result:
        _public_id(result["return_status"])
    if "utility_horizon" in result:
        _require(result["utility_horizon"] ==
                 "actual period; partial/leap durations disclosed, no automatic normalization",
                 "original utility horizon disclosure mismatch")
    if "psr" in result:
        psr = MetricValue(**result["psr"])
        _require(psr.metric_id == "mode5.classical_psr_plugin_v1" and psr.unit == "probability"
                 and psr.sample_count == 1095, "original PSR contract mismatch")
        if psr.reason is not None:
            _require("/" not in psr.reason and "\\" not in psr.reason,
                     "private path in metric reason")
        for name, value in psr.components:
            _require((name == "moment_estimator" and value == "central_population_v1") or
                     (name in {"z", "denominator_squared", "sr_period", "reference_period"}
                      and type(value) in (int, float) and np.isfinite(value)),
                     "unsupported/private PSR component")
        result["psr"] = psr.to_metadata()
    return result


def _sources(worker, pins, approvals, parent, cutoff):
    _require({"alpha_source", "finance_driver", "recovery_driver", "market_metadata"}
             <= approvals.keys(), "externally approved control source identities required")
    approved = {_pin(pin) for pin in approvals.values()}
    roster = worker["pins"]
    _require(isinstance(roster, list) and roster, "nonempty worker pin roster required")
    indexed = {}
    for pin in roster:
        identity = _pin(pin)
        _require(pin["path"] not in indexed, "duplicate worker source identity")
        indexed[pin["path"]] = (identity, pin)
    for name in ("original_registration", "design", "economic_config"):
        _require(indexed.get(pins[name]["path"], (None,))[0] == _pin(pins[name]),
                 "worker original authority differs from caller seal")
    artifact = _json(pins["native_gate"], cutoff)
    _require(artifact["status"] == "PASS", "native gate is not qualified")
    native = artifact["artifact"]
    _require(indexed.get(native["path"], (None,))[0] == _pin(native),
             "exact qualified native artifact absent")
    _sealed(native, cutoff)
    retained = {}
    for item in worker["source_snapshots"]:
        original, snapshot = item["original"], item["retained"]
        identity = _pin(original)
        _require(indexed.get(original["path"], (None,))[0] == identity
                 and original["path"] not in retained, "orphan/duplicate source snapshot")
        _require(Path(snapshot["path"]).parent.resolve() == (parent / "sources").resolve(),
                 "source snapshot is not a worker sibling")
        data = _sealed(snapshot, cutoff)
        _require(snapshot["bytes"] == original["bytes"] and snapshot["sha256"] == original["sha256"],
                 "source snapshot differs from original identity")
        retained[original["path"]] = data
    authorities = {_pin(pins[name]) for name in ("original_registration", "design", "economic_config")}
    for name in ("alpha_source", "finance_driver", "recovery_driver", "market_metadata"):
        _require(approvals[name]["path"] in retained
                 and indexed[approvals[name]["path"]][0] == _pin(approvals[name]),
                 "approved control source not used by worker")
    market = json.loads(retained[approvals["market_metadata"]["path"]], object_pairs_hook=_unique)
    witness = market["development"]
    _require(indexed.get(witness["path"], (None,))[0] == _pin(witness),
             "development witness is not the approved market identity")
    _require(set(retained) == set(indexed) - {native["path"], witness["path"]},
             "incomplete/orphan worker source snapshot roster")
    for path in retained:
        identity = indexed[path][0]
        _require(identity in authorities or identity in approved,
                 "worker source lacks external control approval")
    return witness


def _account(pins, witness, request, protocol, config, contract, cutoff):
    start, stop = _ns(request["start"]), _ns(request["stop"])
    count, days = (stop - start) // HOUR_NS, (stop - start) // DAY_NS
    with np.load(BytesIO(_sealed(pins["paths"], cutoff)), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    required = {"times_ns", "equity", "positions", "fees", "funding", "turnover", "margin", "daily_returns"}
    _require(required <= arrays.keys(), "complete recovery account streams required")
    times = arrays["times_ns"]
    _require(times.dtype == np.dtype("int64") and np.array_equal(times, np.arange(start, stop, HOUR_NS)),
             "full hourly calendar required, not a prefix/reset/splice")
    for key in required - {"times_ns"}:
        values = arrays[key]
        shape = (days,) if key == "daily_returns" else (2 * count,) if key == "margin" else (count,)
        _require(values.shape == shape and values.dtype.kind in "fiu" and np.isfinite(values).all(),
                 "finite aligned recovery stream required")
    coverage = ReportingCoverageV1(result_identity=pins["paths"]["sha256"],
        producer=RECOVERY_SCHEMA, profile="compact", ledger="omitted", retained_rows=0,
        dropped_rows=0, reason="dated execution ledgers retained separately")
    observations = AccountObservations(times_ns=times, equity=arrays["equity"], coverage=coverage)
    observations = observations.with_derived_returns(contract, partial_mask=np.zeros(days, dtype=bool),
        witness="sealed continuous hourly account; observed UTC closes; retrospective recovery")
    _require(np.allclose(observations.returns.values, arrays["daily_returns"], rtol=0, atol=1e-12),
             "daily return metric authority mismatch")
    report = reduce_account(observations, contract, backend="python")
    market = pd.read_csv(BytesIO(_sealed(witness, cutoff)), compression="gzip",
                         usecols=["datetime", "symbol", "close"])
    calendar = pd.DatetimeIndex(pd.to_datetime(market["datetime"], utc=True))
    _require(np.array_equal(calendar.asi8, np.arange(_ns(protocol.preload_start), stop, HOUR_NS))
             and market["symbol"].eq(request["symbol"]).all(), "original preload/market scope mismatch")
    close = market["close"].to_numpy(dtype=float)[-count:]
    _require(np.isfinite(close).all() and (close > 0).all(), "invalid original close marks")
    fills = _json(pins["fills"], cutoff)
    _require(isinstance(fills, list), "dated fill ledger required")
    projected, objects = [], []
    for row in fills:
        stamp = _ns(row["timestamp"])
        _require(start <= stamp < stop and (stamp - start) % HOUR_NS == 0
                 and row["symbol"] == request["symbol"] and row["side"] in {"buy", "sell"}
                 and row["liquidity"] in {"maker", "taker"}, "fill calendar/symbol/semantics mismatch")
        _public_id(row["order_id"])
        for key in ("qty", "price", "fee"):
            _require(type(row[key]) in (int, float) and np.isfinite(row[key])
                     and (row[key] >= 0 if key == "fee" else row[key] > 0), "invalid fill quantity/price/cost")
        projected.append({key: row[key] for key in
                          ("timestamp", "symbol", "side", "qty", "price", "fee", "order_id", "liquidity")})
        objects.append(Fill(timestamp=pd.Timestamp(row["timestamp"]), symbol=row["symbol"],
            order_id=row["order_id"], side=OrderSide.BUY if row["side"] == "buy" else OrderSide.SELL,
            qty=row["qty"], price=row["price"], fee=row["fee"]))
    account = config["account"]
    ledger = reconcile_fills(pd.DatetimeIndex(pd.to_datetime(times, utc=True)), close, objects,
        initial_capital=account["initial_capital"], contract_size=account["contract_size"],
        fee_rate=account["fee_rate"])
    for key in ("equity", "positions", "fees", "turnover"):
        _require(np.allclose(arrays[key], getattr(ledger, key), rtol=0, atol=1e-8),
                 "dated fills/account reconciliation mismatch")
    _require(not np.any(arrays["funding"]), "fixed-fill recovery requires the original zero-funding stream")
    campaigns = _json(pins["campaigns"], cutoff)
    expected = dict(closed=ledger.closed_campaigns, open=ledger.open_campaigns)
    _require(canonical(campaigns) == canonical(expected), "dated campaign/fill support or PnL mismatch")
    pnl = sum(row["net_pnl"] for row in campaigns["closed"])
    pnl += sum(row["marked_net_pnl"] for row in campaigns["open"])
    _require(np.isclose(pnl, arrays["equity"][-1] - contract.baseline_equity, rtol=0, atol=1e-8),
             "closed/open campaign PnL does not reconcile")
    return arrays, observations, report, campaigns, projected


def load_recovery_cell(result_path, *, artifact_pins, approved_source_pins, contract,
                       cutoff_ns, study_id, diagnostic_revision, data_cutoff_ns=None):
    """Read externally sealed recovery evidence into the existing panel reducers.

    Required artifact_pins are result, worker_registration, original_registration,
    design, economic_config, native_gate, paths, campaigns and fills. Control
    source pins use original identities, including alpha_source, finance_driver,
    recovery_driver, market_metadata and every other worker source snapshot.
    The reader creates no receipts, imports no strategies and loads no pickles.
    File mtimes only reject future artifacts; they do not prove historical access.
    """
    _require(_REQUIRED <= artifact_pins.keys(), "externally sealed recovery inventory required")
    _require(type(cutoff_ns) is int and cutoff_ns > 0, "exact retrospective knowledge cutoff required")
    _public_id(study_id)
    _public_id(diagnostic_revision)
    _require(isinstance(contract, ReportingContractV1), "original typed report contract required")
    pins = {name: dict(artifact_pins[name]) for name in _REQUIRED}
    approvals = {name: dict(pin) for name, pin in approved_source_pins.items()}
    parent = Path(result_path).resolve().parent
    for name, filename in (("result", "result.json"), ("worker_registration", "registration.json"),
                           ("paths", "paths.npz"), ("campaigns", "campaigns.json"), ("fills", "fills.json")):
        _require(Path(pins[name]["path"]) == parent / filename, "orphan recovery artifact")
    _require(Path(pins["result"]["path"]) == Path(result_path).resolve(), "result identity mismatch")
    _require(not any((parent / name).exists() for name in ("failure.json", "FAIL.json", "censored.json")),
             "failed/censored recovery cannot be ingested")
    result, worker, original, design, config = (
        _json(pins[name], cutoff_ns) for name in ("result", "worker_registration",
            "original_registration", "design", "economic_config"))
    _require(result["status"] == RECOVERY_STATUS and result["typed_lifecycle_terminal_parity"] is True
             and result["original_compiler_parity"] is True and result["clean_oos"] is False
             and result["future_tape_opened"] is False and result["panel_complete"] is False,
             "completed recovery qualification required, not legacy PASS")
    for key, name in (("registration", "worker_registration"), ("paths", "paths"),
                      ("campaigns_ledger", "campaigns"), ("fills_ledger", "fills")):
        _require(result[key] == pins[name], "result/caller artifact seal mismatch")
    _require(worker["native_gate"] == pins["native_gate"] and worker["methodology_changed"] is False
             and worker["guard_policy"] == "boundary_full_hash_v1", "registered recovery policy mismatch")
    protocol = ResearchProtocol(**original["protocol"])
    _require(original["protocol_id"] == protocol.identity
             and original["financial_outcomes_used_to_choose_design"] is False
             and original["forward_selection"] is False
             and (protocol.preload_start, protocol.development_start, protocol.development_stop)
                 == ("2020-01-01", "2021-01-01", "2024-01-01"), "original continuous protocol mismatch")
    _require(_ns(original["created_at"]) <= cutoff_ns, "future original registration")
    request = result["request"]
    _require(canonical(request) == canonical(worker["request"]) and request["alpha"] == design["alpha"]
             and request["design_id"] == design["design_id"]
             and request["symbol"] == original["symbols"][request["alpha"]]
             and request["role"] == "NEUTRAL_BROAD_DISCOVERY"
             and request["account_mode"] == "continuous_development_2021_2023"
             and request["start"] == protocol.development_start and request["stop"] == protocol.development_stop
             and type(request["max_feedback_runs"]) is int and request["max_feedback_runs"] == 4096,
             "original request/design role or scope mismatch")
    row_id = _count(request["proposal_row"])
    _require(row_id < len(design["rows"]), "proposal outside original design range")
    proposals = [row for row in design["rows"] if type(row["row_id"]) is int and row["row_id"] == row_id]
    _require(len(proposals) == 1, "unique original proposal required")
    proposal = proposals[0]
    _require(proposal["admitted"] is True and proposal["status"] == "READY"
             and proposal["role"] == "exploration" and proposal.get("duplicate_of") is None
             and proposal["candidate_id"] == request["candidate_id"]
             and canonical(proposal["effective"]) == canonical(request["params"]),
             "original effective proposal mismatch")
    for key in ("alpha", "candidate_id", "design_id", "symbol"):
        _public_id(request[key])
    _public_id(proposal["direction"])
    start, stop = _ns(request["start"]), _ns(request["stop"])
    data_cutoff_ns = stop if data_cutoff_ns is None else data_cutoff_ns
    _require(type(data_cutoff_ns) is int and stop <= data_cutoff_ns <= cutoff_ns,
             "future/immature development scope")
    _require(contract.scope == "full" and contract.unit == "account_period"
             and contract.sampling == "observed_daily_utc" and contract.annual_periods == 365.
             and contract.partial_periods == "include_disclosed" and contract.equity_clock == "bar_close"
             and contract.baseline_time_ns == start-HOUR_NS and contract.scope_end_ns == stop-HOUR_NS
             and contract.baseline_equity == config["account"]["initial_capital"]
             and config["timeframe"] == "1h" and config["execution_contract"] == "event_lifecycle_v3_next_open"
             and config["terminal_policy"] == "mark_only_no_hidden_flatten"
             and config["account"]["use_funding"] is False,
             "original continuous report/account/clock contract mismatch")
    original_contract = ReportingContractV1(scope="full", unit="account_period", currency=contract.currency,
        baseline_equity=config["account"]["initial_capital"], baseline_time_ns=start-HOUR_NS,
        scope_end_ns=stop-HOUR_NS, sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
    _require(contract == original_contract, "original report policy defaults required")
    control = worker["control"]
    _require(type(control) is bool and worker["dense_owner_retained"] is control
             and type(worker["python_oracle_calls_planned"]) is int
             and worker["python_oracle_calls_planned"] == int(control), "registered oracle coverage mismatch")
    feedback, normal, python = (_count(result[key], minimum) for key, minimum in
        (("native_feedback_calls", 1), ("final_native_calls", 1), ("python_oracle_calls", 0)))
    _require(normal == (2 if control else 1) and python == int(control)
             and (result["owner"] is not None) == control, "actual oracle/account-call coverage mismatch")
    if control:
        _require(Path(result["owner"]["path"]) == parent / "actual_owner.pkl", "orphan control owner")
        _sealed(result["owner"], cutoff_ns)
    _require(_count(result["bar_steps"]) == 26280 + _count(result["bar_retries"]),
             "incomplete committed decision calendar")
    _require(type(result["wall_seconds"]) in (int, float) and type(result["peak_rss_mib"]) in (int, float)
             and np.isfinite([result["wall_seconds"], result["peak_rss_mib"]]).all()
             and 0 <= result["wall_seconds"] <= worker["cap_seconds"]
             and 0 <= result["peak_rss_mib"] <= protocol.worker_rss_cap_bytes / 1024**2,
             "actual resource accounting exceeds registration")
    witness = _sources(worker, pins, approvals, parent, cutoff_ns)
    arrays, observations, report, campaigns, fills = _account(
        pins, witness, request, protocol, config, contract, cutoff_ns)
    for key, count in (("fills", len(fills)), ("closed_campaigns", len(campaigns["closed"])),
                       ("open_campaigns", len(campaigns["open"]))):
        _require(_count(result[key]) == count, "retained support count mismatch")
    _require(type(result["accounting_residual"]) in (int, float)
             and np.isfinite(result["accounting_residual"]) and 0 <= result["accounting_residual"] <= 1e-8,
             "accounting qualification residual mismatch")
    metrics = _public_metrics(result["metrics"])
    for source, target in (("account.total_return", "total_return"), ("drawdown.max_depth", "max_drawdown"),
                           ("period.sharpe", "sharpe")):
        expected, retained = report.metric(source).value, metrics[target]
        _require((expected is None and retained is None) or
                 (expected is not None and type(retained) in (int, float)
                  and np.isfinite(retained) and np.isclose(expected, retained, rtol=0, atol=1e-10)),
                 "retained account metric authority mismatch")
    _require(metrics["daily_count"] == 1095 and metrics["account_mode"] == request["account_mode"],
             "retained metric scope mismatch")
    refs = {name: pin["sha256"] for name, pin in pins.items()}
    refs.update({f"approved_source_{number}": pin["sha256"]
                 for number, pin in enumerate(sorted(approvals.values(), key=lambda pin: pin["path"]))})
    refs["development_data"] = witness["sha256"]
    provenance = CandidateProvenance(study_id, diagnostic_revision, request["alpha"], request["candidate_id"],
        digest(proposal["requested"]), digest(proposal["effective"]), proposal["direction"], (row_id,),
        pins["result"]["sha256"], request["design_id"], request["symbol"],
        "DEVELOPMENT_REVIEWED_RETROSPECTIVE", DISCLOSURE, _ns(protocol.preload_start), data_cutoff_ns,
        cutoff_ns, cutoff_ns, "incremental_actual_feedback_boundary_full_hash_v1", tuple(sorted(refs.items())))
    buffers = tuple(FrozenBuffer.from_array(name, arrays[name]) for name in
                    ("positions", "fees", "funding", "turnover"))
    return RecoveryCell(provenance, start, stop, contract, observations, buffers,
        canonical(campaigns), canonical(fills), canonical(metrics),
        RECOVERY_STATUS, None, feedback, normal, python)
