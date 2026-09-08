#!/usr/bin/env python3
"""Render the evidence-backed QuantBT release-performance overview.

The visual deliberately keeps two ideas separate:

* a release/capability timeline, which communicates product scope; and
* paired timing bars, which compare only implementations measured on the same
  declared fixture.

It never constructs a synthetic speed series from unrelated domain workloads.
Raw measurements remain in their original committed evidence artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import textwrap
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks" / "history" / "release_performance_evolution_v1.json"
DEFAULT_PNG = ROOT / "docs" / "assets" / "quantbt-performance-evolution.png"
DEFAULT_SVG = ROOT / "docs" / "assets" / "quantbt-performance-evolution.svg"


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return payload


def _value_at(payload: Mapping[str, Any], dotted_path: str) -> float:
    value: Any = payload
    for token in dotted_path.split("."):
        if not isinstance(value, Mapping) or token not in value:
            raise KeyError(f"missing evidence field {dotted_path!r}")
        value = value[token]
    numeric = float(value)
    if numeric <= 0.0:
        raise ValueError(f"evidence field {dotted_path!r} must be positive")
    return numeric


def _summary_row(payload: Mapping[str, Any], selector: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = payload.get("summary")
    if not isinstance(rows, list):
        raise ValueError("callback evidence must contain a summary list")
    matches = [row for row in rows if isinstance(row, Mapping) and all(row.get(key) == value for key, value in selector.items())]
    if len(matches) != 1:
        raise ValueError(f"callback selector {dict(selector)!r} matched {len(matches)} rows")
    return matches[0]


def collect(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load and validate the curated manifest against immutable raw evidence."""

    manifest = _load_json(manifest_path)
    if manifest.get("schema") != "quantbt-release-performance-evolution-v1":
        raise ValueError("unsupported release performance evolution schema")

    paired: list[dict[str, Any]] = []
    for row in manifest.get("paired_routes", []):
        if not isinstance(row, Mapping):
            raise ValueError("paired_routes rows must be objects")
        evidence_path = ROOT / str(row["evidence_path"])
        evidence = _load_json(evidence_path)
        rust_seconds = _value_at(evidence, str(row["rust_path"]))
        reference_seconds = _value_at(evidence, str(row["reference_path"]))
        paired.append(
            {
                "label": str(row["label"]),
                "fixture": str(row["fixture"]),
                "evidence_path": str(row["evidence_path"]),
                "reference_label": str(row["reference_label"]),
                "rust_seconds": rust_seconds,
                "reference_seconds": reference_seconds,
                "speedup": reference_seconds / rust_seconds,
            }
        )

    callbacks: list[dict[str, Any]] = []
    for row in manifest.get("callback_closure", []):
        if not isinstance(row, Mapping):
            raise ValueError("callback_closure rows must be objects")
        evidence = _load_json(ROOT / str(row["evidence_path"]))
        baseline = _summary_row(evidence, row["baseline_selector"])
        candidate = _summary_row(evidence, row["candidate_selector"])
        callbacks.append(
            {
                "label": str(row["label"]),
                "evidence_path": str(row["evidence_path"]),
                "baseline_bars_per_second": float(baseline["bars_per_second"]),
                "candidate_bars_per_second": float(candidate["bars_per_second"]),
                "baseline_peak_rss_mib": float(baseline["median_peak_rss_mib"]),
                "candidate_peak_rss_mib": float(candidate["median_peak_rss_mib"]),
            }
        )

    timeline = manifest.get("release_timeline")
    if not isinstance(timeline, list) or not timeline:
        raise ValueError("release_timeline must contain at least one milestone")
    if not paired or not callbacks:
        raise ValueError("evolution manifest must contain paired routes and callback closure rows")
    return {
        "manifest_path": str(manifest_path.relative_to(ROOT)),
        "title": str(manifest["title"]),
        "subtitle": str(manifest["subtitle"]),
        "timeline": [dict(item) for item in timeline if isinstance(item, Mapping)],
        "paired": paired,
        "callbacks": callbacks,
        "notes": [str(note) for note in manifest.get("notes", [])],
    }


def _format_ms(seconds: float) -> str:
    milliseconds = seconds * 1_000.0
    return f"{milliseconds:.3f} ms" if milliseconds < 100.0 else f"{milliseconds:.0f} ms"


