#!/usr/bin/env python
"""Inventario del disco frente a los CSV: qué series existen y cuántos cortes tiene cada una.

Solo lista directorios (no abre DICOM), así que es seguro en el nodo de login.

Uso:  python 02_inventario_disco.py [--split train] [--workers 16]
Salidas en $KNEE_EDA_OUT/inventario: inventario_<split>.parquet y cortes_por_serie.png
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from tqdm import tqdm

from common import DATA_ROOT, PLANES, SERIES_COLORS, load_series, load_studies, out_dir, setup_style


def scan_study(study_dir: str) -> list[tuple[str, str, int, int]]:
    study = os.path.basename(study_dir)
    rows = []
    with os.scandir(study_dir) as it:
        for entry in it:
            if not entry.is_dir():
                rows.append((study, entry.name, -1, 0))
                continue
            names = os.listdir(entry.path)
            n_dcm = sum(n.endswith(".dcm") for n in names)
            rows.append((study, entry.name, n_dcm, len(names) - n_dcm))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    out = out_dir("inventario")
    root = DATA_ROOT / f"{args.split}_series"
    study_dirs = [e.path for e in os.scandir(root) if e.is_dir()]
    with ThreadPoolExecutor(args.workers) as pool:
        rows = [r for chunk in tqdm(pool.map(scan_study, study_dirs), total=len(study_dirs), desc="estudios")
                for r in chunk]
    disk = pd.DataFrame(rows, columns=["StudyInstanceUID", "SeriesInstanceUID", "n_dcm", "n_otros"])

    series, studies = load_series(args.split), load_studies(args.split)
    inv = series.merge(disk, on=["StudyInstanceUID", "SeriesInstanceUID"], how="outer", indicator="origen")
    inv["origen"] = inv.origen.map({"both": "csv+disco", "left_only": "solo_csv", "right_only": "solo_disco"})
    inv.to_parquet(out / f"inventario_{args.split}.parquet", index=False)

    print(f"== {args.split}: {disk.StudyInstanceUID.nunique():,} estudios y {len(disk):,} series en disco, "
          f"{disk.n_dcm.clip(lower=0).sum():,} archivos .dcm")
    print("\n-- Cruce CSV / disco (series)\n", inv.origen.value_counts().to_string())
    print(f"Estudios en {args.split}.csv sin carpeta: "
          f"{len(set(studies.StudyInstanceUID) - set(disk.StudyInstanceUID))}")
    ok = inv[inv.origen == "csv+disco"]
    print(f"Series vacías: {(ok.n_dcm == 0).sum()}, con archivos que no son .dcm: {(inv.n_otros > 0).sum()}, "
          f"entradas sueltas a nivel de serie: {(inv.n_dcm == -1).sum()}")
    print("\n-- Cortes por serie\n", ok.n_dcm.describe().round(1).to_string())
    print("\n-- Cortes por serie según plano\n",
          ok.groupby("Anatomical_Plane").n_dcm.describe().round(1).reindex(PLANES).to_string())
    print("\n-- Cortes por estudio\n", ok.groupby("StudyInstanceUID").n_dcm.sum().describe().round(1).to_string())
    print("\n-- Series con más cortes\n",
          ok.nlargest(10, "n_dcm")[["StudyInstanceUID", "SeriesInstanceUID", "Anatomical_Plane", "n_dcm"]].to_string(index=False))
    print(f"Series con < 10 cortes: {(ok.n_dcm < 10).sum()}; con > 100: {(ok.n_dcm > 100).sum()}")

    if len(ok) > 50:
        plt = setup_style()
        hi = ok.n_dcm.quantile(0.99)
        fig, axes = plt.subplots(1, 3, figsize=(12, 3.2), sharex=True, sharey=True)
        for ax, plane, color in zip(axes, PLANES, SERIES_COLORS):
            vals = ok.n_dcm[ok.Anatomical_Plane == plane].clip(upper=hi)
            ax.hist(vals, bins=50, range=(0, hi), color=color, edgecolor="#fcfcfb", linewidth=0.4)
            ax.set(title=f"{plane} (mediana {vals.median():.0f})", xlabel="cortes por serie (recortado al p99)")
            ax.grid(axis="x", visible=False)
        axes[0].set_ylabel("series")
        fig.savefig(out / f"cortes_por_serie_{args.split}.png")
    print(f"\nSalidas en {out}")


if __name__ == "__main__":
    main()
