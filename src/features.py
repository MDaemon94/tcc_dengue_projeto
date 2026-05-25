"""
features.py
===========

Engenharia de variáveis (features) para os modelos preditivos
de DENGUE em horizonte de 4 semanas.

Variáveis geradas
-----------------
- lag_1 … lag_8        : casos nas 1–8 semanas anteriores
- precip_lag1 … lag4   : precipitação acumulada, defasada
- temp_lag1 … lag4     : temperatura média, defasada
- sem_sen / sem_cos    : codificação cíclica da SE
- idhm, dens_demo      : variáveis socioeconômicas
- cobertura_vacinal    : variável NOVA (a partir de 2024)
- casos_t4             : alvo — casos em t+4 semanas

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("features")


def criar_features(
    df: pd.DataFrame,
    doenca: str = "dengue",
    horizonte: int = None,
    n_lags_casos: int = None,
    n_lags_clima: int = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Constrói a matriz de features para o modelo preditivo.

    Returns
    -------
    (df, feature_cols)
        - df: DataFrame com features e variável-alvo `casos_t4`.
        - feature_cols: lista de nomes das colunas de feature.
    """
    horizonte    = horizonte    or cfg.horizonte_previsao
    n_lags_casos = n_lags_casos or cfg.n_lags_casos
    n_lags_clima = n_lags_clima or cfg.n_lags_clima

    d = df[df["doenca"] == doenca].copy()
    d = d.sort_values(["cod_ibge_7", "ano_epidem", "sem_epidem"])

    # Lags de casos
    for lag in range(1, n_lags_casos + 1):
        d[f"lag_{lag}"] = d.groupby("cod_ibge_7")["casos"].shift(lag)

    # Lags de variáveis climáticas
    for var in ["precipitacao", "temp_media", "umidade"]:
        if var in d.columns:
            for lag in range(1, n_lags_clima + 1):
                col = f"{var}_lag{lag}" if var == "umidade" else \
                      ({"precipitacao": "precip", "temp_media": "temp"}[var] + f"_lag{lag}")
                d[col] = d.groupby("cod_ibge_7")[var].shift(lag)

    # Codificação cíclica da SE
    d["sem_sen"] = np.sin(2 * np.pi * d["sem_epidem"].astype(float) / 52)
    d["sem_cos"] = np.cos(2 * np.pi * d["sem_epidem"].astype(float) / 52)

    # Alvo
    d["casos_t4"] = d.groupby("cod_ibge_7")["casos"].shift(-horizonte)

    feature_cols = (
        [f"lag_{i}" for i in range(1, n_lags_casos + 1)]
        + [f"precip_lag{i}" for i in range(1, n_lags_clima + 1)]
        + [f"temp_lag{i}"   for i in range(1, n_lags_clima + 1)]
        + ["sem_sen", "sem_cos", "idhm", "dens_demo"]
    )
    # Saneamento (Atlas Brasil / Censo 2010) - usar score consolidado se disponivel,
    # senao os indicadores individuais
    if "score_saneamento" in d.columns:
        feature_cols.append("score_saneamento")
    else:
        for col in ("pct_agua_encanada", "pct_banheiro_agua", "pct_coleta_lixo"):
            if col in d.columns:
                feature_cols.append(col)

    # Vacinacao dengue (binaria, valida apenas para 2024+)
    if "vacinou_dengue" in d.columns:
        feature_cols.append("vacinou_dengue")

    feat = [c for c in feature_cols if c in d.columns]
    d = d.dropna(subset=feat + ["casos_t4"]).reset_index(drop=True)

    log.info(f"Features finais ({len(feat)}): {feat}")
    log.info(f"Observacoes uteis: {len(d):,}")

    return d, feat


def main() -> None:
    from eda import carregar_dados
    df = carregar_dados()
    feats_df, cols = criar_features(df, doenca=cfg.doenca_principal)
    dest = cfg.processed_dir / "features_modelo_dengue.parquet"
    feats_df.to_parquet(dest, index=False)
    log.info(f"Features salvas: {dest}")


if __name__ == "__main__":
    main()
