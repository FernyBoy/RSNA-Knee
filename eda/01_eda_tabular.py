#!/usr/bin/env python
"""EDA de los CSV: etiquetas, informes y metadatos de series. No toca los DICOM.

Uso:  python 01_eda_tabular.py [--split train]
Salidas en $KNEE_EDA_OUT/tabular: figuras PNG y resumen.json
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata

import numpy as np
import pandas as pd

from common import LABELS, PLANES, SEQUENTIAL, SERIES_COLORS, INK, hbar, load_series, load_studies, out_dir, setup_style

# Heurística por palabras vacías: basta para estimar la mezcla de idiomas sin dependencias.
STOPWORDS = {
    "es": "el la los las de del que en y con se por un una no sin es al como",
    "en": "the of and is are with no in there to without at seen on normal",
    "nl": "de het een van en met is geen niet in op bij ook er zijn aan",
    "de": "der die das und mit ist kein keine nicht im des ein eine von zu",
    "fr": "le la les des et du un une est pas avec dans au sans sur de",
    "pt": "o a os as do da dos das e com sem não em um uma na no ao",
    "it": "il lo la gli le di del della e con non in un una si al senza",
}
STOPWORDS = {k: set(v.split()) for k, v in STOPWORDS.items()}


SCRIPTS = {"GREEK": "el", "CYRILLIC": "cirílico", "CJK": "cjk", "HIRAGANA": "ja", "KATAKANA": "ja",
           "HANGUL": "ko", "ARABIC": "ar", "HEBREW": "he", "THAI": "th", "DEVANAGARI": "hi"}


def guess_language(text: str) -> str:
    text = str(text).lower()
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 20:
        return "indet."
    non_latin = [unicodedata.name(c, "").split()[0] for c in letters if ord(c) > 0x24F]
    if len(non_latin) > 0.3 * len(letters):
        script = max(set(non_latin), key=non_latin.count)
        return SCRIPTS.get(script, script.lower())
    words = re.findall(r"[^\W\d_]+", text)
    scores = sorted(((sum(w in sw for w in words), lang) for lang, sw in STOPWORDS.items()), reverse=True)
    (best, lang), (second, _) = scores[0], scores[1]
    return lang if best >= 3 and best > second else "indet."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", choices=["train", "test"])
    args = ap.parse_args()

    plt = setup_style()
    out = out_dir("tabular")
    studies, series = load_studies(args.split), load_series(args.split)
    summary: dict = {"split": args.split, "n_estudios": len(studies), "n_series": len(series)}

    print(f"== {args.split}: {len(studies):,} estudios, {len(series):,} series")
    print(f"UID de estudio duplicados: {studies.StudyInstanceUID.duplicated().sum()}, "
          f"de serie duplicados: {series.SeriesInstanceUID.duplicated().sum()}")
    only_csv = set(studies.StudyInstanceUID) ^ set(series.StudyInstanceUID)
    print(f"Estudios presentes en solo uno de los dos CSV: {len(only_csv)}")

    # ---------- Series ----------
    per_study = series.groupby("StudyInstanceUID").size()
    summary["series_por_estudio"] = per_study.describe().round(2).to_dict()
    print("\n-- Series por estudio\n", per_study.describe().round(2).to_string())

    combo = pd.crosstab(series.Anatomical_Plane, [series.Fluid_Sensitive, series.Fat_Suppression]).reindex(PLANES)
    print("\n-- Plano x (Fluid_Sensitive, Fat_Suppression)\n", combo.to_string())
    same = (series.Fluid_Sensitive == series.Fat_Suppression).mean()
    print(f"Fluid_Sensitive == Fat_Suppression en {same:.1%} de las series")
    summary["fluid_igual_a_fatsup"] = float(same)

    series["tipo"] = series.Anatomical_Plane + np.where(series.Fluid_Sensitive == 1, " FS", " no-FS")
    has = pd.crosstab(series.StudyInstanceUID, series.tipo).gt(0)
    coverage = has.mean().sort_values(ascending=False)
    print("\n-- % de estudios que tienen al menos una serie de cada tipo\n", (coverage * 100).round(1).to_string())
    summary["cobertura_tipo_serie"] = coverage.round(4).to_dict()
    all_planes = pd.crosstab(series.StudyInstanceUID, series.Anatomical_Plane).gt(0).all(axis=1).mean()
    print(f"Estudios con los tres planos: {all_planes:.1%}")

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    counts = per_study.value_counts().sort_index()
    axes[0].bar(counts.index.astype(str), counts.values, color=SERIES_COLORS[0], width=0.7)
    axes[0].set(title="Series por estudio", xlabel="número de series", ylabel="estudios")
    axes[0].grid(axis="x", visible=False)
    x = np.arange(len(PLANES))
    for i, (flag, name) in enumerate([(1, "Sensible a líquido (FS)"), (0, "No sensible a líquido")]):
        vals = [((series.Anatomical_Plane == p) & (series.Fluid_Sensitive == flag)).sum() for p in PLANES]
        bars = axes[1].bar(x + (i - 0.5) * 0.38, vals, width=0.36, color=SERIES_COLORS[i], label=name)
        axes[1].bar_label(bars, labels=[f"{v:,}" for v in vals], padding=2, fontsize=8, color=INK)
    axes[1].set_xticks(x, PLANES)
    axes[1].set(title="Series por plano y tipo de secuencia", ylabel="series")
    axes[1].grid(axis="x", visible=False)
    axes[1].legend(loc="upper right")
    fig.savefig(out / "series.png")
    plt.close(fig)

    if args.split != "train":
        (out / f"resumen_{args.split}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    # ---------- Etiquetas ----------
    lab = studies[LABELS]
    labeled = lab.notna().all(axis=1)
    partial = lab.notna().any(axis=1) & ~labeled
    print(f"\n-- Etiquetas: {labeled.sum():,} estudios etiquetados ({labeled.mean():.1%}), "
          f"{partial.sum()} parciales, {(~labeled & ~partial).sum():,} solo con informe")
    summary.update(n_etiquetados=int(labeled.sum()), n_parciales=int(partial.sum()))
    L = lab[labeled].astype(int)
    prev = L.mean().sort_values(ascending=False)
    print("\n-- Prevalencia entre etiquetados (n positivos / %)\n",
          pd.DataFrame({"positivos": L.sum()[prev.index], "%": (prev * 100).round(1)}).to_string())
    print("\n-- Hallazgos positivos por estudio\n", L.sum(axis=1).describe().round(2).to_string())
    summary["prevalencia"] = prev.round(4).to_dict()

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1, 1.25]})
    hbar(axes[0], prev.index, prev.values * 100, fmt="{:.0f}%")
    axes[0].set(title=f"Prevalencia por hallazgo (n = {len(L)} estudios etiquetados)", xlabel="% positivos")
    co = L.T @ L
    from matplotlib.colors import LinearSegmentedColormap
    im = axes[1].imshow(co.values, cmap=LinearSegmentedColormap.from_list("seq", SEQUENTIAL))
    axes[1].set_xticks(range(len(LABELS)), LABELS, rotation=45, ha="right")
    axes[1].set_yticks(range(len(LABELS)), LABELS)
    thr = co.values.max() * 0.55
    for i in range(len(LABELS)):
        for j in range(len(LABELS)):
            axes[1].text(j, i, co.values[i, j], ha="center", va="center", fontsize=7.5,
                         color="white" if co.values[i, j] > thr else INK)
    axes[1].grid(False)
    axes[1].set_title("Co-ocurrencia (estudios con ambos hallazgos; diagonal = positivos)")
    fig.colorbar(im, ax=axes[1], fraction=0.04, pad=0.02).outline.set_visible(False)
    fig.savefig(out / "etiquetas.png")
    plt.close(fig)

    # ---------- Informes ----------
    rep = studies.Report.fillna("")
    studies["n_chars"] = rep.str.len()
    studies["idioma"] = rep.map(guess_language)
    lang = studies.idioma.value_counts()
    print("\n-- Longitud del informe (caracteres)\n", studies.n_chars.describe().round(0).to_string())
    print("\n-- Idioma estimado del informe (heurística)\n", lang.to_string())
    print("\n-- Idioma entre etiquetados\n", studies.idioma[labeled].value_counts().to_string())
    print(f"Informes vacíos: {(studies.n_chars == 0).sum()}, duplicados exactos: {rep.duplicated().sum()}")
    summary["idiomas"] = lang.to_dict()
    summary["informe_chars"] = studies.n_chars.describe().round(1).to_dict()

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    axes[0].hist(studies.n_chars, bins=60, color=SERIES_COLORS[0], edgecolor="#fcfcfb", linewidth=0.5)
    axes[0].set(title="Longitud de los informes", xlabel="caracteres", ylabel="estudios")
    axes[0].grid(axis="x", visible=False)
    hbar(axes[1], lang.index, lang.values)
    axes[1].set(title="Idioma estimado del informe", xlabel="estudios")
    fig.savefig(out / "informes.png")
    plt.close(fig)

    studies[["StudyInstanceUID", "idioma", "n_chars"]].assign(etiquetado=labeled).to_csv(
        out / "estudios_idioma.csv", index=False)
    print("\n-- Un informe de ejemplo por idioma")
    for code, grp in studies.groupby("idioma"):
        print(f"[{code}] {grp.Report.iloc[0][:300]!r}")

    (out / "resumen_train.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSalidas en {out}")


if __name__ == "__main__":
    main()
