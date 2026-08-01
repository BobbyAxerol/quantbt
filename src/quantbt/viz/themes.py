"""
quantbt.viz.themes
------------------
Centralised styling.  Two themes: 'dark' (presentation / screen)
and 'light' (report / print).

Usage
~~~~~
    from quantbt.viz.themes import apply_theme, PALETTE
    apply_theme('dark')
"""

from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt

# ── Palettes ─────────────────────────────────────────────────────────────────

PALETTE = {
    "dark": {
        "bg":        "#0d1117",
        "axes_bg":   "#161b22",
        "text":      "#c9d1d9",
        "grid":      "#21262d",
        "border":    "#30363d",
        "equity":    "#58a6ff",
        "drawdown":  "#f85149",
        "benchmark": "#8b949e",
        "long":      "#3fb950",
        "short":     "#f78166",
        "neutral":   "#a371f7",
        "bar_pos":   "#3fb950",
        "bar_neg":   "#f85149",
    },
    "light": {
        "bg":        "#ffffff",
        "axes_bg":   "#f6f8fa",
        "text":      "#24292f",
        "grid":      "#d0d7de",
        "border":    "#d0d7de",
        "equity":    "#0550ae",
        "drawdown":  "#cf222e",
        "benchmark": "#57606a",
        "long":      "#1a7f37",
        "short":     "#cf222e",
        "neutral":   "#8250df",
        "bar_pos":   "#1a7f37",
        "bar_neg":   "#cf222e",
    },
}


def apply_theme(theme: str = "dark") -> dict:
    """
    Apply matplotlib rcParams for the chosen theme.
    Returns the colour palette dict for downstream use.
    """
    if theme not in PALETTE:
        raise ValueError(f"theme must be 'dark' or 'light', got '{theme}'")

    c = PALETTE[theme]

    mpl.rcParams.update({
        # figure
        "figure.facecolor":       c["bg"],
        "figure.dpi":             130,
        # axes
        "axes.facecolor":         c["axes_bg"],
        "axes.edgecolor":         c["border"],
        "axes.labelcolor":        c["text"],
        "axes.spines.top":        False,
        "axes.spines.right":      False,
        "axes.grid":              True,
        "axes.grid.axis":         "y",
        "axes.titlepad":          10,
        "axes.titlesize":         11,
        "axes.labelsize":         9,
        # grid
        "grid.color":             c["grid"],
        "grid.linewidth":         0.5,
        "grid.alpha":             1.0,
        # ticks
        "xtick.color":            c["text"],
        "ytick.color":            c["text"],
        "xtick.labelsize":        8,
        "ytick.labelsize":        8,
        # text
        "text.color":             c["text"],
        # legend
        "legend.facecolor":       c["axes_bg"],
        "legend.edgecolor":       c["border"],
        "legend.fontsize":        8,
        "legend.framealpha":      0.85,
        # lines
        "lines.linewidth":        1.6,
        # font
        "font.family":            "monospace",
        "font.size":              9,
    })

    return c
