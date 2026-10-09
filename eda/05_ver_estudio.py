#!/usr/bin/env python
"""Genera un mosaico PNG de un estudio: una fila por serie, N cortes equiespaciados.

Uso:
  python 05_ver_estudio.py --study <StudyInstanceUID>
  python 05_ver_estudio.py --random 3 [--labeled]     # estudios al azar
Salida: $KNEE_EDA_OUT/mosaicos/<StudyInstanceUID>.png (+ .txt con informe y etiquetas)
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pydicom

from common import INK_2, LABELS, PLANES, load_series, load_studies, out_dir, series_dir, setup_style


def load_volume(path, n_slices: int):
    """Devuelve (cortes ordenados espacialmente, cabecera de un corte, n total de cortes)."""
    names = sorted(n for n in os.listdir(path) if n.endswith(".dcm"))
    headers = []
    for n in names:
        ds = pydicom.dcmread(path / n, stop_before_pixels=True)
        iop, pos = ds.get("ImageOrientationPatient"), ds.get("ImagePositionPatient")
        if iop is not None and pos is not None:
            iop = np.asarray(iop, dtype=float)
            key = float(np.dot(np.cross(iop[:3], iop[3:]), np.asarray(pos, dtype=float)))
        else:
            key = float(ds.get("InstanceNumber", 0))
        headers.append((key, n))
    headers.sort()
    if not headers:
        return [], None, 0
    idx = np.unique(np.linspace(0, len(headers) - 1, n_slices).round().astype(int))
    slices, ds = [], None
    for i in idx:
        ds = pydicom.dcmread(path / headers[i][1])
        arr = ds.pixel_array.astype(np.float32)
        if arr.ndim == 3:  # multiframe: nos quedamos con el cuadro central
            arr = arr[arr.shape[0] // 2]
        if ds.get("PhotometricInterpretation") == "MONOCHROME1":
            arr = arr.max() - arr
        slices.append((int(i), arr))
    return slices, ds, len(headers)


def render(study_uid: str, split: str, n_slices: int, studies, series, plt, out):
    rows = series[series.StudyInstanceUID == study_uid].copy()
    if rows.empty:
        raise SystemExit(f"Estudio no encontrado en {split}_series.csv: {study_uid}")
    rows["orden"] = rows.Anatomical_Plane.map({p: i for i, p in enumerate(PLANES)})
    rows = rows.sort_values(["orden", "Fluid_Sensitive"])

    height = 2.2 * len(rows) + 0.4
    fig, axes = plt.subplots(len(rows), n_slices, figsize=(1.9 * n_slices, height), squeeze=False,
                             facecolor="black", gridspec_kw={"wspace": 0.03, "hspace": 0.16})
    fig.subplots_adjust(left=0.005, right=0.995, bottom=0.005, top=1 - 0.6 / height)
    for ax in axes.ravel():
        ax.axis("off")
    for r, row in enumerate(rows.itertuples()):
        slices, ds, total = load_volume(series_dir(split, study_uid, row.SeriesInstanceUID), n_slices)
        if not slices:
            continue
        # Ventana común a toda la serie para que los cortes sean comparables entre sí.
        lo, hi = np.percentile(np.concatenate([a.ravel() for _, a in slices]), [0.5, 99.5])
        spacing = ds.get("PixelSpacing")
        aspect = float(spacing[0]) / float(spacing[1]) if spacing is not None and len(spacing) == 2 else 1
        for c, (i, arr) in enumerate(slices):
            axes[r, c].imshow(arr, cmap="gray", vmin=lo, vmax=max(hi, lo + 1), aspect=aspect)
            axes[r, c].text(0.03, 0.03, f"{i + 1}/{total}", transform=axes[r, c].transAxes,
                            color="#c3c2b7", fontsize=6.5, va="bottom")
        tag = "FS" if row.Fluid_Sensitive else "no-FS"
        axes[r, 0].set_title(
            f"{row.Anatomical_Plane} · {tag} · {ds.get('SeriesDescription', '')} · "
            f"{ds.Rows}x{ds.Columns} · {total} cortes · TE {ds.get('EchoTime', '?')} / TR {ds.get('RepetitionTime', '?')}",
            loc="left", color="#f0efec", fontsize=8, fontweight="normal")

    info = studies[studies.StudyInstanceUID == study_uid]
    text = [f"StudyInstanceUID: {study_uid}"]
    if len(info) and "Report" in info:
        rec = info.iloc[0]
        if rec[LABELS].notna().all():
            pos = [l for l in LABELS if rec[l] == 1]
            text.append("Etiquetas positivas: " + (", ".join(pos) if pos else "ninguna"))
            fig.suptitle("Positivos: " + (", ".join(pos) if pos else "ninguno"),
                         color="#f0efec", fontsize=9, x=0.006, y=1 - 0.12 / height, ha="left", va="top")
        else:
            text.append("Etiquetas: sin etiquetar")
        text.append("\nInforme:\n" + str(rec.Report))
    fig.savefig(out / f"{study_uid}.png", dpi=110, facecolor="black", bbox_inches=None)
    plt.close(fig)
    (out / f"{study_uid}.txt").write_text("\n".join(text))
    print(out / f"{study_uid}.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    ap.add_argument("--study", nargs="*", default=[])
    ap.add_argument("--random", type=int, default=0, help="número de estudios al azar")
    ap.add_argument("--labeled", action="store_true", help="con --random, solo estudios etiquetados")
    ap.add_argument("--slices", type=int, default=8)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    studies, series = load_studies(args.split), load_series(args.split)
    uids = list(args.study)
    if args.random:
        pool = studies
        if args.labeled and args.split == "train":
            pool = studies[studies[LABELS].notna().all(axis=1)]
        uids += pool.StudyInstanceUID.sample(args.random, random_state=args.seed).tolist()
    if not uids:
        ap.error("indica --study UID o --random N")

    plt = setup_style()
    out = out_dir("mosaicos")
    for uid in uids:
        render(uid, args.split, args.slices, studies, series, plt, out)


if __name__ == "__main__":
    main()
