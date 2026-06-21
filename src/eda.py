"""
eda.py
======

Análise Exploratória de Dados (Exploratory Data Analysis, EDA) das
notificações de arboviroses do SINAN/DATASUS no período 2015–2026.

Gera tabelas descritivas e as figuras do Capítulo 8.1 do TCC.

Saídas
------
outputs/tabela_descritiva_regiao.csv
figures/fig04_distribuicao_dengue_semanas.png
figures/fig06_series_temporais_arboviroses.png

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("eda")


def carregar_dados() -> pd.DataFrame:
    """
    Carrega o dataset integrado. Se não existir, cai para o
    dataset sintético gerado pelo `generate_synthetic_data.py`.
    """
    real = cfg.processed_dir / f"dados_integrados_{cfg.ano_inicio}_{cfg.ano_fim}.parquet"
    synth = cfg.processed_dir / "dados_integrados_sinteticos.parquet"
    if real.exists():
        log.info(f"Usando dados reais: {real}")
        return pd.read_parquet(real)
    if synth.exists():
        log.warning("!" * 60)
        log.warning("ATENCAO: carregando DADOS SINTETICOS (demonstracao).")
        log.warning("Resultados gerados NAO devem ir para o TCC oficial.")
        log.warning(f"Arquivo: {synth}")
        log.warning("!" * 60)
        return pd.read_parquet(synth)
    raise FileNotFoundError(
        "Nenhum dataset integrado encontrado. Rode antes:\n"
        "  python src/generate_synthetic_data.py  (sintético)\n"
        "ou\n"
        "  python src/collect_sinan.py && python src/integrate.py  (real)"
    )


def tabela_por_regiao(df: pd.DataFrame) -> pd.DataFrame:
    """Casos totais e taxa de incidência média por região × doença."""
    tab = (
        df.pivot_table(
            index="regiao",
            columns="doenca",
            values="casos",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    log.info("Tabela descritiva por região:")
    log.info("\n" + tab.to_string(index=False))
    return tab


def figura_distribuicao_semanal(df: pd.DataFrame) -> Path:
    """
    Figura 4 — Distribuição de casos de DENGUE por SE,
    com uma curva por ano.
    """
    dengue = df[df["doenca"] == "dengue"]
    pivot = (
        dengue.groupby(["ano_epidem", "sem_epidem"])["casos"]
        .sum()
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(11, 6))
    anos = sorted(pivot["ano_epidem"].dropna().unique())
    cmap = plt.colormaps["viridis"].resampled(len(anos))
    for i, ano in enumerate(anos):
        sub = pivot[pivot["ano_epidem"] == ano]
        ax.plot(
            sub["sem_epidem"], sub["casos"],
            color=cmap(i), lw=1.5,
            label=str(int(ano)),
        )
    ax.set_xlabel("Semana Epidemiológica (SE)")
    ax.set_ylabel("Casos prováveis de dengue (Brasil)")
    

    ax.set_xlim(1, 52)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=4, fontsize=8, title="Ano")
    fig.tight_layout()

    dest = cfg.figures_dir / "fig04_distribuicao_dengue_semanas.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")
    return dest


def figura_series_arboviroses(df: pd.DataFrame) -> Path:
    """
    Figura 6 — Séries temporais nacionais das três arboviroses
    no período 2015–2026, em painéis empilhados.
    """
    arb = (
        df.groupby(["ano_epidem", "sem_epidem", "doenca"])["casos"]
        .sum()
        .reset_index()
    )
    arb["data"] = pd.to_datetime(
        arb["ano_epidem"].astype(str)
        + "-W"
        + arb["sem_epidem"].astype(str).str.zfill(2)
        + "-1",
        format="%G-W%V-%u",
        errors="coerce",
    )
    arb = arb.dropna(subset=["data"]).sort_values("data")

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    cores = {"dengue": "#C62828", "zika": "#1565C0", "chikungunya": "#2E7D32"}
    for ax, doenca in zip(axes, ["dengue", "zika", "chikungunya"]):
        sub = arb[arb["doenca"] == doenca]
        ax.fill_between(sub["data"], sub["casos"], color=cores[doenca], alpha=0.4)
        ax.plot(sub["data"], sub["casos"], color=cores[doenca], lw=1.0)
        ax.set_ylabel(f"{doenca.capitalize()}\n(casos/SE)")
        ax.grid(True, alpha=0.3)
    
    axes[-1].set_xlabel("Data")
    fig.tight_layout()

    dest = cfg.figures_dir / "fig06_series_temporais_arboviroses.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")
    return dest


def figura_pizza_distribuicao(df: pd.DataFrame) -> Path:
    """Distribuição percentual das 3 arboviroses no período."""
    total = df.groupby("doenca")["casos"].sum()
    fig, ax = plt.subplots(figsize=(7, 7))
    cores = ["#C62828", "#1565C0", "#2E7D32"]
    ax.pie(
        total.values,
        labels=[d.capitalize() for d in total.index],
        autopct="%1.1f%%",
        colors=cores,
        startangle=90,
        textprops={"fontsize": 11},
    )
    
    fig.tight_layout()

    dest = cfg.figures_dir / "fig04b_distribuicao_arboviroses_pizza.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")
    return dest


def main() -> None:
    df = carregar_dados()
    log.info(f"Dataset carregado: {len(df):,} linhas, {df['cod_ibge_7'].nunique():,} municípios.")

    tab = tabela_por_regiao(df)
    tab.to_csv(cfg.outputs_dir / "tabela_descritiva_regiao.csv", index=False)

    figura_distribuicao_semanal(df)
    figura_series_arboviroses(df)
    figura_pizza_distribuicao(df)


if __name__ == "__main__":
    main()
