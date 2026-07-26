"""
Alpha execution-contract certification helpers.

These helpers are intentionally lightweight and conservative. They do not try
to prove a strategy has no look-ahead bias from source text alone; they identify
which execution contract a file appears to require and what certification level
an already-run result can claim from its metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Sequence


class CertificationLevel(IntEnum):
    LEGACY = 0
    ACCOUNTING_REPLAY = 1
    ENGINE_CAUSAL = 2
    CROSS_BACKEND = 3
    EXTERNAL_VALIDATION = 4


LEVEL_DESCRIPTIONS = {
    CertificationLevel.LEGACY: "legacy_or_unspecified_execution_contract",
    CertificationLevel.ACCOUNTING_REPLAY: "explicit_fills_accounted_but_fill_generation_not_certified",
    CertificationLevel.ENGINE_CAUSAL: "engine_owned_causal_execution_with_oracle_or_kernel_parity",
    CertificationLevel.CROSS_BACKEND: "native_engine_matches_native_event_on_known_scenarios",
    CertificationLevel.EXTERNAL_VALIDATION: "external_or_lower_timeframe_validation_available",
}


INTRABAR_MARKERS = (
    "exit_price",
    "exit_type",
    "stop_loss",
    "stoploss",
    "take_profit",
    "takeprofit",
    "trailing",
    "trailing_stop",
    "use_sl",
    "use_tp",
    "slpercent",
    "tppercent",
    "high[",
    "low[",
)
FILL_REPLAY_MARKERS = ("fill_replay", "fills_df", "compact_fill", "bar_index", "sequence")
GRID_MARKERS = ("dca_ladder", "grid", "safety_order", "take_profit_price", "stop_loss_price")
NEXT_OPEN_MARKERS = ("next_open", "open[t+1]", "shift(1)", "open.shift")
CLOSE_TARGET_MARKERS = ("native_vectorized", "signal_notional", "pos_weight", "target_weight")


@dataclass(frozen=True)
class AlphaExecutionClassification:
    alpha_id: str
    path: str
    required_engine: str
    current_backend: str
    certification_status: str
    certification_level: int
    markers: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    uses_intrabar_high_low: bool = False
    uses_stop: bool = False
    uses_take_profit: bool = False
    uses_trailing: bool = False
    uses_custom_exit_price: bool = False
    uses_explicit_fills: bool = False
    uses_grid_or_dca: bool = False
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


def classify_alpha_source(source: str, *, alpha_id: str = "unknown", path: str = "") -> AlphaExecutionClassification:
    text = source.lower()
    markers = _matched_markers(text)
    current_backend = _detect_current_backend(text)
    uses_explicit_fills = any(marker in text for marker in FILL_REPLAY_MARKERS)
    uses_grid_or_dca = any(marker in text for marker in GRID_MARKERS)
    uses_stop = any(marker in text for marker in ("stop_loss", "stoploss", "slpercent", "use_sl"))
    uses_take_profit = any(marker in text for marker in ("take_profit", "takeprofit", "tppercent", "use_tp"))
    uses_trailing = "trailing" in text
    uses_custom_exit_price = "exit_price" in text or "exit_type" in text
    uses_intrabar_high_low = bool(re.search(r"\bhigh\s*\[|\blow\s*\[|df\s*\[\s*['\"]high|df\s*\[\s*['\"]low", text))

    if uses_grid_or_dca:
        required_engine = "event_lifecycle_v2"
        level = CertificationLevel.LEGACY
        status = "needs_specialized_event_or_nautilus_certification"
    elif uses_explicit_fills and not (uses_stop or uses_take_profit or uses_trailing):
        required_engine = "fill_replay_v1"
        level = CertificationLevel.ACCOUNTING_REPLAY
        status = "can_start_with_accounting_replay"
    elif uses_stop or uses_take_profit or uses_trailing or uses_custom_exit_price or uses_intrabar_high_low:
        required_engine = "intrabar_bracket_v1"
        level = CertificationLevel.LEGACY
        status = "requires_intrabar_migration"
    elif any(marker in text for marker in NEXT_OPEN_MARKERS):
        required_engine = "next_open_v1"
        level = CertificationLevel.LEGACY
        status = "requires_next_open_contract"
    elif any(marker in text for marker in CLOSE_TARGET_MARKERS):
        required_engine = "close_target_v2"
        level = CertificationLevel.ENGINE_CAUSAL if current_backend in {"native_vectorized", "close_target_v2"} else CertificationLevel.LEGACY
        status = "close_target_candidate"
    else:
        required_engine = "unknown"
        level = CertificationLevel.LEGACY
        status = "manual_review_required"

    notes = _notes_for_classification(required_engine, current_backend, markers)
    return AlphaExecutionClassification(
        alpha_id=alpha_id,
        path=path,
        required_engine=required_engine,
        current_backend=current_backend,
        certification_status=status,
        certification_level=int(level),
        markers=tuple(markers),
        notes=tuple(notes),
        uses_intrabar_high_low=uses_intrabar_high_low,
        uses_stop=uses_stop,
        uses_take_profit=uses_take_profit,
        uses_trailing=uses_trailing,
        uses_custom_exit_price=uses_custom_exit_price,
        uses_explicit_fills=uses_explicit_fills,
        uses_grid_or_dca=uses_grid_or_dca,
    )


def scan_alpha_directory(root: str | Path, *, suffixes: Sequence[str] = (".py", ".ipynb", ".md"), max_bytes: int = 2_000_000) -> List[AlphaExecutionClassification]:
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(str(base))
    out: list[AlphaExecutionClassification] = []
    for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in suffixes):
        if any(part.startswith(".") for part in path.relative_to(base).parts):
            continue
        if path.stat().st_size > max_bytes:
            out.append(
                AlphaExecutionClassification(
                    alpha_id=path.stem,
                    path=str(path),
                    required_engine="unknown",
                    current_backend="unknown",
                    certification_status="skipped_large_file",
                    certification_level=int(CertificationLevel.LEGACY),
                    notes=("file exceeds scanner max_bytes",),
                )
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        out.append(classify_alpha_source(text, alpha_id=path.stem, path=str(path)))
    return out


def certify_result_metadata(metadata: Dict) -> Dict:
    engine = str(metadata.get("engine_id") or metadata.get("engine") or "").lower()
    backend = str(metadata.get("backend") or metadata.get("backend_alias") or "").lower()
    if engine == "fill_replay_v1":
        level = CertificationLevel.ACCOUNTING_REPLAY
        status = "accounting_certified"
    elif engine == "intrabar_bracket_v1":
        level = CertificationLevel.ENGINE_CAUSAL
        status = "engine_causal_certified"
        if metadata.get("cross_backend_parity_passed"):
            level = CertificationLevel.CROSS_BACKEND
            status = "cross_backend_certified"
    elif backend == "nautilus" or "nautilus" in engine:
        level = CertificationLevel.EXTERNAL_VALIDATION
        status = "external_validation_route"
    elif engine == "close_target_v2":
        level = CertificationLevel.ENGINE_CAUSAL
        status = "close_target_certified"
        if str(metadata.get("certification_status", "")).startswith("uncertified"):
            level = CertificationLevel.LEGACY
            status = str(metadata.get("certification_status"))
    else:
        level = CertificationLevel.LEGACY
        status = "uncertified_or_unknown"
    return {
        "engine_id": engine or "unknown",
        "backend": backend or "unknown",
        "certification_level": int(level),
        "certification_label": f"LEVEL {int(level)}",
        "certification_status": status,
        "description": LEVEL_DESCRIPTIONS[level],
    }


def build_alpha_certification_report(items: Iterable[AlphaExecutionClassification]) -> Dict:
    rows = [item.to_dict() for item in items]
    by_engine: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for row in rows:
        by_engine[row["required_engine"]] = by_engine.get(row["required_engine"], 0) + 1
        by_status[row["certification_status"]] = by_status.get(row["certification_status"], 0) + 1
    return {
        "total": len(rows),
        "by_required_engine": by_engine,
        "by_status": by_status,
        "items": rows,
    }


def alpha_report_markdown(report: Dict) -> str:
    lines = [
        "# Alpha Execution Certification Report",
        "",
        f"- Total files scanned: `{report['total']}`",
        "",
        "## By Required Engine",
        "",
        "| Engine | Count |",
        "|---|---:|",
    ]
    for engine, count in sorted(report["by_required_engine"].items()):
        lines.append(f"| `{engine}` | {count} |")
    lines.extend(["", "## By Status", "", "| Status | Count |", "|---|---:|"])
    for status, count in sorted(report["by_status"].items()):
        lines.append(f"| `{status}` | {count} |")
    lines.extend(["", "## Files", "", "| Alpha | Required engine | Current backend | Status | Markers |", "|---|---|---|---|---|"])
    for item in report["items"]:
        markers = ", ".join(item["markers"][:8])
        if len(item["markers"]) > 8:
            markers += ", ..."
        lines.append(
            f"| `{item['alpha_id']}` | `{item['required_engine']}` | `{item['current_backend']}` | "
            f"`{item['certification_status']}` | {markers or '-'} |"
        )
    return "\n".join(lines) + "\n"


def _matched_markers(text: str) -> list[str]:
    all_markers = sorted(set(INTRABAR_MARKERS + FILL_REPLAY_MARKERS + GRID_MARKERS + NEXT_OPEN_MARKERS + CLOSE_TARGET_MARKERS))
    return [marker for marker in all_markers if marker in text]


def _detect_current_backend(text: str) -> str:
    if "nautilus_validation" in text or "backend=\"nautilus\"" in text or "backend='nautilus'" in text:
        return "nautilus"
    if "intrabar_bracket" in text:
        return "native_intrabar"
    if "fill_replay" in text:
        return "fill_replay_v1"
    if "native_event" in text:
        return "native_event"
    if "native_vectorized" in text:
        return "native_vectorized"
    if "%_equity" in text or "pct_equity" in text:
        return "legacy_pct_equity"
    if "backtestengine(" in text:
        return "legacy"
    return "unknown"


def _notes_for_classification(required_engine: str, current_backend: str, markers: Sequence[str]) -> list[str]:
    notes: list[str] = []
    if required_engine == "intrabar_bracket_v1" and current_backend in {"native_vectorized", "legacy", "legacy_pct_equity"}:
        notes.append("intrabar markers found on a close-target/legacy route; migrate to intrabar intent or fill replay")
    if required_engine == "fill_replay_v1":
        notes.append("accounting can be validated from explicit fills, but fill generation remains alpha-owned")
    if required_engine == "event_lifecycle_v2":
        notes.append("multi-order/grid/DCA behavior should stay on event lifecycle or Nautilus validation")
    if not markers:
        notes.append("no execution-sensitive markers detected; manual review still required before production certification")
    return notes
