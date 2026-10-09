#!/usr/bin/env python
"""Genera el diccionario de datos (Markdown) con todas las columnas de los CSV y etiquetas DICOM.

Requiere haber ejecutado antes 06_columnas_vacias.py para train y test.

Uso:  python 07_diccionario_columnas.py
Salida: $KNEE_EDA_OUT/diccionario_columnas.md
"""
from __future__ import annotations

import pandas as pd
from pydicom.datadict import dictionary_VR, tag_for_keyword
from pydicom.tag import Tag

from common import DATA_ROOT, OUT_ROOT, out_dir

CSV_DESC = {
    "StudyInstanceUID": "Identificador del estudio; coincide con la carpeta de primer nivel",
    "SeriesInstanceUID": "Identificador de la serie; coincide con la subcarpeta",
    "Report": "Informe radiológico en texto libre, en varios idiomas",
    "Fluid_Sensitive": "1 si la secuencia es sensible a líquido",
    "Fat_Suppression": "1 si tiene supresión grasa (idéntica a Fluid_Sensitive en todas las filas)",
    "Anatomical_Plane": "Plano de adquisición: Sagittal, Coronal o Axial",
    "ACL": "Ligamento cruzado anterior", "MCL": "Ligamento colateral medial",
    "Medial Meniscus": "Menisco medial", "Lateral Meniscus": "Menisco lateral",
    "Medial OA": "Artrosis del compartimento medial", "Lateral OA": "Artrosis del compartimento lateral",
    "PF OA": "Artrosis patelofemoral", "Effusion": "Derrame articular", "Synovitis": "Sinovitis",
    "Baker's": "Quiste de Baker", "Contusion": "Contusión ósea", "Fracture": "Fractura",
}

GROUPS = {
    "Identificadores": {
        "StudyInstanceUID": "Identificador del estudio", "SeriesInstanceUID": "Identificador de la serie",
        "SOPInstanceUID": "Identificador del corte; coincide con el nombre del archivo",
        "SOPClassUID": "Tipo de objeto DICOM (MR Image Storage)",
        "FrameOfReferenceUID": "Sistema de coordenadas compartido entre series",
        "SeriesNumber": "Número de la serie dentro del estudio", "AcquisitionNumber": "Número de adquisición",
        "InstanceNumber": "Número del corte dentro de la serie",
    },
    "Paciente y estudio": {
        "PatientID": "Identificador anonimizado del paciente", "PatientSex": "Sexo (M, F, O)",
        "PatientPosition": "Posición en el equipo (FFS = pies primero, supino)",
        "BodyPartExamined": "Región anatómica declarada", "Laterality": "Lado: R o L",
        "Modality": "Modalidad (MR)", "SeriesDescription": "Nombre de la secuencia según el centro",
        "ContrastBolusAgent": "Agente de contraste",
    },
    "Equipo": {
        "Manufacturer": "Fabricante", "ManufacturerModelName": "Modelo del resonador",
        "MagneticFieldStrength": "Campo magnético en teslas", "SoftwareVersions": "Versión de software",
        "ReceiveCoilName": "Bobina receptora", "ReceiveCoilType": "Tipo de bobina receptora",
        "TransmitCoilName": "Bobina transmisora", "TransmitCoilType": "Tipo de bobina transmisora",
        "ImagingFrequency": "Frecuencia de resonancia en MHz",
    },
    "Secuencia de adquisición": {
        "ImageType": "Tipo de imagen (original/derivada, magnitud...)",
        "ScanningSequence": "Familia de secuencia (SE, GR, IR)", "SequenceVariant": "Variante de la secuencia",
        "ScanOptions": "Opciones (FS = supresión grasa, etc.)", "SequenceName": "Nombre interno de la secuencia",
        "PulseSequenceName": "Nombre de la secuencia de pulsos", "MRAcquisitionType": "Adquisición 2D o 3D",
        "RepetitionTime": "TR en ms", "EchoTime": "TE en ms", "InversionTime": "TI en ms",
        "EchoTrainLength": "Longitud del tren de ecos", "RFEchoTrainLength": "Longitud del tren de ecos de RF",
        "EchoNumbers": "Número de eco", "FlipAngle": "Ángulo de inclinación en grados",
        "VariableFlipAngleFlag": "Ángulo de inclinación variable (Y/N)",
        "NumberOfAverages": "Promedios (NEX)", "PixelBandwidth": "Ancho de banda por píxel en Hz",
        "AcquisitionMatrix": "Matriz de adquisición", "NumberOfPhaseEncodingSteps": "Pasos de codificación de fase",
        "MRAcquisitionPhaseEncodingStepsInPlane": "Pasos de fase en el plano",
        "MRAcquisitionPhaseEncodingStepsOutOfPlane": "Pasos de fase fuera del plano",
        "InPlanePhaseEncodingDirection": "Dirección de codificación de fase (ROW/COL)",
        "PercentSampling": "Porcentaje de muestreo", "PercentPhaseFieldOfView": "Porcentaje de campo de visión en fase",
        "ParallelAcquisition": "Adquisición en paralelo (YES/NO)",
        "ParallelAcquisitionTechnique": "Técnica de adquisición en paralelo",
        "ParallelReductionFactorInPlane": "Factor de aceleración en el plano",
        "ParallelReductionFactorOutOfPlane": "Factor de aceleración fuera del plano",
        "PartialFourier": "Fourier parcial (YES/NO)", "PartialFourierDirection": "Dirección del Fourier parcial",
        "DiffusionBValue": "Valor b de difusión", "DiffusionDirectionality": "Direccionalidad de la difusión",
        "DiffusionGradientOrientation": "Orientación del gradiente de difusión",
        "NumberOfTemporalPositions": "Número de posiciones temporales",
        "TemporalPositionIndex": "Índice de posición temporal",
    },
    "Geometría": {
        "ImagePositionPatient": "Posición (x, y, z) en mm de la esquina del corte",
        "ImageOrientationPatient": "Cosenos directores de filas y columnas",
        "SliceLocation": "Posición del corte en mm", "SliceThickness": "Grosor del corte en mm",
        "SpacingBetweenSlices": "Distancia entre centros de cortes en mm",
        "PixelSpacing": "Tamaño del píxel en mm (fila, columna)",
        "Rows": "Filas de la imagen", "Columns": "Columnas de la imagen",
        "StackID": "Identificador de pila", "InStackPositionNumber": "Posición del corte en la pila",
        "NumberOfFrames": "Cuadros por archivo",
    },
    "Codificación del píxel": {
        "BitsAllocated": "Bits reservados por píxel", "BitsStored": "Bits usados por píxel", "HighBit": "Bit más significativo",
        "PixelRepresentation": "0 = sin signo, 1 = con signo", "SamplesPerPixel": "Canales por píxel",
        "PhotometricInterpretation": "Interpretación fotométrica", "PlanarConfiguration": "Disposición de canales",
        "RescaleSlope": "Pendiente de reescalado", "RescaleIntercept": "Ordenada de reescalado",
        "RescaleType": "Unidad tras el reescalado",
        "WindowCenter": "Centro de ventana sugerido", "WindowWidth": "Ancho de ventana sugerido",
    },
}


