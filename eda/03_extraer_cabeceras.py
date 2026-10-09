#!/usr/bin/env python
"""Extrae las cabeceras DICOM a un parquet (una fila por archivo leído).

Por defecto lee UN corte por serie (el central por nombre de archivo): ~24 mil lecturas.
Con --per-series 0 lee todos los cortes (~820 mil): lanzarlo con SLURM (jobs/cabeceras.slurm).

Uso:
  python 03_extraer_cabeceras.py --sample-studies 50          # prueba rápida
  python 03_extraer_cabeceras.py --pixel-stats                # 1 corte por serie + intensidades
  python 03_extraer_cabeceras.py --per-series 0 --workers 64  # barrido completo
Salida: $KNEE_EDA_OUT/dicom/cabeceras_<split>_<modo>.parquet
"""
from __future__ import annotations

import argparse
import os
from multiprocessing import Pool

import numpy as np
import pandas as pd
import pydicom
from tqdm import tqdm

from common import load_series, out_dir, series_dir

SCALAR_TAGS = [
    "PatientID", "PatientSex", "PatientAge", "Modality", "Manufacturer", "ManufacturerModelName",
    "SeriesDescription", "BodyPartExamined", "Laterality", "ScanningSequence", "SequenceVariant",
    "ScanOptions", "MRAcquisitionType", "SliceThickness", "SpacingBetweenSlices", "RepetitionTime",
    "EchoTime", "InversionTime", "EchoTrainLength", "FlipAngle", "MagneticFieldStrength",
    "ReceiveCoilName", "PatientPosition", "SeriesNumber", "InstanceNumber", "SliceLocation",
    "NumberOfFrames", "Rows", "Columns", "BitsAllocated", "BitsStored", "PixelRepresentation",
    "PhotometricInterpretation", "SamplesPerPixel", "RescaleIntercept", "RescaleSlope",
    "WindowCenter", "WindowWidth", "ContrastBolusAgent",
]
NUMERIC = [
    "SliceThickness", "SpacingBetweenSlices", "RepetitionTime", "EchoTime", "InversionTime",
    "EchoTrainLength", "FlipAngle", "MagneticFieldStrength", "SeriesNumber", "InstanceNumber",
    "SliceLocation", "NumberOfFrames", "Rows", "Columns", "BitsAllocated", "BitsStored",
    "PixelRepresentation", "SamplesPerPixel", "RescaleIntercept", "RescaleSlope",
    "WindowCenter", "WindowWidth",
]
PIXEL_STATS = False


def _scalar(value):
    if value is None:
        return None
    if isinstance(value, pydicom.multival.MultiValue):
        if len(value) == 0:
            return None
        return "\\".join(str(v) for v in value)
    return str(value)


def read_one(task: tuple[str, str, str]) -> dict:
    study, series, path = task
    row = {"StudyInstanceUID": study, "SeriesInstanceUID": series, "archivo": os.path.basename(path)}
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=not PIXEL_STATS)
        row["TransferSyntax"] = ds.file_meta.TransferSyntaxUID.name
        row["uid_coincide"] = (str(ds.get("StudyInstanceUID")) == study
                               and str(ds.get("SeriesInstanceUID")) == series)
        for tag in SCALAR_TAGS:
            row[tag] = _scalar(ds.get(tag))
        row["ImageType"] = _scalar(ds.get("ImageType"))
        spacing = ds.get("PixelSpacing")
        if spacing is not None and len(spacing) == 2:
            row["px_row_mm"], row["px_col_mm"] = float(spacing[0]), float(spacing[1])
        pos, iop = ds.get("ImagePositionPatient"), ds.get("ImageOrientationPatient")
        if iop is not None and len(iop) == 6:
            iop = np.asarray(iop, dtype=float)
            normal = np.cross(iop[:3], iop[3:])
            # 0 = sagital (normal en x), 1 = coronal (y), 2 = axial (z), en coordenadas del paciente
            row["eje_normal"] = int(np.abs(normal).argmax())
            row["oblicuidad"] = float(1 - np.abs(normal).max())
            if pos is not None and len(pos) == 3:
                row["pos_normal_mm"] = float(np.dot(np.asarray(pos, dtype=float), normal))
        if PIXEL_STATS:
            arr = ds.pixel_array
            row["px_shape"] = "x".join(map(str, arr.shape))
            row["px_dtype"] = str(arr.dtype)
            p = np.percentile(arr, [1, 50, 99, 99.9])
            row.update(px_min=float(arr.min()), px_max=float(arr.max()), px_mean=float(arr.mean()),
                       px_std=float(arr.std()), px_p01=p[0], px_p50=p[1], px_p99=p[2], px_p999=p[3],
                       px_frac_cero=float((arr == 0).mean()))
    except Exception as exc:  # un archivo corrupto no debe tumbar el barrido
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return row


def list_tasks(args_tuple) -> list[tuple[str, str, str]]:
    split, study, series, per_series = args_tuple
    d = series_dir(split, study, series)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".dcm"))
    except FileNotFoundError:
        return []
    if per_series > 0 and len(names) > per_series:
        idx = np.linspace(0, len(names) - 1, per_series + 2)[1:-1].round().astype(int)
        names = [names[i] for i in idx]
    return [(study, series, str(d / n)) for n in names]


def _init(pixel_stats: bool):
    global PIXEL_STATS
    PIXEL_STATS = pixel_stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    ap.add_argument("--per-series", type=int, default=1, help="cortes por serie; 0 = todos")
    ap.add_argument("--sample-studies", type=int, default=0, help="muestra aleatoria de estudios; 0 = todos")
    ap.add_argument("--pixel-stats", action="store_true", help="decodifica el píxel y guarda estadísticas de intensidad")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 8)))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    series = load_series(args.split)
    if args.sample_studies:
        uids = series.StudyInstanceUID.drop_duplicates().sample(args.sample_studies, random_state=args.seed)
        series = series[series.StudyInstanceUID.isin(uids)]
    jobs = [(args.split, s, r, args.per_series) for s, r in zip(series.StudyInstanceUID, series.SeriesInstanceUID)]

    with Pool(args.workers, initializer=_init, initargs=(args.pixel_stats,)) as pool:
        tasks = [t for chunk in tqdm(pool.imap_unordered(list_tasks, jobs, chunksize=32),
                                     total=len(jobs), desc="listando series", mininterval=5) for t in chunk]
        rows = list(tqdm(pool.imap_unordered(read_one, tasks, chunksize=64),
                         total=len(tasks), desc="leyendo DICOM", mininterval=5))

    df = pd.DataFrame(rows)
    for col in NUMERIC:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    modo = ("todos" if args.per_series == 0 else f"{args.per_series}xserie") + ("_px" if args.pixel_stats else "")
    if args.sample_studies:
        modo += f"_muestra{args.sample_studies}"
    path = args.out or out_dir("dicom") / f"cabeceras_{args.split}_{modo}.parquet"
    df.to_parquet(path, index=False)
    n_err = int(df["error"].notna().sum()) if "error" in df else 0
    print(f"{len(df):,} cabeceras de {df.SeriesInstanceUID.nunique():,} series -> {path}  (errores: {n_err})")


if __name__ == "__main__":
    main()