def render(data: Mapping[str, Any], *, png_path: Path, svg_path: Path) -> None:
    """Render a responsive-looking static asset suitable for GitHub README."""

    if "MPLCONFIGDIR" not in os.environ:
        cache_dir = Path(tempfile.gettempdir()) / "quantbt-matplotlib"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(cache_dir)
    import matplotlib.pyplot as plt
    import numpy as np

    colors = {
        "ink": "#182033",
        "muted": "#596579",
        "grid": "#D7DEE8",
        "paper": "#F7F9FC",
        "panel": "#FFFFFF",
        "rust": "#007C7A",
        "python": "#D96C44",
        "timeline": "#1E5A8A",
        "accent": "#D6A018",
    }
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.labelcolor": colors["muted"],
            "xtick.color": colors["muted"],
            "ytick.color": colors["muted"],
            "text.color": colors["ink"],
        }
    )
    figure = plt.figure(figsize=(18, 12), facecolor=colors["paper"])
    grid = figure.add_gridspec(2, 2, height_ratios=[1.0, 1.8], hspace=0.48, wspace=0.28)
    timeline_axis = figure.add_subplot(grid[0, :])
    paired_axis = figure.add_subplot(grid[1, 0])
    callback_axis = figure.add_subplot(grid[1, 1])
    for axis in (timeline_axis, paired_axis, callback_axis):
        axis.set_facecolor(colors["panel"])
        for spine in axis.spines.values():
            spine.set_visible(False)

    figure.suptitle(str(data["title"]), x=0.055, y=0.992, ha="left", fontsize=25, fontweight="bold")
    figure.text(0.055, 0.955, str(data["subtitle"]), ha="left", fontsize=11.5, color=colors["muted"])

    timeline = list(data["timeline"])
    x_values = np.arange(len(timeline), dtype=float)
    timeline_axis.hlines(0.5, x_values[0], x_values[-1], color=colors["grid"], linewidth=4, zorder=1)
    timeline_axis.scatter(x_values, np.full(len(timeline), 0.5), s=300, color=colors["timeline"], edgecolor="white", linewidth=2.5, zorder=3)
    for index, item in enumerate(timeline):
        vertical = 0.80 if index % 2 == 0 else 0.18
        alignment = "bottom" if vertical > 0.5 else "top"
        timeline_axis.vlines(index, min(0.5, vertical), max(0.5, vertical), color=colors["grid"], linewidth=1.5, zorder=2)
        timeline_axis.text(index, vertical, str(item["release"]), ha="center", va=alignment, fontsize=12, fontweight="bold", color=colors["timeline"])
        detail_y = vertical - 0.12 if vertical > 0.5 else vertical + 0.12
        timeline_axis.text(index, detail_y, f"{item['label']}\n{item['detail']}", ha="center", va=alignment, fontsize=9.2, color=colors["muted"], linespacing=1.45)
    timeline_axis.set_xlim(-0.45, len(timeline) - 0.55)
    timeline_axis.set_ylim(0.0, 1.0)
    timeline_axis.set_xticks([])
    timeline_axis.set_yticks([])
    timeline_axis.set_title("Release Milestones And Certified Domain Expansion", loc="left", pad=14, fontsize=14)

    paired = list(data["paired"])
    labels = [str(item["label"]) for item in paired]
    positions = np.arange(len(paired), dtype=float)
    height = 0.34
    rust_ms = [float(item["rust_seconds"]) * 1_000.0 for item in paired]
    reference_ms = [float(item["reference_seconds"]) * 1_000.0 for item in paired]
    paired_axis.barh(positions + height / 2.0, reference_ms, height=height, color=colors["python"], label="Matched Python/Numba reference")
    paired_axis.barh(positions - height / 2.0, rust_ms, height=height, color=colors["rust"], label="Rust measured route")
    paired_axis.set_xscale("log")
    paired_axis.set_yticks(positions, labels)
    paired_axis.invert_yaxis()
    paired_axis.grid(axis="x", color=colors["grid"], linewidth=0.8, alpha=0.9)
    paired_axis.set_axisbelow(True)
    paired_axis.set_xlabel("Median runtime, milliseconds (log scale)")
    paired_axis.set_title("Paired Runtime Evidence By Certified Domain", loc="left", pad=14, fontsize=14)
    for index, item in enumerate(paired):
        speedup = float(item["speedup"])
        anchor = max(rust_ms[index], reference_ms[index]) * 1.15
        paired_axis.text(anchor, positions[index], f"{speedup:.1f}x\n{item['fixture']}", va="center", fontsize=8.6, color=colors["ink"])
    paired_axis.legend(loc="lower right", fontsize=8.6, frameon=False)

    callbacks = list(data["callbacks"])
    positions = np.arange(len(callbacks), dtype=float)
    baseline = [float(item["baseline_bars_per_second"]) for item in callbacks]
    candidate = [float(item["candidate_bars_per_second"]) for item in callbacks]
    callback_axis.bar(positions - 0.18, baseline, width=0.34, color=colors["python"], label="Before closure")
    callback_axis.bar(positions + 0.18, candidate, width=0.34, color=colors["rust"], label="After closure")
    callback_axis.set_xticks(positions, [str(item["label"]) for item in callbacks])
    callback_axis.grid(axis="y", color=colors["grid"], linewidth=0.8, alpha=0.9)
    callback_axis.set_axisbelow(True)
    callback_axis.set_ylabel("Bars per second")
    callback_axis.set_title("Public Reactive Callback Recovery", loc="left", pad=14, fontsize=14)
    for index, item in enumerate(callbacks):
        ratio = float(item["candidate_bars_per_second"]) / float(item["baseline_bars_per_second"])
        peak = float(item["candidate_peak_rss_mib"])
        callback_axis.text(positions[index], max(baseline[index], candidate[index]) * 1.035, f"{ratio:.2f}x\n{peak:.0f} MiB peak RSS", ha="center", fontsize=9, color=colors["ink"])
    callback_axis.legend(loc="upper left", fontsize=8.8, frameon=False)

    note = " ".join(str(item) for item in data["notes"])
    note = textwrap.fill(
        f"{note} Raw evidence and the regeneration script are committed with QuantBT.",
        width=210,
    )
    figure.text(0.5, 0.022, note, ha="center", va="bottom", fontsize=7.8, color=colors["muted"])
    figure.subplots_adjust(left=0.08, right=0.95, top=0.89, bottom=0.11)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(png_path, dpi=180, facecolor=figure.get_facecolor(), bbox_inches="tight")
    figure.savefig(svg_path, facecolor=figure.get_facecolor(), bbox_inches="tight")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG)
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG)
    parser.add_argument("--check", action="store_true", help="Validate raw evidence without rendering an asset.")
    args = parser.parse_args(argv)
    manifest = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    data = collect(manifest)
    if args.check:
        print(f"Performance evolution evidence verified: {data['manifest_path']}")
        return 0
    png = args.png if args.png.is_absolute() else ROOT / args.png
    svg = args.svg if args.svg.is_absolute() else ROOT / args.svg
    render(data, png_path=png, svg_path=svg)
    print(f"Performance evolution assets written: {png.relative_to(ROOT)}, {svg.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
