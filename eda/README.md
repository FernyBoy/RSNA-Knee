# Exploración del dataset RSNA Knee Abnormality Detection

Datos: `/lustre/proyectos/p082/kaggle_data/competitions/rsna-knee-abnormality-detection`
(se puede cambiar con la variable `KNEE_DATA`). Las salidas van a `code/data/eda/`
(ignorado por git; se cambia con `KNEE_EDA_OUT`). Ejecutar desde `code/eda/`.

| Script | Qué hace | Coste |
|---|---|---|
| `01_eda_tabular.py` | Etiquetas, informes (longitud, idioma estimado) y metadatos de series a partir de los CSV | segundos |
| `02_inventario_disco.py` | Cruza los CSV con el disco y cuenta cortes por serie (no abre DICOM) | ~1 min |
| `03_extraer_cabeceras.py` | Vuelca las cabeceras DICOM a parquet; `--pixel-stats` añade estadísticas de intensidad | 1 corte/serie: ~1 min; todos: usar SLURM |
| `04_resumen_cabeceras.py` | Resume un parquet de cabeceras: equipos, geometría, pacientes, intensidades | segundos |
| `05_ver_estudio.py` | Mosaico PNG de un estudio (una fila por serie) junto con su informe y etiquetas | segundos por estudio |
| `../jobs/cabeceras.slurm` | Barrido completo de cabeceras (~820 mil archivos) + resumen; escribe en `/lustre/proyectos/p082/runs/<jobid>/` | desde `code/`: `sbatch jobs/cabeceras.slurm [train\|test]` |

```bash
python 01_eda_tabular.py
python 02_inventario_disco.py
python 03_extraer_cabeceras.py --pixel-stats
python 04_resumen_cabeceras.py ../data/eda/dicom/cabeceras_train_1xserie_px.parquet
python 05_ver_estudio.py --random 3 --labeled
```

En el nodo de login solo caben pruebas pequeñas (`--sample-studies`). El barrido completo va por SLURM,
siguiendo el protocolo de la skill `yuca-hpc-ops` (linter, commit, `--test-only`, envío).

Requiere `pandas`, `pyarrow`, `pydicom`, `matplotlib` y `tqdm` (ya están en `/apps/miniconda3`).
