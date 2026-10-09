#!/usr/bin/env python
"""Verifica la geometría y la consistencia interna de cada serie a partir del parquet
con TODAS las cabeceras (03_extraer_cabeceras.py --per-series 0). No abre ningún DICOM.

Por serie comprueba:
  - consistencia entre cortes: matriz, tamaño de píxel, grosor, plano e inclinación;
  - espaciado: posiciones repetidas, pasos irregulares y huecos compatibles con cortes faltantes;
  - si InstanceNumber sigue el orden espacial y si el paso medido coincide con el declarado;
  - parámetros de adquisición que cambian dentro de la serie (TE, TR, ImageType...).

Uso:  python 08_verificar_series.py RUTA.parquet [--out DIR] [--split train]
Salidas en DIR (por defecto, junto al parquet):
  verificacion_series.parquet   una fila por serie con todas las medidas e indicadores
  series_con_problemas.csv      solo las series con algún problema de geometría
  verificacion_resumen.txt      el resumen que también se imprime
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from common import load_series

KEY = "SeriesInstanceUID"
DUP_TOL_MM = 1e-3   # dos cortes a menos de esta distancia ocupan la misma posición
TOL_REL = 0.10      # un paso es irregular si se aparta más del 10 % del paso mediano de su serie
OBL_TOL = 1e-3      # variación admitida de la inclinación del plano entre cortes

CONSISTENCY = ["Rows", "Columns", "px_row_r", "px_col_r", "SliceThickness", "eje_normal",
               "EchoTime", "RepetitionTime", "ImageType", "SeriesDescription", "PatientID",
               "BitsStored", "PixelRepresentation"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parquet", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    args = ap.parse_args()
    out = args.out or args.parquet.parent
    out.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    df = pd.read_parquet(args.parquet)
    n_files = len(df)
    n_err = int(df["error"].notna().sum()) if "error" in df else 0
    if n_err:
        df = df[df["error"].isna()]
    df["px_row_r"] = df.px_row_mm.round(4)
    df["px_col_r"] = df.px_col_mm.round(4)

    # ---------- Consistencia entre cortes ----------
    g = df.groupby(KEY, sort=False)
    ser = g.size().rename("n_cortes").to_frame()
    if ser.n_cortes.max() < 5:
        raise SystemExit("El parquet no parece tener todos los cortes (usa --per-series 0 al extraer).")
    for col in CONSISTENCY:
        if col in df:
            ser[f"nd_{col}"] = g[col].nunique(dropna=True)
    ser["obl_rango"] = g.oblicuidad.max() - g.oblicuidad.min()
    ser["sin_posicion"] = df.pos_normal_mm.isna().groupby(df[KEY]).sum()
    ser["nd_instance"] = g.InstanceNumber.nunique(dropna=True)
    first_cols = [c for c in ["StudyInstanceUID", "SpacingBetweenSlices", "MRAcquisitionType", "Manufacturer"] if c in df]
    ser = ser.join(g[first_cols].first())

    # ---------- Espaciado entre cortes ----------
    d = df.dropna(subset=["pos_normal_mm"]).sort_values([KEY, "pos_normal_mm"]).copy()
    gd = d.groupby(KEY, sort=False)
    d["paso"] = gd.pos_normal_mm.diff()
    d["inst_diff"] = gd.InstanceNumber.diff()
    # El paso mediano se calcula solo con pasos positivos: en series con cada posición
    # duplicada (p. ej. dos ecos) la mediana de todos los pasos sería cero.
    paso_mediano = d.loc[d.paso > DUP_TOL_MM].groupby(KEY).paso.median().rename("paso_mediano")
    d = d.join(paso_mediano, on=KEY)
    valid = d.paso.notna()
    ratio = d.paso / d.paso_mediano
    k = ratio.round()
    d["dup"] = valid & (d.paso.abs() <= DUP_TOL_MM)
    d["irregular"] = valid & ~d.dup & ((ratio - 1).abs() > TOL_REL)
    d["hueco"] = d.irregular & (k >= 2) & ((ratio - k).abs() <= TOL_REL * k)
    d["faltantes"] = np.where(d.hueco, k - 1, 0)
    geo = d.groupby(KEY).agg(
        n_pos_repetidas=("dup", "sum"), n_pasos_irregulares=("irregular", "sum"),
        n_huecos=("hueco", "sum"), cortes_faltantes_est=("faltantes", "sum"),
        paso_min=("paso", "min"), paso_max=("paso", "max"),
    )
    ser = ser.join(geo).join(paso_mediano)
    for col in ["n_pos_repetidas", "n_pasos_irregulares", "n_huecos", "cortes_faltantes_est"]:
        ser[col] = ser[col].fillna(0).astype(int)

    # InstanceNumber frente al orden espacial: debe crecer o decrecer siempre.
    nz = d[d.inst_diff.notna()]
    sign = np.sign(nz.inst_diff).groupby(nz[KEY])
    monotono = ((sign.min() == sign.max()) & (sign.min() != 0)).rename("instance_monotono")
    ser = ser.join(monotono)

    csv = load_series(args.split).set_index(KEY)[["Anatomical_Plane", "Fluid_Sensitive"]]
    ser = ser.join(csv)

    # ---------- Indicadores ----------
    def nd(col: str) -> pd.Series:
        name = f"nd_{col}"
        return ser[name] if name in ser else pd.Series(0, index=ser.index)

    geometry = {
        "matriz distinta entre cortes": (nd("Rows") > 1) | (nd("Columns") > 1),
        "tamaño de píxel distinto entre cortes": (nd("px_row_r") > 1) | (nd("px_col_r") > 1),
        "grosor distinto entre cortes": nd("SliceThickness") > 1,
        "plano distinto entre cortes": nd("eje_normal") > 1,
        "inclinación variable entre cortes": ser.obl_rango > OBL_TOL,
        "cortes sin posición": ser.sin_posicion > 0,
        "posiciones repetidas": ser.n_pos_repetidas > 0,
        "espaciado irregular": ser.n_pasos_irregulares > 0,
    }
    other = {
        "espaciado irregular compatible con cortes faltantes": ser.n_huecos > 0,
        "paso medido distinto de SpacingBetweenSlices (>10 %)":
            ((ser.paso_mediano / ser.SpacingBetweenSlices - 1).abs() > TOL_REL).fillna(False),
        "InstanceNumber repetido": ser.nd_instance < ser.n_cortes,
        "InstanceNumber no sigue el orden espacial": ser.instance_monotono.eq(False),
        "más de un TE": nd("EchoTime") > 1,
        "más de un TR": nd("RepetitionTime") > 1,
        "más de un ImageType": nd("ImageType") > 1,
        "más de una SeriesDescription": nd("SeriesDescription") > 1,
        "más de un PatientID": nd("PatientID") > 1,
        "BitsStored o PixelRepresentation distinto entre cortes": (nd("BitsStored") > 1) | (nd("PixelRepresentation") > 1),
    }
    for i, (name, mask) in enumerate({**geometry, **other}.items()):
        ser[f"f{i:02d}"] = mask.astype(bool)
    flag_names = {f"f{i:02d}": name for i, name in enumerate({**geometry, **other})}
    geo_cols = list(flag_names)[: len(geometry)]
    ser["problema_geometria"] = ser[geo_cols].any(axis=1)

    # ---------- Resumen ----------
    n_ser, n_est = len(ser), ser.StudyInstanceUID.nunique()
    say(f"== {args.parquet.name}: {n_files:,} archivos ({n_err} ilegibles), {n_ser:,} series, {n_est:,} estudios")
    say(f"Tolerancias: posición repetida < {DUP_TOL_MM} mm; paso irregular > {TOL_REL:.0%} del paso mediano de la serie")

    def table(title: str, cols: list[str]) -> None:
        say(f"\n-- {title}")
        say(f"{'indicador':<58}{'series':>8}{'% series':>10}{'estudios':>10}")
        for col in cols:
            mask = ser[col]
            say(f"{flag_names[col]:<58}{int(mask.sum()):>8,}{mask.mean() * 100:>10.2f}"
                f"{ser.loc[mask, 'StudyInstanceUID'].nunique():>10,}")

    table("Geometría", geo_cols)
    bad = ser[ser.problema_geometria]
    say(f"\nSeries con al menos un problema de geometría: {len(bad):,} ({len(bad) / n_ser:.2%}); "
        f"estudios afectados: {bad.StudyInstanceUID.nunique():,} de {n_est:,}")
    table("Otros indicadores (no implican por sí solos un problema)", list(flag_names)[len(geometry):])

    rep = ser[ser.n_pos_repetidas > 0]
    if len(rep):
        multi = (rep.get("nd_EchoTime", 0) > 1) | (rep.get("nd_ImageType", 0) > 1)
        say(f"\nPosiciones repetidas: {int(multi.sum()):,} de {len(rep):,} series tienen además más de un TE "
            f"o ImageType (varias imágenes por posición, esperable); {int((~multi).sum()):,} no.")
    irr = ser[ser.n_pasos_irregulares > 0]
    if len(irr):
        say(f"Espaciado irregular: {int((irr.n_huecos > 0).sum()):,} de {len(irr):,} series son compatibles con "
            f"cortes faltantes (≈{int(irr.cortes_faltantes_est.sum()):,} cortes en total).")

    for col, title in [("Anatomical_Plane", "plano"), ("MRAcquisitionType", "tipo de adquisición")]:
        if col in ser and len(bad):
            tab = pd.crosstab(ser[col].fillna("(sin dato)"), ser.problema_geometria)
            tab.columns = ["sin problema" if not c else "con problema" for c in tab.columns]
            say(f"\n-- Problemas de geometría por {title}\n{tab.to_string()}")

    if len(bad):
        show = ["StudyInstanceUID", "Anatomical_Plane", "n_cortes", "n_pos_repetidas", "n_pasos_irregulares",
                "cortes_faltantes_est", "paso_mediano", "paso_min", "paso_max"]
        worst = bad.sort_values(["n_pasos_irregulares", "n_pos_repetidas"], ascending=False).head(15)
        say("\n-- Las 15 series con más pasos irregulares o posiciones repetidas")
        say(worst[show].round(2).to_string())

    ser = ser.rename(columns=flag_names)
    ser.reset_index().to_parquet(out / "verificacion_series.parquet", index=False)
    ser[ser.problema_geometria].reset_index().to_csv(out / "series_con_problemas.csv", index=False)
    (out / "verificacion_resumen.txt").write_text("\n".join(lines) + "\n")
    print(f"\nSalidas en {out}")


if __name__ == "__main__":
    main()
