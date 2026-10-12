"""Actual scorer/source witnesses for explicitly qualified continuous routes."""

from hashlib import sha256
from importlib import import_module
from pathlib import Path

from ..core.wfo_contracts import strategy_fingerprint
from ..optimization.meta_selection.observer import economics_identity
from .diagnostics.identity import digest
from .dossier.records import Record


def producer_records(config, strategy):
    """Describe the executed provider, not a backend supplied by a researcher.

    This initial public binding certifies the original pct-equity scorer only.
    Other financial routes need their own matched producer qualification; they
    cannot borrow this witness just because they also return equity.
    """
    if (config.mode != "pct_equity" or config.backend != "legacy"
            or str(config.target_runtime).lower() == "rust"):
        raise NotImplementedError("continuous public producer qualification is legacy pct_equity only")
    modules = ("endpoint", "backtester", "core.engine", "core.preprocessor",
               "core.constraints", "sizing.modes")
    source_files = []
    for name in modules:
        module = import_module("quantbt." + name)
        path = Path(module.__file__)
        source_files.append((name, sha256(path.read_bytes()).hexdigest()))
    source = Record.of(dict(alpha=strategy_fingerprint(strategy), financial_provider=digest(source_files)))
    execution = Record.of(dict(route=config.mode, backend=config.backend,
        clock=dict(id="legacy_pct_equity", equity_clock="bar_close",
            # The legacy endpoint attaches this generic record, not an event
            # clock. Source qualification above supplies the actual convention.
            execution_contract=dict(engine_id="unknown", signal_phase="unspecified",
                fill_phase="unspecified", intrabar_exit_model="unspecified")),
        initial_state=dict(equity=float(config.account.initial_capital), position_policy="flat"),
        terminal_policy=dict(id="legacy_original"),
        economics=dict(identity=economics_identity(config))))
    return source, execution


def qualify_producer(scorer, strategy, contract):
    from ..endpoint import _WalkForwardEndpointScorer
    if type(scorer) is not _WalkForwardEndpointScorer:
        raise TypeError("original public endpoint scorer required; no self-certified execution witness")
    source, execution = producer_records(scorer.score_config, strategy)
    if source != contract.source or execution != contract.execution:
        raise ValueError("actual producer source/backend/clock/economics differs from continuous binding")
    return execution


def validate_result(result, execution, config):
    """Reconcile original legacy result fields without replay or metadata edits."""
    if execution.data["route"] != "pct_equity" or execution.data["backend"] != "legacy":
        raise NotImplementedError("unqualified continuous result producer")
    expected = dict(hedge_type="%_equity", fee_oneway=float(config.fee)/2,
        slippage=float(config.slippage), maintenance_ratio=float(config.account.maintenance_ratio))
    if any(result.metadata.get(k) != v for k, v in expected.items()):
        raise ValueError("original executed fee/sizing/slippage/margin differs from producer")
    if (float(result.initial_capital) != execution.data["initial_state"]["equity"]
            or float(result.leverage) != float(config.account.leverage)):
        raise ValueError("actual initial capital/leverage differs from continuous producer")
