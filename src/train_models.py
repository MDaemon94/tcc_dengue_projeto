"""
train_models.py
===============

Treinamento e avaliação comparativa de modelos preditivos de
DENGUE no horizonte de 4 semanas, com validação cruzada
temporal (TimeSeriesSplit, 5 dobras).

Modelos
-------
- LinearRegression  (baseline)
- RandomForestRegressor
- XGBRegressor
- (Opcional) Prophet — script separado por divergência de API

Saídas
------
outputs/tabela6_metricas_modelos.csv
outputs/importancia_features_rf.csv
figures/fig10_importancia_rf.png
figures/fig11_previsto_vs_real.png
figures/fig12_curvas_aprendizado.png
models/<modelo>.joblib

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import TimeSeriesSplit

from config import cfg
from features import criar_features
from eda import carregar_dados


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("train")


def construir_modelos() -> dict:
    """Define o dicionário de modelos a comparar."""
    modelos = {
        "LinearRegression": LinearRegression(),
        "RandomForest":     RandomForestRegressor(
                                n_estimators=150, max_depth=10,
                                min_samples_leaf=5, n_jobs=-1,
                                random_state=cfg.random_state),
    }
    try:
        from xgboost import XGBRegressor
        modelos["XGBoost"] = XGBRegressor(
            n_estimators=200, max_depth=6, learning_rate=0.07,
            subsample=0.8, colsample_bytree=0.8, n_jobs=-1,
            random_state=cfg.random_state, verbosity=0,
        )
    except ImportError:
        log.warning("xgboost não instalado — pulando modelo XGBoost.")
    return modelos


def validar_cruzado(
    X: np.ndarray, y: np.ndarray, modelo, n_splits: int = 5
) -> dict:
    """Validação cruzada temporal — devolve média ± desvio."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    rmse_list, mae_list, r2_list = [], [], []
    for tr, te in tscv.split(X):
        modelo.fit(X[tr], y[tr])
        pred = modelo.predict(X[te])
        rmse_list.append(np.sqrt(mean_squared_error(y[te], pred)))
        mae_list.append(mean_absolute_error(y[te], pred))
        r2_list.append(r2_score(y[te], pred))
    return {
        "RMSE_mean": np.mean(rmse_list), "RMSE_std": np.std(rmse_list),
        "MAE_mean":  np.mean(mae_list),  "MAE_std":  np.std(mae_list),
        "R2_mean":   np.mean(r2_list),   "R2_std":   np.std(r2_list),
    }


def figura_importancia(modelo, features: list[str]) -> None:
    """Figura 10 — importância de variáveis no Random Forest."""
    imp = pd.DataFrame({
        "feature":   features,
        "importance": modelo.feature_importances_,
    }).sort_values("importance", ascending=True).tail(20)

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(imp["feature"], imp["importance"], color="#1976D2")
    ax.set_xlabel("Importância (Gini, normalizada)")
    

    fig.tight_layout()
    dest = cfg.figures_dir / "fig10_importancia_rf.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    imp.sort_values("importance", ascending=False).to_csv(
        cfg.outputs_dir / "importancia_features_rf.csv", index=False
    )
    log.info(f"Figura salva: {dest}")


