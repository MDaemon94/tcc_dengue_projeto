"""
prophet_forecast.py
===================

Previsão univariada de casos semanais de DENGUE no Brasil
com Facebook Prophet, para a série nacional 2015–2026.

Este modelo serve como linha de base interpretável (forte
sazonalidade anual) para comparação com Random Forest e
XGBoost. Não usa variáveis externas (climáticas/IDHM).

Saídas
------
outputs/prophet_metrics.json
figures/fig11b_prophet_forecast.png

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import json
import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

try:
    from prophet import Prophet
    HAS_PROPHET = True
except ImportError:
    HAS_PROPHET = False

from config import cfg
from eda import carregar_dados


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("prophet")


def construir_serie_nacional(df: pd.DataFrame) -> pd.DataFrame:
    """Constrói série semanal nacional de dengue: colunas ds, y."""
    dengue = df[df["doenca"] == "dengue"]
    s = (
        dengue.groupby(["ano_epidem", "sem_epidem"])["casos"]
        .sum()
        .reset_index()
    )
    s["ds"] = pd.to_datetime(
        s["ano_epidem"].astype(str)
        + "-W" + s["sem_epidem"].astype(str).str.zfill(2)
        + "-1",
        format="%G-W%V-%u",
        errors="coerce",
    )
    s = s.dropna(subset=["ds"]).rename(columns={"casos": "y"})
    s = s.sort_values("ds").reset_index(drop=True)
    return s[["ds", "y"]]


def main() -> None:
    if not HAS_PROPHET:
        log.error("prophet não está instalado. Instale com: pip install prophet")
        return

    df = carregar_dados()
    serie = construir_serie_nacional(df)
    log.info(f"Série nacional: {len(serie)} semanas, "
             f"{serie['ds'].min().date()} → {serie['ds'].max().date()}")

    # Split: últimas 26 semanas como teste
    n_teste = 26
    treino = serie.iloc[:-n_teste]
    teste  = serie.iloc[-n_teste:]

    modelo = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode="multiplicative",
        changepoint_prior_scale=0.15,
        interval_width=0.95,
    )
    log.info("Ajustando Prophet…")
    modelo.fit(treino)

    futuro   = modelo.make_future_dataframe(periods=n_teste, freq="W-MON")
    forecast = modelo.predict(futuro)

    prev  = forecast.iloc[-n_teste:]["yhat"].values
    reais = teste["y"].values

    metricas = {
        "rmse": float(np.sqrt(mean_squared_error(reais, prev))),
        "mae":  float(mean_absolute_error(reais, prev)),
        "r2":   float(r2_score(reais, prev)),
        "n_teste": int(n_teste),
    }
    with open(cfg.outputs_dir / "prophet_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metricas, f, indent=2)
    log.info(f"Métricas Prophet: {metricas}")

    # Figura
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(treino["ds"], treino["y"], label="Treino (histórico)", color="#1976D2", lw=1.0)
    ax.plot(teste["ds"], reais, label="Real (teste)", color="black", lw=1.5)
    ax.plot(teste["ds"], prev, label="Previsto (Prophet)", color="#C62828", lw=1.5)
    ax.fill_between(
        forecast.iloc[-n_teste:]["ds"],
        forecast.iloc[-n_teste:]["yhat_lower"],
        forecast.iloc[-n_teste:]["yhat_upper"],
        color="#C62828", alpha=0.20, label="IC 95%",
    )
    ax.set_xlabel("Data")
    ax.set_ylabel("Casos prováveis de dengue (Brasil)")
    ax.set_title("Figura 11 – Previsão Prophet vs. valores reais\n"
                 f"(série nacional, últimas {n_teste} semanas)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    dest = cfg.figures_dir / "fig11_prophet_forecast.png"
    fig.savefig(dest, dpi=200)
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


if __name__ == "__main__":
    main()
