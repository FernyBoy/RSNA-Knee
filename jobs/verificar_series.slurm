#!/bin/bash
#SBATCH -A p082
#SBATCH -J rsna-verificar-series
#SBATCH -p cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:20:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# Verifica geometría y consistencia interna de cada serie a partir del parquet de cabeceras.
# No abre DICOM: solo lee el parquet que dejó jobs/cabeceras.slurm.
# Lanzar desde code/:  sbatch jobs/verificar_series.slurm [JOBID_DEL_BARRIDO] [train|test]
set -euo pipefail

BARRIDO=${1:-2078579}
SPLIT=${2:-train}

# --- Rutas -------------------------------------------------------------------
PROJ=/lustre/proyectos/p082
export KNEE_DATA="$PROJ/kaggle_data/competitions/rsna-knee-abnormality-detection"   # SOLO LECTURA
PARQUET="$PROJ/runs/$BARRIDO/cabeceras_${SPLIT}_todos.parquet"                    # entrada, no se modifica
OUT="$PROJ/runs/${SLURM_JOB_ID:?}"                                                 # directorio nuevo por job
mkdir -p "$OUT"
cd "$PROJ/code"

echo "job=$SLURM_JOB_ID nodo=$(hostname) inicio=$(date -Is) entrada=$PARQUET"
echo "commit=$(git rev-parse --short HEAD)" | tee "$OUT/commit.txt"
[[ -r "$PARQUET" ]] || { echo "No existe el parquet de entrada: $PARQUET" >&2; exit 1; }

# --- Entorno -----------------------------------------------------------------
PY=/apps/miniconda3/bin/python

# --- Trabajo -----------------------------------------------------------------
"$PY" eda/08_verificar_series.py "$PARQUET" --out "$OUT" --split "$SPLIT"

echo "fin=$(date -Is)"
