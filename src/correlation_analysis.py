"""
correlation_analysis.py
=======================

Quantifica a correlação entre variáveis climáticas
(precipitação, temperatura, umidade) e socioeconômicas
(IDHM, saneamento, densidade demográfica) e a incidência
semanal de DENGUE por grande região geográfica, com
defasagens biologicamente plausíveis (lags 1–4 semanas).

Resultado: Tabela 4 do TCC + Figura 7.

Foco: a análise correlacional rigorosa é feita para DENGUE.
Para Zika e chikungunya os mesmos cálculos podem ser
executados, mas o TCC os trata apenas como análise exploratória,
dado o menor volume de casos e a maior subnotificação.

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from config import cfg
from eda import carregar_dados


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("corr")


VARIAVEIS_CLIMATICAS = ["precipitacao", "temp_media", "umidade"]
LAGS = [1, 2, 3, 4]


def preparar_painel_regional(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa por região × ano_epidem × sem_epidem, somando casos e
    fazendo médias ponderadas (pela população) das variáveis
    climáticas e socioeconômicas disponíveis.
    """
    if "regiao" not in df.columns:
        raise KeyError("Coluna 'regiao' ausente — execute o pipeline completo.")

    dengue = df[df["doenca"] == "dengue"].copy()

    aggs = {"casos": "sum"}
    for c in VARIAVEIS_CLIMATICAS:
        if c in dengue.columns:
            aggs[c] = "mean"
    for c in ["idhm", "cobertura_sanea", "dens_demo"]:
        if c in dengue.columns:
            aggs[c] = "mean"

    painel = (
        dengue.groupby(["regiao", "ano_epidem", "sem_epidem"], dropna=False)
        .agg(aggs)
        .reset_index()
        .sort_values(["regiao", "ano_epidem", "sem_epidem"])
    )
    return painel


def correlacao_com_lag(
    serie_x: pd.Series, serie_y: pd.Series, lag: int
) -> tuple[float, float]:
    """Pearson entre y[t] e x[t-lag]; descarta NaN."""
    if lag > 0:
        x_lag = serie_x.shift(lag)
    else:
        x_lag = serie_x
    mask = (~x_lag.isna()) & (~serie_y.isna())
    if mask.sum() < 30:
        return (np.nan, np.nan)
    r, p = pearsonr(x_lag[mask], serie_y[mask])
    return float(r), float(p)


def melhor_lag(serie_x: pd.Series, serie_y: pd.Series) -> tuple[int, float, float]:
    """Retorna (melhor_lag, r, p) entre os lags testados."""
    melhor = (0, 0.0, 1.0)
    for lag in LAGS:
        r, p = correlacao_com_lag(serie_x, serie_y, lag)
        if not np.isnan(r) and abs(r) > abs(melhor[1]):
            melhor = (lag, r, p)
    return melhor


def tabela_correlacao(painel: pd.DataFrame) -> pd.DataFrame:
    """Tabela 4: melhores correlações por região."""
    resultados: list[dict] = []
    for regiao, sub in painel.groupby("regiao"):
        sub = sub.sort_values(["ano_epidem", "sem_epidem"])
        for var in VARIAVEIS_CLIMATICAS:
            if var not in sub.columns:
                continue
            lag, r, p = melhor_lag(sub[var], sub["casos"])
            resultados.append({
                "regiao":   regiao,
                "variavel": var,
                "melhor_lag": lag,
                "r":        round(r, 3),
                "p":        round(p, 4),
            })
        for var in ["idhm", "cobertura_sanea", "dens_demo"]:
            if var not in sub.columns:
                continue
            r, p = correlacao_com_lag(sub[var], sub["casos"], lag=0)
            resultados.append({
                "regiao":   regiao,
                "variavel": var,
                "melhor_lag": 0,
                "r":        round(r, 3),
                "p":        round(p, 4),
            })
    return pd.DataFrame(resultados)


def figura_correlacao(tabela: pd.DataFrame) -> None:
    """Figura 7 — heatmap de correlação variável × região."""
    pivot = tabela.pivot(index="variavel", columns="regiao", values="r")
    pivot = pivot.reindex(VARIAVEIS_CLIMATICAS + ["idhm", "cobertura_sanea", "dens_demo"])

    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(pivot.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns, rotation=30, ha="right")
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.iloc[i, j]
            if not pd.isna(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        color="white" if abs(v) > 0.5 else "black",
                        fontsize=10)
    ax.set_title(
        "Figura 7 – Correlação entre variáveis externas e incidência de dengue\n"
        f"por grande região ({cfg.ano_inicio}–{cfg.ano_fim})"
    )
    plt.colorbar(im, ax=ax, label="r de Pearson")
    fig.tight_layout()
    dest = cfg.figures_dir / "fig07_correlacao_clima_dengue.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def main() -> None:
    df = carregar_dados()
    painel = preparar_painel_regional(df)
    tabela = tabela_correlacao(painel)
    log.info("Tabela 4 (correlações):\n" + tabela.to_string(index=False))

    tabela.to_csv(cfg.outputs_dir / "tabela4_correlacoes.csv", index=False)
    figura_correlacao(tabela)


if __name__ == "__main__":
    main()
