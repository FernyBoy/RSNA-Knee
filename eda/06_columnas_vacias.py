#!/usr/bin/env python
"""Mide qué columnas están vacías: las de los CSV y TODAS las etiquetas DICOM de primer nivel.

Lee un corte por serie (el central por nombre de archivo). Una etiqueta cuenta como vacía
si no existe en el archivo o si existe sin valor ('' , lista o secuencia vacía).

Uso:  python 06_columnas_vacias.py [--split train] [--workers 8] [--sample-studies N]
Salida: $KNEE_EDA_OUT/vacios/vacios_dicom_<split>.csv y vacios_csv_<split>.csv
"""
from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from multiprocessing import Pool

import pandas as pd
import pydicom
from tqdm import tqdm

from common import load_series, load_studies, out_dir, series_dir


def scan(task: tuple[str, str, str]) -> list[tuple[str, bool, str]] | None:
    split, study, series = task
    d = series_dir(split, study, series)
    names = sorted(n for n in os.listdir(d) if n.endswith(".dcm"))
    if not names:
        return None
    try:
        ds = pydicom.dcmread(d / names[len(names) // 2], stop_before_pixels=True)
    except Exception:
        return None
    rows = []
    for elem in ds:
        key = elem.keyword or f"Privada {elem.tag}"
        value = elem.value
        if elem.VR == "SQ":
            empty, text = len(value) == 0, f"<secuencia de {len(value)}>"
        else:
            text = "" if value is None else str(value).strip()
            empty = text in ("", "[]")
        rows.append((key, empty, text[:60]))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 8)))
    ap.add_argument("--sample-studies", type=int, default=0)
    args = ap.parse_args()
    out = out_dir("vacios")

    # ---------- CSV ----------
    rows = []
    for name, df in [(f"{args.split}.csv", load_studies(args.split)), (f"{args.split}_series.csv", load_series(args.split))]:
        for col in df.columns:
            blank = df[col].isna() | df[col].astype(str).str.strip().eq("")
            rows.append({"archivo": name, "columna": col, "filas": len(df), "vacias": int(blank.sum()),
                         "pct_vacio": round(blank.mean() * 100, 2), "valores_distintos": df[col].nunique()})
    csv_report = pd.DataFrame(rows)
    csv_report.to_csv(out / f"vacios_csv_{args.split}.csv", index=False)
    print("== Columnas de los CSV\n", csv_report.to_string(index=False))

    # ---------- DICOM ----------
    series = load_series(args.split)
    if args.sample_studies:
        uids = series.StudyInstanceUID.drop_duplicates().sample(args.sample_studies, random_state=0)
        series = series[series.StudyInstanceUID.isin(uids)]
    tasks = [(args.split, s, r) for s, r in zip(series.StudyInstanceUID, series.SeriesInstanceUID)]

    present, blank, values = Counter(), Counter(), defaultdict(Counter)
    n_files = n_failed = 0
    with Pool(args.workers) as pool:
        for rows in tqdm(pool.imap_unordered(scan, tasks, chunksize=32), total=len(tasks), mininterval=5):
            if rows is None:
                n_failed += 1
                continue
            n_files += 1
            for key, empty, text in rows:
                present[key] += 1
                if empty:
                    blank[key] += 1
                elif len(values[key]) < 5000 or text in values[key]:
                    values[key][text] += 1

    rep = pd.DataFrame({"etiqueta": list(present)})
    rep["ausente"] = n_files - rep.etiqueta.map(present)
    rep["presente_sin_valor"] = rep.etiqueta.map(blank).fillna(0).astype(int)
    rep["con_valor"] = n_files - rep.ausente - rep.presente_sin_valor
    rep["pct_vacio"] = ((1 - rep.con_valor / n_files) * 100).round(2)
    rep["valores_distintos"] = rep.etiqueta.map(lambda k: len(values[k]))
    rep["valor_mas_comun"] = rep.etiqueta.map(lambda k: values[k].most_common(1)[0][0] if values[k] else "")
    rep["pct_valor_mas_comun"] = rep.etiqueta.map(
        lambda k: round(values[k].most_common(1)[0][1] / n_files * 100, 2) if values[k] else 0.0)
    rep = rep.sort_values(["pct_vacio", "etiqueta"], ascending=[False, True])
    rep.to_csv(out / f"vacios_dicom_{args.split}.csv", index=False)

    print(f"\n== DICOM: {n_files:,} archivos leídos (uno por serie), {n_failed} fallidos, "
          f"{len(rep)} etiquetas distintas ({rep.etiqueta.str.startswith('Privada').sum()} privadas)")
    pd.set_option("display.width", 250)
    print(rep.to_string(index=False))
    print(f"\nSalidas en {out}")


if __name__ == "__main__":
    main()
