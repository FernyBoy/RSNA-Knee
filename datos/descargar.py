"""Descarga los datos de la competencia RSNA Knee Abnormality Detection.

Requiere credenciales de Kaggle (~/.kaggle/kaggle.json o las variables
KAGGLE_USERNAME y KAGGLE_KEY) y haber aceptado las reglas de la competencia.

Uso:
    uv run python datos/descargar.py
"""

import kagglehub


def main() -> None:
    # Descarga la versión más reciente
    path = kagglehub.competition_download("rsna-knee-abnormality-detection")
    print("Path to competition files:", path)


if __name__ == "__main__":
    main()