def cell(text) -> str:
    text = "" if pd.isna(text) else str(text)
    return text.replace("|", "\\|").replace("\n", " ")[:45]


def main():
    vac = OUT_ROOT / "vacios"
    lines = ["# Diccionario de columnas: RSNA Knee Abnormality Detection", "",
             f"Datos en `{DATA_ROOT}`.", ""]

    lines += ["## Archivos CSV", ""]
    csv_stats = pd.concat([pd.read_csv(vac / f"vacios_csv_{s}.csv") for s in ("train", "test")])
    sub = pd.read_csv(DATA_ROOT / "sample_submission.csv")
    for name, grp in csv_stats.groupby("archivo", sort=False):
        lines += [f"### `{name}` ({grp.filas.iloc[0]:,} filas)", "",
                  "| Columna | Descripción | % con valor | Valores distintos |", "|---|---|---|---|"]
        for r in grp.itertuples():
            lines.append(f"| {r.columna} | {CSV_DESC.get(r.columna, '')} | {100 - r.pct_vacio:.1f} | {r.valores_distintos:,} |")
        lines.append("")
    lines += [f"### `sample_submission.csv` ({len(sub):,} filas)", "",
              "`StudyInstanceUID` y una probabilidad por cada una de las 12 etiquetas: "
              + ", ".join(sub.columns[1:]) + ".", ""]

    train = pd.read_csv(vac / "vacios_dicom_train.csv").set_index("etiqueta")
    test = pd.read_csv(vac / "vacios_dicom_test.csv").set_index("etiqueta")
    described = {k for g in GROUPS.values() for k in g}
    groups = dict(GROUPS)
    extra = sorted((set(train.index) | set(test.index)) - described)
    if extra:
        groups["Otras"] = {k: "" for k in extra}

    lines += ["## Etiquetas DICOM", "",
              f"{len(set(train.index) | set(test.index))} etiquetas de primer nivel, medidas sobre un corte por serie de train. "
              "\"% con valor\" descuenta las ausentes y las presentes sin valor. "
              "\"≥5000\" indica que el recuento de valores distintos se cortó en 5,000.", ""]
    for gname, tags in groups.items():
        lines += [f"### {gname}", "",
                  "| Etiqueta | Tag | VR | Descripción | % con valor | Valores distintos | Valor más común (% de series) | En test |",
                  "|---|---|---|---|---|---|---|---|"]
        for key, desc in tags.items():
            if key not in train.index and key not in test.index:
                continue
            tag = tag_for_keyword(key)
            tag_txt = f"({Tag(tag).group:04X},{Tag(tag).element:04X})" if tag else ""
            vr = dictionary_VR(tag) if tag else ""
            if key in train.index:
                r = train.loc[key]
                nd = "≥5000" if r.valores_distintos >= 5000 else f"{int(r.valores_distintos):,}"
                common = f"`{cell(r.valor_mas_comun)}` ({r.pct_valor_mas_comun:.1f})" if r.valores_distintos else "—"
                stats = f"{100 - r.pct_vacio:.1f} | {nd} | {common}"
            else:
                stats = "no existe en train | | "
            lines.append(f"| {key} | {tag_txt} | {vr} | {desc} | {stats} | {'sí' if key in test.index else 'no'} |")
        lines.append("")

    path = out_dir() / "diccionario_columnas.md"
    path.write_text("\n".join(lines))
    print(f"{path}: {len(train)} etiquetas en train, {len(test)} en test, sin descripción: {extra}")
    print("solo en train:", sorted(set(train.index) - set(test.index)))
    print("solo en test:", sorted(set(test.index) - set(train.index)))


if __name__ == "__main__":
    main()
