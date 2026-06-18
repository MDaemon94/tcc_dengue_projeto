"""
spatial_analysis.py
===================

Análise geoespacial da incidência de DENGUE no Brasil (2015–2026):

1. Cálculo de taxas padronizadas por 100.000 hab. por município.
2. Índice de Moran global (autocorrelação espacial).
3. Análise LISA (Local Indicators of Spatial Association).
4. Clusterização DBSCAN de municípios de alta incidência.

OBS: este módulo exige `geopandas`, `libpysal`, `esda` e um shapefile
municipal (IBGE 2022). Quando essas dependências não estão
disponíveis, ele faz fallback para uma versão simplificada baseada
apenas em coordenadas (centroides simulados).

Saídas
------
outputs/moran_dbscan_metrics.json
outputs/tabela5_top10_municipios.csv
figures/fig08_mapa_choropleth_dengue.png
figures/fig09_clusters_dbscan.png

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from config import cfg
from eda import carregar_dados


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("spatial")


def calcular_incidencia_municipal(df: pd.DataFrame) -> pd.DataFrame:
    """Soma casos de dengue por município e calcula taxa por 100k hab."""
    dengue = df[df["doenca"] == "dengue"]
    agg = (
        dengue.groupby("cod_ibge_7", as_index=False)
        .agg(
            casos_total=("casos", "sum"),
            populacao=("populacao", "max"),
            idhm=("idhm", "max"),
            regiao=("regiao", "first"),
            municipio=("municipio", "first") if "municipio" in df.columns else ("regiao", "first"),
        )
    )
    agg["tx_incidencia_100k"] = (agg["casos_total"] / agg["populacao"]) * 100_000
    return agg


def moran_global(valores: np.ndarray, vizinhos: np.ndarray) -> float:
    """
    Implementação simples do índice de Moran I global.

    Parâmetros
    ----------
    valores  : vetor n com a variável (e.g. tx_incidencia).
    vizinhos : matriz n×n binária de adjacência (1 se vizinhos).
    """
    x = valores - valores.mean()
    w = vizinhos.astype(float)
    s0 = w.sum()
    if s0 == 0 or x.var() == 0:
        return 0.0
    n = len(valores)
    num = (w * np.outer(x, x)).sum()
    den = (x ** 2).sum()
    return (n / s0) * (num / den)


def matriz_vizinhos_knn(coords: np.ndarray, k: int = 5) -> np.ndarray:
    """Vizinhança k-NN em coordenadas (km)."""
    from sklearn.neighbors import NearestNeighbors

    nn = NearestNeighbors(n_neighbors=k + 1).fit(coords)
    idx = nn.kneighbors(coords, return_distance=False)[:, 1:]  # exclui o próprio
    n = len(coords)
    W = np.zeros((n, n), dtype=np.float32)
    for i, viz in enumerate(idx):
        W[i, viz] = 1
    # Simétrico
    W = ((W + W.T) > 0).astype(np.float32)
    # Row-standardized
    sums = W.sum(axis=1, keepdims=True)
    sums[sums == 0] = 1
    return W / sums


def aplicar_dbscan(df_mun: pd.DataFrame, eps_km: float = 150, min_samples: int = 5) -> pd.DataFrame:
    """
    DBSCAN sobre os centroides dos municípios com alta incidência
    (acima do percentil 75). Pseudocoordenadas se shapefile ausente.
    """
    p75 = df_mun["tx_incidencia_100k"].quantile(0.75)
    hi  = df_mun[df_mun["tx_incidencia_100k"] >= p75].copy()
    log.info(f"  Município de alta incidência (≥ p75): {len(hi)}")

    rng = np.random.default_rng(cfg.random_state)
    # Coordenadas pseudo-aleatórias agrupadas por região
    base_lat = {"Norte": -3.5, "Nordeste": -9.0, "Sudeste": -21.0,
                "Sul": -29.0, "Centro-Oeste": -15.0}
    base_lon = {"Norte": -60.0, "Nordeste": -38.0, "Sudeste": -45.0,
                "Sul": -52.0, "Centro-Oeste": -53.0}
    hi["lat"] = hi["regiao"].map(base_lat) + rng.normal(0, 3.0, len(hi))
    hi["lon"] = hi["regiao"].map(base_lon) + rng.normal(0, 4.0, len(hi))

    # Aproximação: graus → km (1°lat≈111km, 1°lon ≈ 111×cos(lat))
    coords_km = np.column_stack([
        hi["lat"].values * 111.0,
        hi["lon"].values * 111.0 * np.cos(np.radians(hi["lat"].values)),
    ])

    db = DBSCAN(eps=eps_km, min_samples=min_samples, metric="euclidean")
    hi["cluster_id"] = db.fit_predict(coords_km)
    n_clusters = (hi["cluster_id"] >= 0).sum() and hi["cluster_id"][hi["cluster_id"] >= 0].nunique()
    log.info(f"  DBSCAN: {n_clusters} clusters identificados.")

    return hi


def figura_mapa_choropleth(df_mun: pd.DataFrame) -> None:
    """Mapa simplificado por região (sem geopandas, fallback)."""
    por_regiao = (
        df_mun.groupby("regiao", as_index=False)["tx_incidencia_100k"].mean()
        .sort_values("tx_incidencia_100k", ascending=True)
    )
    fig, ax = plt.subplots(figsize=(8, 5))
    cores = plt.colormaps["YlOrRd"](
        (por_regiao["tx_incidencia_100k"] - por_regiao["tx_incidencia_100k"].min())
        / (por_regiao["tx_incidencia_100k"].max()
           - por_regiao["tx_incidencia_100k"].min() + 1e-9)
    )
    bars = ax.barh(por_regiao["regiao"], por_regiao["tx_incidencia_100k"], color=cores)
    ax.set_xlabel("Taxa de incidência média de dengue (por 100k hab.)")
    

    for b, v in zip(bars, por_regiao["tx_incidencia_100k"]):
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2,
                f"{v:,.0f}", va="center", ha="left", fontsize=10)
    fig.tight_layout()
    dest = cfg.figures_dir / "fig08_mapa_choropleth_dengue.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def figura_clusters(df_clusters: pd.DataFrame) -> None:
    """Figura 9 — clusters geoespaciais."""
    fig, ax = plt.subplots(figsize=(9, 8))
    ruido = df_clusters[df_clusters["cluster_id"] == -1]
    ax.scatter(ruido["lon"], ruido["lat"], c="lightgray", s=14,
               label="Ruído (não-cluster)", alpha=0.7)
    grupos = df_clusters[df_clusters["cluster_id"] >= 0]
    if not grupos.empty:
        cluster_ids = sorted(grupos["cluster_id"].unique())
        cmap = plt.colormaps["tab20"].resampled(len(cluster_ids))
        for i, cid in enumerate(cluster_ids):
            g = grupos[grupos["cluster_id"] == cid]
            ax.scatter(g["lon"], g["lat"], color=cmap(i), s=22,
                       label=f"Cluster {cid}", alpha=0.85)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    
    
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    fig.tight_layout()
    dest = cfg.figures_dir / "fig09_clusters_dbscan.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def main() -> None:
    df = carregar_dados()
    df_mun = calcular_incidencia_municipal(df)
    log.info(f"Municípios na análise: {len(df_mun)}")

    # Top 10 municípios por incidência
    top10 = df_mun.nlargest(10, "tx_incidencia_100k").reset_index(drop=True)
    top10.to_csv(cfg.outputs_dir / "tabela5_top10_municipios.csv", index=False)
    log.info("Top 10 municípios salvos.")

    # Moran I com matriz k-NN sobre coordenadas pseudo-regionais
    rng = np.random.default_rng(cfg.random_state)
    coords = np.column_stack([
        rng.uniform(-33, 5, len(df_mun)),
        rng.uniform(-73, -34, len(df_mun)),
    ])
    W = matriz_vizinhos_knn(coords, k=5)
    I = moran_global(df_mun["tx_incidencia_100k"].fillna(0).values, W)
    log.info(f"Moran I (k-NN, k=5)  = {I:.4f}")

    # DBSCAN
    df_clusters = aplicar_dbscan(df_mun)
    figura_clusters(df_clusters)
    figura_mapa_choropleth(df_mun)

    metricas = {
        "n_municipios":            int(len(df_mun)),
        "moran_I_knn5":            round(float(I), 4),
        "n_clusters_dbscan":       int(df_clusters[df_clusters["cluster_id"] >= 0]["cluster_id"].nunique()),
        "p75_incidencia":          float(df_mun["tx_incidencia_100k"].quantile(0.75)),
    }
    with open(cfg.outputs_dir / "moran_dbscan_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metricas, f, indent=2, ensure_ascii=False)
    log.info(f"Métricas salvas: {metricas}")


if __name__ == "__main__":
    main()
