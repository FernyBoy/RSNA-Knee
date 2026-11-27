"""Extracción de metadatos DICOM a un DataFrame (una fila por serie)."""

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pydicom
from tqdm import tqdm

# Campos que son iguales para todos los cortes de una serie.
CAMPOS = [
    "PatientID", "PatientSex", "Laterality", "BodyPartExamined", "PatientPosition",
    "Manufacturer", "ManufacturerModelName", "MagneticFieldStrength", "ReceiveCoilName",
    "SeriesDescription", "ImageType", "ScanningSequence", "SequenceVariant",
    "MRAcquisitionType", "RepetitionTime", "EchoTime", "InversionTime", "FlipAngle",
    "EchoTrainLength", "ContrastBolusAgent",
    "Rows", "Columns", "PixelSpacing", "SliceThickness", "SpacingBetweenSlices",
    "ImageOrientationPatient",
    "BitsStored", "PixelRepresentation", "PhotometricInterpretation",
    "WindowCenter", "WindowWidth", "RescaleSlope", "RescaleIntercept",
]


def _valor(v):
    """Convierte un valor de pydicom a algo que se pueda guardar en un CSV."""
    if v is None or v == "":
        return None
    if isinstance(v, pydicom.multival.MultiValue):
        return "\\".join(str(x) for x in v)  # "\" es el separador nativo de DICOM
    return str(v)


def leer_serie(carpeta_serie: Path) -> dict:
    """Lee la cabecera del primer .dcm de una serie y cuenta sus archivos."""
    archivos = sorted(carpeta_serie.glob("*.dcm"))
    fila = {
        "StudyInstanceUID": carpeta_serie.parent.name,
        "SeriesInstanceUID": carpeta_serie.name,
        "n_dcm": len(archivos),
    }
    if archivos:
        # stop_before_pixels=True: solo lee la cabecera, no la imagen.
        ds = pydicom.dcmread(archivos[0], stop_before_pixels=True)
        for campo in CAMPOS:
            fila[campo] = _valor(ds.get(campo))
    return fila


def extraer_metadatos(raiz: Path, procesos: int = 8) -> pd.DataFrame:
    """Recorre raiz/<StudyInstanceUID>/<SeriesInstanceUID>/ y regresa un DataFrame."""
    series = sorted(p for p in Path(raiz).glob("*/*") if p.is_dir())
    with ProcessPoolExecutor(max_workers=procesos) as ex:
        filas = list(tqdm(ex.map(leer_serie, series, chunksize=32), total=len(series)))
    return pd.DataFrame(filas)
