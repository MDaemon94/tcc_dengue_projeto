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
import re
import unicodedata

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


UF_VALIDAS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
}


def _normalizar_nome(s) -> str:
    """Remove acentos, pontuacao e espacos; tudo minusculo.

    Ex.: "Olho-d'Agua do Borges" -> "olhodaguadoborges". Serve para
    casar nomes de municipio entre o Atlas Brasil e o IBGE, que diferem
    em hifen/apostrofo/acentuacao.
    """
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _carregar_atlas_brasil_xlsx(caminho, value_cols: list[str]) -> pd.DataFrame:
    """Le uma planilha municipal bruta do Atlas Brasil.

    Essas planilhas (IDHM, saneamento, etc.) NAO possuem codigo IBGE:
    a coluna A e 'Territorialidades' no formato 'Municipio (UF)' e as
    colunas seguintes sao os indicadores. A renomeacao e POSICIONAL
    (coluna A -> chave de municipio; colunas B..N -> `value_cols`, nessa
    ordem), o que evita depender do texto exato dos cabecalhos longos.

    Devolve um frame com a chave normalizada 'nome|uf' (coluna
    'chave_mun') mais as colunas em `value_cols`. As linhas de
    cabecalho/rodape (Brasil, fontes, vazia) sao descartadas por nao
    baterem no padrao 'Nome (UF)'.
    """
    n = 1 + len(value_cols)
    raw = pd.read_excel(caminho, usecols=range(n))
    raw.columns = ["territorialidade", *value_cols]
    extr = raw["territorialidade"].astype(str).str.extract(
        r"^(?P<municipio>.*)\s+\((?P<uf_sigla>[A-Z]{2})\)\s*$"
    )
    raw = raw.join(extr)
    raw = raw[raw["uf_sigla"].isin(UF_VALIDAS)].copy()
    raw["chave_mun"] = raw["municipio"].map(_normalizar_nome) + "|" + raw["uf_sigla"]
    return raw[["chave_mun", *value_cols]].reset_index(drop=True)


def _resolver_cod_ibge_por_nome(df: pd.DataFrame, fonte: str = "Atlas") -> pd.DataFrame:
    """Anexa cod_ibge_7 cruzando nome+uf (chave_mun) com municipios_ibge.csv.

    As planilhas do Atlas Brasil nao trazem codigo IBGE, entao a
    referencia municipios_ibge.csv (mesma usada na integracao) e
    obrigatoria para o caminho .xlsx. Sem ela, retorna frame vazio e o
    merge correspondente e pulado. `fonte` so rotula as mensagens de log.
    """
    ref_path = cfg.raw_dir / "ibge" / "municipios_ibge.csv"
    if not ref_path.exists():
        log.warning(
            f"{fonte} em .xlsx exige municipios_ibge.csv para resolver cod_ibge_7 "
            "(o Atlas Brasil nao traz codigo IBGE). Pulando merge."
        )
        return pd.DataFrame()

    ref = pd.read_csv(ref_path, dtype={"cod_ibge_7": str})
    if not {"municipio", "uf_sigla", "cod_ibge_7"}.issubset(ref.columns):
        log.warning(
            "municipios_ibge.csv sem colunas municipio/uf_sigla/cod_ibge_7. "
            f"Pulando merge {fonte}."
        )
        return pd.DataFrame()

    ref["chave_mun"] = ref["municipio"].map(_normalizar_nome) + "|" + ref["uf_sigla"]
    ref = ref[["chave_mun", "cod_ibge_7"]].drop_duplicates("chave_mun")

    out = df.merge(ref, on="chave_mun", how="left")
    sem = out["cod_ibge_7"].isna()
    if sem.any():
        log.warning(
            f"{fonte}: {int(sem.sum())} municipios sem cod_ibge_7 "
            "(divergencia de grafia ou criados apos 2010)."
        )
    return out.dropna(subset=["cod_ibge_7"]).drop(columns=["chave_mun"])


