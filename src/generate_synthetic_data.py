"""
generate_synthetic_data.py
==========================

Gerador de dados sintéticos REALISTAS para fins de
demonstração/reprodução do pipeline analítico quando os
microdados originais (SINAN/INMET) não estão disponíveis
localmente — por exemplo, ao executar o repositório pela
primeira vez ou em ambientes sem acesso à API do INMET.

Os parâmetros estatísticos (médias, sazonalidade, correlações)
foram calibrados a partir dos boletins epidemiológicos do
Ministério da Saúde (BRASIL, 2024) e do painel de
Monitoramento das Arboviroses do SVSA/MS.

ATENÇÃO
-------
Os dados produzidos por este script NÃO são reais. Para
reproduzir integralmente as análises do TCC com dados
oficiais, execute os scripts `collect_sinan.py`,
`collect_inmet.py` e `collect_ibge_pni.py` antes.

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
log = logging.getLogger("synth")


RNG = np.random.default_rng(cfg.random_state)


# Volumes anuais aproximados (em milhares) com base no Painel de
# Monitoramento das Arboviroses do MS (BRASIL, 2024) e Boletins.
VOLUMES_DENGUE_ANUAL = {
    2015: 1_649,
    2016: 1_487,
    2017:   252,
    2018:   265,
    2019: 1_544,
    2020:   978,
    2021:   534,
    2022: 1_450,
    2023: 1_658,
    2024: 6_485,   # maior epidemia da história
    2025: 1_711,
    2026:   420,   # parcial (queda de 75% vs 2025)
}
VOLUMES_ZIKA_ANUAL = {
    2015: 30, 2016: 215, 2017: 17, 2018: 9, 2019: 11,
    2020: 7,  2021: 5,  2022: 9,  2023: 23, 2024: 38,
    2025: 30, 2026: 10,
}
VOLUMES_CHIK_ANUAL = {
    2015: 38,  2016: 271, 2017: 185, 2018: 88, 2019: 124,
    2020: 95, 2021: 92, 2022: 174, 2023: 217, 2024: 360,
    2025: 160, 2026: 60,
}

# Distribuição regional aproximada (Boletim MS 2024)
PESO_REGIAO = {
    "Norte":         0.07,
    "Nordeste":      0.20,
    "Sudeste":       0.45,
    "Sul":           0.10,
    "Centro-Oeste":  0.18,
}


def gerar_municipios() -> pd.DataFrame:
    """
    Gera tabela sintética de municípios brasileiros (n ~ 200,
    amostragem representativa para testes; o pipeline real
    operaria sobre os 5.570 municípios).
    """
    regs   = list(PESO_REGIAO)
    pesos  = np.array(list(PESO_REGIAO.values()))
    n_mun  = 200
    quotas = (pesos * n_mun).astype(int)
    rows: list[dict] = []
    base_id = 1100000
    for r, q in zip(regs, quotas):
        for i in range(q):
            base_id += 1
            rows.append({
                "cod_ibge_7":   str(base_id),
                "municipio":    f"Municipio_{base_id}",
                "regiao":       r,
                "uf_sigla":     "BR",
                "populacao":    int(RNG.lognormal(mean=10.0, sigma=1.3)),
                "idhm":         float(np.clip(RNG.normal(0.70, 0.07), 0.45, 0.90)),
                "dens_demo":    float(np.clip(RNG.gamma(2.0, 50), 0.5, 8000)),
                "cobertura_sanea": float(np.clip(RNG.normal(0.65, 0.20), 0.05, 0.99)),
            })
    return pd.DataFrame(rows)


def gerar_serie_temporal_doenca(
    doenca: str,
    volumes_anual: dict[int, int],
    municipios: pd.DataFrame,
    pico_se_inicio: int = 7,
    pico_se_fim:    int = 13,
) -> pd.DataFrame:
    """
    Gera série semanal por município com sazonalidade entre
    SE pico_se_inicio e pico_se_fim, modulada pela população
    e pelo IDHM (efeito protetor) do município.
    """
    rows: list[dict] = []

    for ano, vol_mil in volumes_anual.items():
        # Casos totais simulados nesse ano (escala milhares→absoluto)
        total_ano = vol_mil * 1000

        # 52 ou 53 SE — uma curva sazonal gaussiana centrada no pico
        n_se = 52
        se_eixo = np.arange(1, n_se + 1)
        centro = (pico_se_inicio + pico_se_fim) / 2
        largura = (pico_se_fim - pico_se_inicio + 4) / 2.355  # FWHM→σ
        curva = np.exp(-0.5 * ((se_eixo - centro) / largura) ** 2)
        curva = curva / curva.sum()  # normaliza

        # Pesos municipais ~ população × (1 - 0.3*IDHM)
        peso_mun = (
            municipios["populacao"].values
            * (1.0 - 0.3 * municipios["idhm"].values)
        )
        peso_mun = peso_mun / peso_mun.sum()

        # Distribui casos: matriz municípios × semanas
        # Usamos um multinomial em duas etapas (aproximação)
        casos_mun = RNG.multinomial(total_ano, peso_mun)
        for mi, mun_row in municipios.reset_index(drop=True).iterrows():
            casos_se = RNG.multinomial(int(casos_mun[mi]), curva)
            for se, c in enumerate(casos_se, start=1):
                if c == 0:
                    continue
                rows.append({
                    "ano_epidem":  ano,
                    "sem_epidem":  se,
                    "cod_ibge_7":  mun_row["cod_ibge_7"],
                    "doenca":      doenca,
                    "casos":       int(c),
                })

    return pd.DataFrame(rows)


def gerar_clima(municipios: pd.DataFrame) -> pd.DataFrame:
    """
    Gera dados climáticos sintéticos semanais por município:
    - precipitação acumulada (mm/sem)
    - temperatura média (°C)
    - umidade relativa (%)

    Sazonalidade típica do clima tropical do Brasil: maior
    precipitação em SE 1–15 e queda na seca austral.
    """
    rows: list[dict] = []
    for ano in range(cfg.ano_inicio, cfg.ano_fim + 1):
        for se in range(1, 53):
            # Padrão sazonal nacional
            t_med_base = 24 + 4 * np.cos(2 * np.pi * (se - 5) / 52)
            prec_base  = 50 + 80 * np.cos(2 * np.pi * (se - 5) / 52)
            umid_base  = 75 + 10 * np.cos(2 * np.pi * (se - 5) / 52)
            for _, mun in municipios.iterrows():
                # Ajuste regional simples
                ajustes = {
                    "Norte":         (+2.0, +30.0, +5.0),
                    "Nordeste":      (+1.0, -10.0, -2.0),
                    "Sudeste":       (0.0,    0.0,  0.0),
                    "Sul":           (-3.0, -20.0,  0.0),
                    "Centro-Oeste":  (+0.5, +10.0, -3.0),
                }
                dt, dp, du = ajustes[mun["regiao"]]
                rows.append({
                    "ano_epidem":   ano,
                    "sem_epidem":   se,
                    "cod_ibge_7":   mun["cod_ibge_7"],
                    "precipitacao": max(0.0, prec_base + dp + RNG.normal(0, 15)),
                    "temp_media":   t_med_base + dt + RNG.normal(0, 1.0),
                    "umidade":      np.clip(umid_base + du + RNG.normal(0, 5), 20, 100),
                })
    return pd.DataFrame(rows)


def main() -> None:
    log.info("Gerando municípios sintéticos…")
    municipios = gerar_municipios()
    log.info(f"  {len(municipios)} municípios.")

    log.info("Gerando séries de casos (dengue)…")
    dengue = gerar_serie_temporal_doenca("dengue", VOLUMES_DENGUE_ANUAL, municipios)
    log.info(f"  {len(dengue):,} linhas (município×SE).")

    log.info("Gerando séries de casos (zika)…")
    zika   = gerar_serie_temporal_doenca("zika",   VOLUMES_ZIKA_ANUAL,   municipios,
                                         pico_se_inicio=10, pico_se_fim=18)

    log.info("Gerando séries de casos (chikungunya)…")
    chik   = gerar_serie_temporal_doenca("chikungunya", VOLUMES_CHIK_ANUAL, municipios,
                                         pico_se_inicio=12, pico_se_fim=20)

    log.info("Gerando clima sintético…")
    clima  = gerar_clima(municipios)

    casos = pd.concat([dengue, zika, chik], ignore_index=True)

    # Salva no formato esperado pelo pipeline real
    municipios.to_parquet(cfg.processed_dir / "municipios_sinteticos.parquet", index=False)
    casos.to_parquet(cfg.processed_dir / "casos_sinteticos.parquet", index=False)
    clima.to_parquet(cfg.processed_dir / "clima_sintetico.parquet", index=False)

    # Tabela analítica consolidada (sintética) — formato do dados_integrados
    integrado = casos.merge(
        clima, on=["ano_epidem", "sem_epidem", "cod_ibge_7"], how="left"
    ).merge(
        municipios.drop(columns=["municipio", "uf_sigla"]),
        on="cod_ibge_7", how="left",
    )
    integrado["tx_incidencia"] = (integrado["casos"] / integrado["populacao"]) * 100_000
    integrado.to_parquet(cfg.processed_dir / "dados_integrados_sinteticos.parquet", index=False)

    log.info("Dados sintéticos gerados com sucesso.")
    log.info(f"  Total de casos:   {casos['casos'].sum():,}")
    log.info(f"  Anos:             {sorted(casos['ano_epidem'].unique())}")
    log.info(f"  Tabela integrada: {len(integrado):,} linhas")


if __name__ == "__main__":
    main()