def figura_previsto_vs_real(
    y_true: np.ndarray, y_pred: np.ndarray, modelo_nome: str
) -> None:
    """Figura 11 — dispersão previsto vs. real."""
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(y_true, y_pred, alpha=0.3, s=18, color="#1976D2")
    lim = max(y_true.max(), y_pred.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1, alpha=0.7, label="y = x")
    ax.set_xlabel("Casos observados (t+4)")
    ax.set_ylabel("Casos previstos")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    

    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    dest = cfg.figures_dir / "fig11_previsto_vs_real.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def figura_curvas_aprendizado(X: np.ndarray, y: np.ndarray, features: list[str]) -> None:
    """Figura 12 — curva de aprendizado do RF/XGB por tamanho do treino."""
    fracoes = [0.1, 0.25, 0.5, 0.75, 1.0]
    splits = TimeSeriesSplit(n_splits=5)
    tr_idx, te_idx = list(splits.split(X))[-1]  # última dobra (teste mais recente)

    resultados = {"frac": [], "modelo": [], "r2": []}
    modelos = {
        "RandomForest": RandomForestRegressor(
            n_estimators=150, max_depth=10, n_jobs=-1,
            random_state=cfg.random_state),
    }
    try:
        from xgboost import XGBRegressor
        modelos["XGBoost"] = XGBRegressor(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            n_jobs=-1, random_state=cfg.random_state, verbosity=0)
    except ImportError:
        pass

    n_tr = len(tr_idx)
    for frac in fracoes:
        n_use = int(n_tr * frac)
        if n_use < 50:
            continue
        for nome, mdl in modelos.items():
            mdl.fit(X[tr_idx[:n_use]], y[tr_idx[:n_use]])
            r2 = r2_score(y[te_idx], mdl.predict(X[te_idx]))
            resultados["frac"].append(frac)
            resultados["modelo"].append(nome)
            resultados["r2"].append(r2)
    res = pd.DataFrame(resultados)

    fig, ax = plt.subplots(figsize=(8, 5))
    for nome, sub in res.groupby("modelo"):
        ax.plot(sub["frac"], sub["r2"], "-o", lw=2, label=nome)
    ax.set_xlabel("Fração do conjunto de treino utilizada")
    ax.set_ylabel("R² no teste")
    
    
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    dest = cfg.figures_dir / "fig12_curvas_aprendizado.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def main() -> None:
    df = carregar_dados()
    feats_df, features = criar_features(df, doenca=cfg.doenca_principal)

    # Para experimentação rápida com dados sintéticos, amostra estratificada
    # por ano (garante representatividade temporal). Em dados reais, pular
    # esta amostragem.
    if len(feats_df) > 20_000:
        log.info(f"Amostrando {20_000} linhas (de {len(feats_df):,}) para acelerar treino…")
        feats_df = (
            feats_df.groupby("ano_epidem", group_keys=False)[feats_df.columns.tolist()]
            .apply(lambda g: g.sample(min(len(g), 1700), random_state=cfg.random_state))
            .reset_index(drop=True)
        )
        feats_df = feats_df.sort_values(["cod_ibge_7", "ano_epidem", "sem_epidem"]).reset_index(drop=True)
        log.info(f"  Após amostragem: {len(feats_df):,}")

    X = feats_df[features].values.astype(float)
    y = feats_df["casos_t4"].values.astype(float)
    log.info(f"X shape: {X.shape}  |  y shape: {y.shape}")

    modelos = construir_modelos()
    resumo: list[dict] = []
    rf_final = None

    for nome, mdl in modelos.items():
        log.info(f"Validando {nome} …")
        m = validar_cruzado(X, y, mdl, n_splits=5)
        resumo.append({"Modelo": nome,
                       "RMSE": f"{m['RMSE_mean']:.1f} ± {m['RMSE_std']:.1f}",
                       "MAE":  f"{m['MAE_mean']:.1f} ± {m['MAE_std']:.1f}",
                       "R²":   f"{m['R2_mean']:.3f} ± {m['R2_std']:.3f}"})
        log.info(f"  RMSE = {m['RMSE_mean']:.1f} ± {m['RMSE_std']:.1f}")
        log.info(f"  MAE  = {m['MAE_mean']:.1f} ± {m['MAE_std']:.1f}")
        log.info(f"  R²   = {m['R2_mean']:.3f} ± {m['R2_std']:.3f}")

        # Re-treina no conjunto completo (para salvar e gerar figs)
        mdl.fit(X, y)
        joblib.dump(mdl, cfg.models_dir / f"{nome.lower()}.joblib")
        if nome == "RandomForest":
            rf_final = mdl

    pd.DataFrame(resumo).to_csv(
        cfg.outputs_dir / "tabela6_metricas_modelos.csv", index=False
    )
    log.info("Tabela 6 (métricas) salva.")

    # Figuras
    if rf_final is not None:
        figura_importancia(rf_final, features)
        # Previsto vs. Real — última dobra de teste
        tr_idx, te_idx = list(TimeSeriesSplit(n_splits=5).split(X))[-1]
        rf_final.fit(X[tr_idx], y[tr_idx])
        figura_previsto_vs_real(y[te_idx], rf_final.predict(X[te_idx]), "Random Forest")
        figura_curvas_aprendizado(X, y, features)


if __name__ == "__main__":
    main()