def carregar_ibge() -> pd.DataFrame:
    """Carrega IDHM municipal (Atlas Brasil 2010), sempre com a chave cod_ibge_7.

    Ordem de preferencia:
      1. idhm_municipal_normalizado.csv -> ja contem cod_ibge_7;
      2. idhm_municipal.xlsx (bruto do Atlas) -> resolve cod_ibge_7 por
         nome+uf usando municipios_ibge.csv.
    """
    csv_path = cfg.raw_dir / "ibge" / "idhm_municipal_normalizado.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path, dtype={"cod_ibge_7": str})

    xlsx_path = cfg.raw_dir / "ibge" / "idhm_municipal.xlsx"
    if xlsx_path.exists():
        idhm = _carregar_atlas_brasil_xlsx(
            xlsx_path,
            ["idhm", "idhm_renda", "idhm_longevidade", "idhm_educacao"],
        )
        return _resolver_cod_ibge_por_nome(idhm, fonte="IDHM")

    log.warning("IDHM ausente (nem .csv normalizado nem .xlsx). Pulando merge IDHM.")
    return pd.DataFrame()


def carregar_saneamento() -> pd.DataFrame:
    """Carrega indicadores de saneamento municipal (Atlas Brasil, base 2010),
    sempre com a chave cod_ibge_7.

    Colunas de saida:
      - pct_agua_encanada
      - pct_banheiro_agua_encanada
      - pct_coleta_lixo_urb
      - pct_agua_esgoto_inadeq

    Ordem de preferencia:
      1. saneamento_municipal_normalizado.csv -> ja contem cod_ibge_7;
      2. saneamento_municipal.xlsx (bruto do Atlas) -> resolve cod_ibge_7
         por nome+uf usando municipios_ibge.csv.
    """
    val_cols = [
        "pct_agua_encanada",
        "pct_banheiro_agua_encanada",
        "pct_coleta_lixo_urb",
        "pct_agua_esgoto_inadeq",
    ]

    csv_path = cfg.raw_dir / "ibge" / "saneamento_municipal_normalizado.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path, dtype={"cod_ibge_7": str})

    xlsx_path = cfg.raw_dir / "ibge" / "saneamento_municipal.xlsx"
    if xlsx_path.exists():
        san = _carregar_atlas_brasil_xlsx(xlsx_path, val_cols)
        return _resolver_cod_ibge_por_nome(san, fonte="Saneamento")

    log.warning("Saneamento ausente (nem .csv normalizado nem .xlsx). Pulando merge.")
    return pd.DataFrame()


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

    # Tenta resolver cod_ibge_7 + atributos geográficos a partir da tabela do IBGE
    munic_path = cfg.raw_dir / "ibge" / "municipios_ibge.csv"
    if munic_path.exists():
        mun = pd.read_csv(munic_path,
                          dtype={"cod_ibge_6": str, "cod_ibge_7": str})
        cols_geo = [c for c in ["cod_ibge_6", "cod_ibge_7", "municipio",
                                "uf_sigla", "regiao"] if c in mun.columns]
        df = df.merge(mun[cols_geo], on="cod_ibge_6", how="left")
    else:
        df["cod_ibge_7"] = df["cod_ibge_6"]  # fallback

    # Fallback robusto: deriva a regiao pelo prefixo do codigo IBGE (digitos 1-2)
    # garantindo que a coluna 'regiao' SEMPRE exista, mesmo sem municipios_ibge.csv
    PREFIXO2REGIAO = {
        "1": "Norte", "2": "Nordeste", "3": "Sudeste",
        "4": "Sul", "5": "Centro-Oeste",
    }
    if "regiao" not in df.columns:
        df["regiao"] = pd.NA
    falta = df["regiao"].isna()
    if falta.any():
        df.loc[falta, "regiao"] = (
            df.loc[falta, "cod_ibge_7"].str[0].map(PREFIXO2REGIAO)
        )
    log.info(f"Coluna 'regiao' preenchida ({df['regiao'].notna().sum():,} linhas).")

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
        log.info(f"Merge saneamento (Atlas Brasil 2010) ok.")

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