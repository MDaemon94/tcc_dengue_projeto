"""
stl_analysis.py
===============

Decomposição STL (Seasonal-Trend decomposition using Loess) das
séries semanais de dengue, Zika e chikungunya e cálculo da força
sazonal (Fs) de cada arbovirose.

Referência metodológica:
  Cleveland, R. B. et al. (1990) — STL: a seasonal-trend
  decomposition procedure based on loess.

Saídas
------
figures/fig05_decomposicao_stl_dengue.png
outputs/forca_sazonal.csv

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from config import cfg
from eda import carregar_dados


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("stl")


def construir_serie_nacional(df: pd.DataFrame, doenca: str) -> pd.Series:
    """Soma os casos por (ano, SE) e retorna série temporal indexada por data."""
    sub = (
        df[df["doenca"] == doenca]
        .groupby(["ano_epidem", "sem_epidem"])["casos"]
        .sum()
        .reset_index()
    )
    sub["data"] = pd.to_datetime(
        sub["ano_epidem"].astype(str)
        + "-W"
        + sub["sem_epidem"].astype(str).str.zfill(2)
        + "-1",
        format="%G-W%V-%u",
        errors="coerce",
    )
    sub = sub.dropna(subset=["data"]).sort_values("data")
    s = pd.Series(sub["casos"].values, index=sub["data"], name=doenca)
    s = s.asfreq("W-MON").fillna(0)
    return s


def forca_sazonal(seasonal: np.ndarray, resid: np.ndarray) -> float:
    """
    Fs = max(0, 1 − Var(R) / Var(S + R))
    (Hyndman & Athanasopoulos, 2018)
    """
    var_r = np.var(resid)
    var_sr = np.var(seasonal + resid)
    if var_sr <= 0:
        return 0.0
    return max(0.0, 1.0 - var_r / var_sr)


def plotar_decomposicao(stl_result, doenca: str) -> None:
    """Plota a decomposição STL e salva PNG."""
    fig = stl_result.plot()
    fig.set_size_inches(11, 8)
    
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    dest = cfg.figures_dir / f"fig05_decomposicao_stl_{doenca}.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def main() -> None:
    df = carregar_dados()

    resultados = []
    for doenca in ["dengue", "zika", "chikungunya"]:
        serie = construir_serie_nacional(df, doenca)
        if serie.sum() == 0 or len(serie) < 104:
            log.warning(f"Série insuficiente para {doenca}. Pulando.")
            continue

        stl = STL(serie, period=52, robust=True)
        res = stl.fit()
        fs = forca_sazonal(res.seasonal.values, res.resid.values)
        resultados.append({"doenca": doenca, "forca_sazonal": fs, "n_semanas": len(serie)})
        log.info(f"{doenca:>12s}  Fs = {fs:.3f}  (n={len(serie)} semanas)")

        if doenca == "dengue":
            plotar_decomposicao(res, doenca)

    pd.DataFrame(resultados).to_csv(
        cfg.outputs_dir / "forca_sazonal.csv", index=False
    )
    log.info("Resultados de força sazonal salvos em outputs/forca_sazonal.csv.")


if __name__ == "__main__":
    main()
