"""
build_clima_municipal.py
========================
Agrega os dados diários do INMET (por estação) em uma tabela de clima
por MUNICÍPIO e SEMANA EPIDEMIOLÓGICA, gerando o arquivo que o
integrate.py espera:  data/processed/clima_municipal.parquet

Etapas
------
1. Lê os parquets diários particionados em data/raw/inmet/diario/ano=/uf=/
   (colunas: data, precip_mm, temp_c, umidade_pct, latitude, longitude, ...).
2. Calcula a semana epidemiológica ISO 8601 de cada dia.
3. Agrega por estação × ano_epidem × sem_epidem:
       precipitacao = soma semanal de chuva
       temp_media   = média semanal de temperatura
       umidade      = média semanal de umidade
4. Atribui cada município ao da ESTAÇÃO MAIS PRÓXIMA (vizinho mais próximo
   sobre os centroides reais do shapefile IBGE), via geo_utils.
5. Salva clima_municipal.parquet com:
       cod_ibge_7, ano_epidem, sem_epidem, precipitacao, temp_media, umidade

Observação metodológica
------------------------
A atribuição por estação mais próxima é uma simplificação da interpolação
IDW descrita na metodologia do TCC; é suficiente para o caráter ecológico
do estudo (clima como covariável regional) e evita dependência de bibliotecas
de interpolação. Caso deseje IDW, substitua a função `atribuir_municipios`.

Como rodar
----------
    python src/build_clima_municipal.py
    # depois: python src/integrate.py  (agora com clima)

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import cfg

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("clima")


def carregar_inmet_diario() -> pd.DataFrame:
    """Lê todos os parquets diários do INMET particionados por ano/uf."""
    base = cfg.raw_dir / "inmet" / "diario"
    if not base.exists():
        raise FileNotFoundError(
            f"INMET diário não encontrado em {base}. "
            "Rode collect_inmet.py antes."
        )
    partes = sorted(base.rglob("*.parquet"))
    if not partes:
        raise FileNotFoundError(f"Nenhum parquet em {base}.")
    log.info(f"Lendo {len(partes)} arquivos diários do INMET…")
    cols = ["data", "precip_mm", "temp_c", "umidade_pct", "latitude", "longitude"]
    frames = []
    for p in partes:
        try:
            frames.append(pd.read_parquet(p, columns=cols))
        except Exception as e:  # noqa: BLE001
            log.warning(f"Falha ao ler {p}: {e}")
    df = pd.concat(frames, ignore_index=True)
    log.info(f"INMET diário: {len(df):,} linhas-estação-dia.")
    return df


def agregar_estacao_semana(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega para estação (lat/lon) × ano_epidem × sem_epidem (ISO)."""
    df = df.copy()
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data", "latitude", "longitude"])
    iso = df["data"].dt.isocalendar()
    df["ano_epidem"] = iso["year"].astype(int)
    df["sem_epidem"] = iso["week"].astype(int)

    g = (
        df.groupby(["latitude", "longitude", "ano_epidem", "sem_epidem"], as_index=False)
        .agg(
            precipitacao=("precip_mm", "sum"),
            temp_media=("temp_c", "mean"),
            umidade=("umidade_pct", "mean"),
        )
    )
    log.info(f"Agregado estação×semana: {len(g):,} linhas.")
    return g


def atribuir_municipios(clima_estacao: pd.DataFrame) -> pd.DataFrame:
    """
    Liga cada município ao clima da estação mais próxima (vizinho 1-NN
    sobre os centroides reais do IBGE).
    """
    from geo_utils import carregar_centroides
    from sklearn.neighbors import NearestNeighbors

    cent = carregar_centroides()
    if cent.empty:
        raise RuntimeError(
            "Centroides reais indisponíveis (instale geopandas e confirme o "
            "shapefile em data/geo/). Sem eles não há atribuição município↔estação."
        )

    # Estações únicas (lat/lon)
    estacoes = (
        clima_estacao[["latitude", "longitude"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    estacoes["estacao_id"] = estacoes.index

    nn = NearestNeighbors(n_neighbors=1).fit(
        estacoes[["latitude", "longitude"]].values
    )
    dist, idx = nn.kneighbors(cent[["lat", "lon"]].values)
    cent = cent.copy()
    cent["estacao_id"] = estacoes.iloc[idx.ravel()]["estacao_id"].values

    # mapa município -> (lat,lon) da estação atribuída
    mun_estacao = cent.merge(estacoes, on="estacao_id", how="left")[
        ["cod_ibge_7", "latitude", "longitude"]
    ]

    # junta clima da estação para cada município-semana
    out = mun_estacao.merge(
        clima_estacao, on=["latitude", "longitude"], how="left"
    )
    out = out[["cod_ibge_7", "ano_epidem", "sem_epidem",
               "precipitacao", "temp_media", "umidade"]]
    log.info(f"Clima por município×semana: {len(out):,} linhas, "
             f"{out['cod_ibge_7'].nunique():,} municípios.")
    return out


def main() -> None:
    bruto = carregar_inmet_diario()
    clima_estacao = agregar_estacao_semana(bruto)
    clima_mun = atribuir_municipios(clima_estacao)

    dest = cfg.processed_dir / "clima_municipal.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    clima_mun.to_parquet(dest, index=False)
    log.info(f"Salvo: {dest}  ({len(clima_mun):,} linhas).")
    log.info("Agora rode: python src/integrate.py")


if __name__ == "__main__":
    main()