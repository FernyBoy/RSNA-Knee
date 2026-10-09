#!/bin/bash
#SBATCH -A p082
#SBATCH -J rsna-NOMBRE
#SBATCH -p PARTICION                 # confirmar con: ssh yuca 'sinfo -s'
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
##SBATCH --gres=gpu:1                # descomentar solo si usa GPU (MI210)

set -euo pipefail

# --- Rutas -------------------------------------------------------------------
PROJ=/lustre/proyectos/p082
DATA="$PROJ/kaggle_data/competitions/rsna-knee-abnormality-detection"   # SOLO LECTURA
OUT="$PROJ/runs/${SLURM_JOB_ID:?}"                                     # directorio nuevo por job
mkdir -p "$OUT"
cd "$PROJ/code"

echo "job=$SLURM_JOB_ID nodo=$(hostname) inicio=$(date -Is)"
echo "commit=$(git rev-parse --short HEAD)" | tee "$OUT/commit.txt"

# --- Entorno -----------------------------------------------------------------
# module load rocm           # ajustar a los módulos reales
# source "$PROJ/venvs/rsna/bin/activate"

# --- (Opcional) datos a disco local del nodo -----------------------------------
# SCR="/scratch/$USER/${SLURM_JOB_ID:?}"; mkdir -p "$SCR"
# trap 'rsync -a "$SCR/out/" "$OUT/"' EXIT   # resultados de vuelta a Lustre (/scratch se purga solo)

# --- Trabajo -----------------------------------------------------------------
python src/COMANDO.py --data "$DATA" --out "$OUT"

echo "fin=$(date -Is)"
