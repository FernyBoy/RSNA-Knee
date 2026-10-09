#!/usr/bin/env python
"""Resume el parquet de cabeceras generado por 03_extraer_cabeceras.py.

Uso:  python 04_resumen_cabeceras.py RUTA.parquet [--split train]
Salidas junto al parquet: <nombre>_resumen.txt y figuras PNG
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import LABELS, PLANES, SERIES_COLORS, hbar, load_series, load_studies, setup_style

AXIS_TO_PLANE = {0: "Sagittal", 1: "Coronal", 2: "Axial"}


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)

    def flush(self):
        for s in self.streams:
            s.flush()


def vendor(name) -> str:
    """Unifica las variantes de Manufacturer ('SIEMENS', 'Siemens Healthineers', ...)."""
    n = str(name).lower()
    for key, label in [("siemens", "Siemens"), ("philips", "Philips"), ("ge", "GE"), ("toshiba", "Canon/Toshiba"),
                       ("canon", "Canon/Toshiba"), ("hitachi", "Fujifilm/Hitachi"), ("fuji", "Fujifilm/Hitachi")]:
        if n.startswith(key) or key in n.split():
            return label
    return "(sin dato)" if name is None or n in ("", "none", "nan") else str(name)


def top(df, col, n=12):
    if col not in df:
        return
    vc = df[col].value_counts(dropna=False).head(n)
    print(f"\n-- {col} ({df[col].nunique(dropna=True)} valores distintos)")
    print(pd.DataFrame({"n": vc, "%": (vc / len(df) * 100).round(1)}).to_string())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parquet", type=Path)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    df["fabricante"] = df.Manufacturer.map(vendor)
    stem = args.parquet.with_suffix("")
    log = open(f"{stem}_resumen.txt", "w")
    sys.stdout = Tee(sys.__stdout__, log)

    print(f"== {args.parquet.name}: {len(df):,} archivos, {df.SeriesInstanceUID.nunique():,} series, "
          f"{df.StudyInstanceUID.nunique():,} estudios")
    if "error" in df and df.error.notna().any():
        print(f"\n-- Archivos ilegibles: {df.error.notna().sum()}")
        print(df.error.value_counts().head(10).to_string())
        df = df[df.error.isna()]
    if "uid_coincide" in df:
        print(f"UID de cabecera distinto al de la ruta: {(~df.uid_coincide.astype(bool)).sum()}")

    # Una fila por serie para todo lo que es propiedad de la serie.
    ser = df.groupby("SeriesInstanceUID", as_index=False).first()
    ser = ser.merge(load_series(args.split), on=["StudyInstanceUID", "SeriesInstanceUID"], how="left")
    ser["matriz"] = ser.Rows.astype("Int64").astype(str) + "x" + ser.Columns.astype("Int64").astype(str)

    for col in ["Modality", "BodyPartExamined", "fabricante", "Manufacturer", "ManufacturerModelName",
                "MagneticFieldStrength", "MRAcquisitionType", "ScanningSequence", "ScanOptions",
                "TransferSyntax", "PhotometricInterpretation", "BitsAllocated", "BitsStored",
                "PixelRepresentation", "NumberOfFrames", "matriz", "Laterality", "PatientPosition",
                "SeriesDescription"]:
        top(ser, col)

    num = ["px_row_mm", "SliceThickness", "SpacingBetweenSlices", "RepetitionTime", "EchoTime",
           "FlipAngle", "RescaleSlope", "RescaleIntercept", "oblicuidad"]
    num = [c for c in num if c in ser]
    print("\n-- Parámetros numéricos (por serie)\n",
          ser[num].describe(percentiles=[.01, .25, .5, .75, .99]).T.round(3).to_string())
    print("\n-- Faltantes por columna (%)\n",
          (ser.isna().mean() * 100).round(1).loc[lambda s: s > 0].sort_values(ascending=False).to_string())
    if "px_row_mm" in ser:
        print(f"Píxel anisotrópico en el plano: {(np.abs(ser.px_row_mm - ser.px_col_mm) > 1e-3).mean():.1%}")

    if {"eje_normal", "Anatomical_Plane"} <= set(ser.columns):
        ser["plano_geom"] = ser.eje_normal.map(AXIS_TO_PLANE)
        print("\n-- Plano del CSV vs plano derivado de ImageOrientationPatient\n",
              pd.crosstab(ser.Anatomical_Plane, ser.plano_geom, dropna=False).to_string())

    if "EchoTime" in ser and "Fluid_Sensitive" in ser:
        print("\n-- TE / TR según Fluid_Sensitive\n",
              ser.groupby("Fluid_Sensitive")[["EchoTime", "RepetitionTime"]].describe().round(0).T.to_string())

    # Pacientes: estudios repetidos del mismo paciente obligan a dividir por grupo en la validación.
    pat = df.groupby("StudyInstanceUID").PatientID.agg(lambda s: s.dropna().unique())
    multi = pat.map(len).gt(1).sum()
    pat = pat.map(lambda a: a[0] if len(a) else None)
    per_pat = pat.value_counts()
    print(f"\n-- Pacientes: {pat.nunique():,} PatientID distintos en {len(pat):,} estudios; "
          f"{(per_pat > 1).sum():,} pacientes con más de un estudio (máx {per_pat.max() if len(per_pat) else 0}); "
          f"estudios con varios PatientID: {multi}; sin PatientID: {pat.isna().sum()}")
    top(df.groupby("StudyInstanceUID", as_index=False).first(), "PatientSex")

    if args.split == "train":
        st = load_studies("train")
        labeled = set(st.StudyInstanceUID[st[LABELS].notna().all(axis=1)])
        first = df.groupby("StudyInstanceUID").first()
        first["etiquetado"] = first.index.isin(labeled)
        print("\n-- Fabricante: etiquetados vs resto (% por columna)\n",
              (pd.crosstab(first.fabricante, first.etiquetado, normalize="columns") * 100).round(1).to_string())

    if "px_max" in df:
        px = ["px_min", "px_p01", "px_p50", "px_p99", "px_p999", "px_max", "px_mean", "px_frac_cero"]
        print("\n-- Intensidades crudas (un corte por serie)\n",
              df[px].describe(percentiles=[.01, .5, .99]).T.round(2).to_string())
        print("\n-- p99 de intensidad por fabricante\n",
              df.groupby("fabricante").px_p99.describe().round(0).to_string())
        top(df, "px_dtype")

    if df.groupby("SeriesInstanceUID").size().max() > 5 and "pos_normal_mm" in df:
        g = df.sort_values("pos_normal_mm").groupby("SeriesInstanceUID").pos_normal_mm
        gaps = g.apply(lambda s: np.diff(s.to_numpy()))
        step = gaps.map(lambda d: float(np.median(d)) if len(d) else np.nan)
        irregular = gaps.map(lambda d: bool(len(d) and (np.abs(d - np.median(d)) > 0.1 * max(np.median(d), 1e-6)).any()))
        dup = gaps.map(lambda d: bool((np.abs(d) < 1e-3).any()))
        print("\n-- Geometría entre cortes (parquet con todos los cortes)")
        print(step.describe(percentiles=[.01, .5, .99]).round(2).to_string())
        print(f"Series con espaciado irregular: {irregular.mean():.1%}; con posiciones repetidas: {dup.mean():.1%}")

    plt = setup_style()
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2))
    for ax, col, title in [(axes[0, 0], "fabricante", "Fabricante"), (axes[0, 1], "matriz", "Tamaño de matriz (filas x columnas)")]:
        vc = ser[col].fillna("(sin dato)").value_counts()
        if len(vc) > 10:
            vc = pd.concat([vc.head(9), pd.Series({"Otros": vc.iloc[9:].sum()})])
        hbar(ax, vc.index, vc.values)
        ax.set(title=title, xlabel="series")
    for ax, col, title, unit in [(axes[1, 0], "px_row_mm", "Tamaño de píxel", "mm"),
                                 (axes[1, 1], "SliceThickness", "Grosor de corte", "mm")]:
        hi = ser[col].quantile(0.995)
        data = [ser.loc[ser.Anatomical_Plane == p, col].dropna().clip(upper=hi) for p in PLANES]
        ax.hist(data, bins=40, stacked=True, color=SERIES_COLORS[:3], label=PLANES, edgecolor="#fcfcfb", linewidth=0.4)
        ax.set(title=title, xlabel=f"{unit} (recortado al p99.5)", ylabel="series")
        ax.grid(axis="x", visible=False)
        ax.legend()
    fig.tight_layout()
    fig.savefig(f"{stem}_adquisicion.png")

    if {"EchoTime", "RepetitionTime", "Fluid_Sensitive"} <= set(ser.columns):
        fig, ax = plt.subplots(figsize=(6.5, 4.6))
        for flag, name, color in [(0, "No sensible a líquido", SERIES_COLORS[1]), (1, "Sensible a líquido", SERIES_COLORS[0])]:
            s = ser[ser.Fluid_Sensitive == flag]
            ax.scatter(s.EchoTime, s.RepetitionTime, s=9, alpha=0.35, color=color, label=name, linewidths=0)
        ax.set(title="TE vs TR por tipo de secuencia", xlabel="Echo Time (ms)", ylabel="Repetition Time (ms)",
               xlim=(0, ser.EchoTime.quantile(0.995) * 1.05), ylim=(0, ser.RepetitionTime.quantile(0.995) * 1.05))
        leg = ax.legend(markerscale=2.5)
        for h in leg.legend_handles:
            h.set_alpha(1)
        fig.savefig(f"{stem}_te_tr.png")

    sys.stdout = sys.__stdout__
    log.close()
    print(f"\nResumen en {stem}_resumen.txt")


if __name__ == "__main__":
    main()
