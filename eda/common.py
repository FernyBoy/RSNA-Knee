"""Rutas, constantes y utilidades compartidas por los scripts de exploración."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

DATA_ROOT = Path(
    os.environ.get(
        "KNEE_DATA",
        "/lustre/proyectos/p082/kaggle_data/competitions/rsna-knee-abnormality-detection",
    )
)
OUT_ROOT = Path(
    os.environ.get("KNEE_EDA_OUT", Path(__file__).resolve().parents[1] / "data" / "eda")
)

LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA", "Lateral OA",
    "PF OA", "Effusion", "Synovitis", "Baker's", "Contusion", "Fracture",
]
PLANES = ["Sagittal", "Coronal", "Axial"]

# Paleta categórica en orden fijo (no reordenar: el color sigue a la entidad).
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def out_dir(*parts: str) -> Path:
    d = OUT_ROOT.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_studies(split: str = "train") -> pd.DataFrame:
    return pd.read_csv(DATA_ROOT / f"{split}.csv", dtype={"StudyInstanceUID": str})


def load_series(split: str = "train") -> pd.DataFrame:
    return pd.read_csv(
        DATA_ROOT / f"{split}_series.csv",
        dtype={"StudyInstanceUID": str, "SeriesInstanceUID": str},
    )


def series_dir(split: str, study_uid: str, series_uid: str) -> Path:
    return DATA_ROOT / f"{split}_series" / study_uid / series_uid


def setup_style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from cycler import cycler

    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "figure.dpi": 130, "savefig.bbox": "tight",
        "axes.prop_cycle": cycler(color=SERIES_COLORS),
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.labelsize": 9, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "text.color": INK, "font.size": 9, "legend.frameon": False, "legend.fontsize": 8.5,
        "lines.linewidth": 2,
    })
    return plt


def hbar(ax, labels, values, fmt="{:,.0f}", color=SERIES_COLORS[0]):
    """Barras horizontales con el valor rotulado al final de cada barra."""
    labels, values = list(labels)[::-1], list(values)[::-1]
    bars = ax.barh(labels, values, color=color, height=0.62)
    ax.bar_label(bars, labels=[fmt.format(v) for v in values], padding=3, color=INK_2, fontsize=8.5)
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.12)
    return bars
