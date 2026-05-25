"""
integrate.py
============

Integração das bases preparadas em uma única tabela analítica
município × semana epidemiológica × doença, com variáveis
climáticas, socioeconômicas e cobertura vacinal.

Saída: data/processed/dados_integrados_{ano_inicio}_{ano_fim}.parquet

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import pandas as pd

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("integrate")


def carregar_sinan_agregado() -> pd.DataFrame:
    """
    Le o SINAN ja limpo (data/processed/sinan_limpo/) PARTICAO POR
    PARTICAO e agrega na granularidade municipio x SE x doenca antes
    de concatenar. Assim, mesmo um SINAN de 24M de linhas vira uma
    tabela agregada com poucos milhoes de linhas, cabendo na RAM.
    """
    src_root = cfg.processed_dir / "sinan_limpo"
    if not src_root.exists():
        raise FileNotFoundError(
            f"Dataset limpo nao encontrado em {src_root}. "
            "Execute: python src/preprocess.py"
        )

    agregados: list[pd.DataFrame] = []
    for doenca in [cfg.doenca_principal, *cfg.arboviroses_exploratorias]:
        for ano in range(cfg.ano_inicio, cfg.ano_fim + 1):
            d = src_root / f"doenca={doenca}" / f"ano={ano}"
            if not d.exists():
                continue
            partes = sorted(d.glob("part-*.parquet"))
            if not partes:
                continue
            log.info(f"[{doenca}/{ano}] agregando {len(partes)} partes ...")
            # Le SO as colunas necessarias para o groupby
            cols = ["ano_epidem", "sem_epidem", "id_mn_resi"]
            df = pd.concat(
                (pd.read_parquet(p, columns=cols) for p in partes),
                ignore_index=True,
            )
            casos = (
                df.groupby(cols, dropna=False)
                  .size()
                  .reset_index(name="casos")
            )
            casos["doenca"] = doenca
            agregados.append(casos)
            del df
    if not agregados:
        return pd.DataFrame()
    final = pd.concat(agregados, ignore_index=True)
    log.info(f"Agregacao total: {len(final):,} linhas (mun x SE x doenca).")
    return final


def agregar_semanal(sinan: pd.DataFrame) -> pd.DataFrame:
    """Mantida por retrocompatibilidade: ja recebe tabela agregada."""
    return sinan


def carregar_clima_municipal() -> pd.DataFrame:
    """Carrega clima já interpolado por município/semana."""
    p = cfg.processed_dir / "clima_municipal.parquet"
    if not p.exists():
        log.warning(f"Clima municipal ausente em {p}. Pulando merge climático.")
        return pd.DataFrame()
    return pd.read_parquet(p)


def carregar_ibge() -> pd.DataFrame:
    """Carrega IDHM normalizado (Atlas Brasil 2010)."""
    p = cfg.raw_dir / "ibge" / "idhm_municipal_normalizado.csv"
    if not p.exists():
        # Fallback: tenta o nome original (caso o usuario tenha
        # baixado direto e ainda nao rodou collect_ibge_pni.py)
        p = cfg.raw_dir / "ibge" / "idhm_municipal.csv"
    if not p.exists():
        log.warning("IDHM ausente. Pulando merge IDHM.")
        return pd.DataFrame()
    return pd.read_csv(p, dtype={"cod_ibge_7": str})


def carregar_saneamento() -> pd.DataFrame:
    """Carrega indicadores de saneamento (PNSB 2017)."""
    p = cfg.raw_dir / "ibge" / "saneamento_municipal_normalizado.csv"
    if not p.exists():
        p = cfg.raw_dir / "ibge" / "saneamento_municipal.csv"
    if not p.exists():
        log.warning("Saneamento (PNSB) ausente. Pulando merge.")
        return pd.DataFrame()
    return pd.read_csv(p, dtype={"cod_ibge_7": str})


def carregar_populacao() -> pd.DataFrame:
    """Carrega população municipal por ano."""
    p = cfg.raw_dir / "ibge" / "populacao_municipal.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, dtype={"cod_ibge_7": str})


def carregar_vacinacao() -> pd.DataFrame:
    """
    Carrega lista BINARIA de municipios com campanha de vacinacao
    contra dengue (Qdenga). Disponivel a partir de 2024.

    Retorna DataFrame com colunas: cod_ibge_7, ano, vacinou_dengue
    """
    p = cfg.raw_dir / "pni" / "vacinacao_municipal_normalizado.csv"
    if not p.exists():
        p = cfg.raw_dir / "pni" / "vacinacao_municipal.csv"
    if not p.exists():
        log.warning("Vacinacao ausente. Sera tratado como 0 para todos os municipios.")
        return pd.DataFrame()
    df = pd.read_csv(p, dtype={"cod_ibge_7": str}, comment="#")
    # Mantem so as linhas onde vacinou_dengue == 1
    if "vacinou_dengue" in df.columns:
        df = df[df["vacinou_dengue"] == 1]
    return df


def integrar() -> pd.DataFrame:
    """Pipeline principal de integracao."""
    casos = carregar_sinan_agregado()
    if casos.empty:
        log.error("Sem dados agregados — abortando integracao.")
        return casos

    # id_mn_resi do SINAN tem 6 digitos; expandimos para 7 com o digito
    # verificador IBGE quando temos a tabela de municipios disponivel.
    df = casos.rename(columns={"id_mn_resi": "cod_ibge_6"})
    df["cod_ibge_6"] = df["cod_ibge_6"].astype(str).str.zfill(6)

    # Tenta resolver cod_ibge_7 a partir da tabela do IBGE
    munic_path = cfg.raw_dir / "ibge" / "municipios_ibge.csv"
    if munic_path.exists():
        mun = pd.read_csv(munic_path,
                          dtype={"cod_ibge_6": str, "cod_ibge_7": str})
        df = df.merge(mun[["cod_ibge_6", "cod_ibge_7"]],
                      on="cod_ibge_6", how="left")
    else:
        df["cod_ibge_7"] = df["cod_ibge_6"]  # fallback

    clima = carregar_clima_municipal()
    if not clima.empty:
        df = df.merge(
            clima,
            on=["ano_epidem", "sem_epidem", "cod_ibge_7"],
            how="left",
        )
        log.info(f"Após merge climático: {len(df):,} linhas.")

    ibge = carregar_ibge()
    if not ibge.empty:
        df = df.merge(ibge, on="cod_ibge_7", how="left")
        log.info(f"Merge IDHM ok ({ibge['idhm'].notna().sum()} municipios com IDHM)."
                 if "idhm" in ibge.columns else "Merge IDHM ok.")

    saneamento = carregar_saneamento()
    if not saneamento.empty:
        df = df.merge(saneamento, on="cod_ibge_7", how="left")
        log.info(f"Merge saneamento (PNSB 2017) ok.")

    pop = carregar_populacao()
    if not pop.empty:
        df = df.merge(
            pop.rename(columns={"ano": "ano_epidem"}),
            on=["cod_ibge_7", "ano_epidem"],
            how="left",
        )
        df["tx_incidencia"] = (df["casos"] / df["populacao"]) * 100_000
        log.info("Taxa de incidencia calculada.")

    vac = carregar_vacinacao()
    if not vac.empty:
        # Merge: traz vacinou_dengue=1 onde aplica
        df = df.merge(
            vac.rename(columns={"ano": "ano_epidem"})[
                ["cod_ibge_7", "ano_epidem", "vacinou_dengue"]
            ],
            on=["cod_ibge_7", "ano_epidem"],
            how="left",
        )
        # Preenche 0 onde nao houve campanha (NaN do merge -> 0)
        df["vacinou_dengue"] = df["vacinou_dengue"].fillna(0).astype("Int8")
        # Tambem 0 para todos os anos < 2024 (vacina nao existia)
        df.loc[df["ano_epidem"] < 2024, "vacinou_dengue"] = 0
        n_vac = (df["vacinou_dengue"] == 1).sum()
        log.info(f"Vacinacao binaria integrada: {n_vac:,} linhas com campanha ativa.")
    else:
        # Sem arquivo de vacinacao, preenche tudo com 0
        df["vacinou_dengue"] = 0
        log.info("Sem dados de vacinacao - coluna vacinou_dengue=0 para todos.")

    dest = cfg.processed_dir / f"dados_integrados_{cfg.ano_inicio}_{cfg.ano_fim}.parquet"
    df.to_parquet(dest, index=False)
    log.info(f"Salvo: {dest}  ({len(df):,} linhas).")
    return df


if __name__ == "__main__":
    integrar()
