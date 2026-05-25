"""
collect_ibge_pni.py
===================

Coleta dados socioeconômicos do IBGE (população, IDHM, densidade
demográfica, saneamento básico) e cobertura vacinal contra dengue
do Programa Nacional de Imunizações (PNI), via OpenDataSUS.

A vacina Qdenga foi incorporada ao SUS em fevereiro de 2024
(BRASIL, 2024), e é uma variável muito relevante para a análise
epidemiológica do período 2024–2026.

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("collect_ibge_pni")


# Tabelas SIDRA do IBGE — referências oficiais
SIDRA_POPULACAO = "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324"
SIDRA_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"

# OpenDataSUS — vacinação dengue (Qdenga) por município
# (formato CSV em https://opendatasus.saude.gov.br/dataset)
URL_PNI_DENGUE = (
    "https://opendatasus.saude.gov.br/dataset/"
    "campanha-vacinacao-dengue-2024"
)


def _get_uf_info(mun: dict) -> tuple[str | None, str | None, str | None]:
    """
    Extrai (uf_sigla, uf_nome, regiao_nome) do JSON de um municipio.

    A API do IBGE retorna esses dados em DOIS lugares:
      a) caminho aninhado: microrregiao.mesorregiao.UF.{sigla,nome,regiao.nome}
      b) caminho direto:   regiao-imediata.regiao-intermediaria.UF.{...}

    Alguns municipios (distritos estaduais, criados pos-Censo 2022,
    reorganizados) tem (a) como null. Esta funcao tenta (a), depois (b),
    e retorna (None, None, None) se ambos falharem — para esses municipios
    podemos preencher depois a partir do prefixo do codigo IBGE
    (digitos 1-2 = codigo da UF).
    """
    # Tentativa 1: caminho aninhado classico
    micro = mun.get("microrregiao") or {}
    meso = micro.get("mesorregiao") or {}
    uf = meso.get("UF") or {}
    if uf:
        regiao = uf.get("regiao") or {}
        return uf.get("sigla"), uf.get("nome"), regiao.get("nome")

    # Tentativa 2: caminho via regiao-imediata (estrutura nova pos-2017)
    ri = mun.get("regiao-imediata") or {}
    rin = ri.get("regiao-intermediaria") or {}
    uf = rin.get("UF") or {}
    if uf:
        regiao = uf.get("regiao") or {}
        return uf.get("sigla"), uf.get("nome"), regiao.get("nome")

    return None, None, None


# Tabela de fallback: prefixo do codigo IBGE (digitos 1-2) -> UF e regiao.
# Cobre todos os 27 entes federativos.
PREFIXO2UF = {
    "11": ("RO", "Rondonia",          "Norte"),
    "12": ("AC", "Acre",              "Norte"),
    "13": ("AM", "Amazonas",          "Norte"),
    "14": ("RR", "Roraima",           "Norte"),
    "15": ("PA", "Para",              "Norte"),
    "16": ("AP", "Amapa",             "Norte"),
    "17": ("TO", "Tocantins",         "Norte"),
    "21": ("MA", "Maranhao",          "Nordeste"),
    "22": ("PI", "Piaui",             "Nordeste"),
    "23": ("CE", "Ceara",             "Nordeste"),
    "24": ("RN", "Rio Grande do Norte", "Nordeste"),
    "25": ("PB", "Paraiba",           "Nordeste"),
    "26": ("PE", "Pernambuco",        "Nordeste"),
    "27": ("AL", "Alagoas",           "Nordeste"),
    "28": ("SE", "Sergipe",           "Nordeste"),
    "29": ("BA", "Bahia",             "Nordeste"),
    "31": ("MG", "Minas Gerais",      "Sudeste"),
    "32": ("ES", "Espirito Santo",    "Sudeste"),
    "33": ("RJ", "Rio de Janeiro",    "Sudeste"),
    "35": ("SP", "Sao Paulo",         "Sudeste"),
    "41": ("PR", "Parana",            "Sul"),
    "42": ("SC", "Santa Catarina",    "Sul"),
    "43": ("RS", "Rio Grande do Sul", "Sul"),
    "50": ("MS", "Mato Grosso do Sul","Centro-Oeste"),
    "51": ("MT", "Mato Grosso",       "Centro-Oeste"),
    "52": ("GO", "Goias",             "Centro-Oeste"),
    "53": ("DF", "Distrito Federal",  "Centro-Oeste"),
}


def baixar_municipios_ibge() -> pd.DataFrame:
    """Baixa a lista completa de municipios brasileiros (5.570) via IBGE."""
    log.info("Baixando lista de municipios IBGE...")
    resp = requests.get(SIDRA_MUNICIPIOS, timeout=60)
    resp.raise_for_status()

    rows = []
    sem_uf = 0
    for mun in resp.json():
        cod7 = str(mun.get("id", "")).zfill(7)
        cod6 = cod7[:6]
        nome = mun.get("nome", "")

        uf_sigla, uf_nome, regiao = _get_uf_info(mun)

        # Fallback pelo prefixo do codigo IBGE
        if uf_sigla is None:
            prefixo = cod7[:2]
            if prefixo in PREFIXO2UF:
                uf_sigla, uf_nome, regiao = PREFIXO2UF[prefixo]
                sem_uf += 1
            else:
                log.warning(f"  Municipio sem UF identificavel: id={cod7} nome={nome}")
                continue

        rows.append({
            "cod_ibge_7": cod7,
            "cod_ibge_6": cod6,
            "municipio":  nome,
            "uf_sigla":   uf_sigla,
            "uf_nome":    uf_nome,
            "regiao":     regiao,
        })

    df = pd.DataFrame(rows)
    log.info(f"  {len(df)} municipios coletados.")
    if sem_uf > 0:
        log.info(f"  {sem_uf} usaram fallback por prefixo do codigo IBGE.")
    return df


def _tabela_e_variavel_por_ano(ano: int) -> tuple[int, int]:
    """
    Retorna (id_tabela_sidra, id_variavel) apropriado para o ano.

    O IBGE distribui as series de populacao por municipio em tabelas
    distintas dependendo do contexto:
      - 6579: Estimativas anuais  (2001 a 2021, suspenso em 2022)
      - 9514: Censo 2022          (apenas 2022)
      - 9923: Estimativas pos-Censo 2022 (2023 em diante)
    """
    if ano <= 2021:
        return 6579, 9324   # variavel 9324 = "Populacao residente estimada"
    if ano == 2022:
        return 9514, 93     # variavel 93   = "Populacao residente"
    return 9923, 9324       # mesma variavel da serie historica retomada


def _parse_populacao(valor) -> int | None:
    """
    Converte o valor de populacao do JSON do IBGE para int.

    O SIDRA usa convencoes de sentinela:
      '...'  -> dado nao disponivel
      '-'    -> fenomeno inexistente
      '..'   -> dado nao se aplica
      ''/None -> ausente
    Qualquer um desses vira None aqui.
    """
    if valor is None:
        return None
    s = str(valor).strip()
    if s in ("", "...", "..", "-", "X"):
        return None
    try:
        # Remove possiveis separadores de milhar
        return int(s.replace(".", "").replace(",", ""))
    except ValueError:
        return None


def baixar_populacao_municipal() -> pd.DataFrame:
    """
    Baixa populacao municipal anual para o periodo configurado.

    Estrategia: para cada ano, escolhe a tabela SIDRA apropriada
    (6579 para 2015-2021, 9514 para 2022, 9923 para 2023+).
    """
    log.info("Baixando populacao municipal IBGE (multi-tabela)...")
    rows: list[dict] = []

    for ano in range(cfg.ano_inicio, cfg.ano_fim + 1):
        tabela, variavel = _tabela_e_variavel_por_ano(ano)
        url = (
            f"https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/"
            f"periodos/{ano}/variaveis/{variavel}"
            f"?localidades=N6[all]"
        )
        try:
            resp = requests.get(url, timeout=90)
            if resp.status_code != 200:
                log.warning(f"  {ano} (tab {tabela}): HTTP {resp.status_code}")
                continue
            payload = resp.json()
            if not payload:
                log.warning(f"  {ano} (tab {tabela}): payload vazio")
                continue

            n_ok = 0
            n_nulos = 0
            for r in payload[0]["resultados"][0]["series"]:
                cod = r["localidade"]["id"]
                val = r["serie"].get(str(ano))
                pop = _parse_populacao(val)
                if pop is None:
                    n_nulos += 1
                    continue
                rows.append({
                    "cod_ibge_7": str(cod).zfill(7),
                    "ano":        ano,
                    "populacao":  pop,
                })
                n_ok += 1

            msg = f"  {ano} (tab {tabela}): {n_ok:,} municipios"
            if n_nulos:
                msg += f"  ({n_nulos} sem dado)"
            log.info(msg)

        except Exception as e:  # noqa: BLE001
            log.warning(f"  {ano} (tab {tabela}): {e}")

    df = pd.DataFrame(rows)
    if df.empty:
        log.error("Nenhum dado de populacao foi coletado!")
    else:
        log.info(f"Total: {len(df):,} linhas ({df['ano'].nunique()} anos).")
    return df


def _normalizar_nome(s: str) -> str:
    """
    Normaliza nome de municipio para matching robusto:
    remove acentos, apostrofes, lowercase, espacos extras.
    Ex: "São José d'Oeste" -> "sao jose doeste"
    """
    import unicodedata
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip().replace("'", "").replace("`", "")
    s = re.sub(r"\s+", " ", s)
    return s


def carregar_idhm_pnud() -> pd.DataFrame:
    """
    Carrega o IDHM municipal do Atlas Brasil (Censo 2010).

    Aceita o arquivo .XLSX exportado diretamente da interface
    `atlasbrasil.org.br/consulta/planilha`, que NAO contem codigo
    IBGE (so nome do municipio + UF entre parenteses).

    Estrategia:
      1. Le o arquivo Excel.
      2. Filtra apenas linhas com padrao "Nome (UF)" - remove
         totalizador "Brasil", linhas de rodape e NaN.
      3. Extrai nome do municipio e UF.
      4. Faz matching com a tabela `municipios_ibge.csv` (gerada
         pela coleta automatica via API IBGE) usando nome
         normalizado (sem acentos) + UF como chave composta.

    Retorna DataFrame com colunas:
        cod_ibge_7, municipio, idhm, idhm_renda, idhm_long, idhm_educ

    Aceita tambem .csv ou .csv.tsv para retrocompatibilidade.
    """
    base = cfg.raw_dir / "ibge"

    # Procura o arquivo em ordem de prioridade
    candidatos = [
        base / "idhm_municipal.xlsx",
        base / "idhm_municipal.csv",
        base / "data.xlsx",                # nome padrao do download Atlas
    ]
    # Tambem aceita qualquer .xlsx que contenha "idhm" no nome
    candidatos += list(base.glob("*idhm*.xlsx"))
    candidatos += list(base.glob("data*.xlsx"))

    caminho = next((c for c in candidatos if c.exists()), None)
    if caminho is None:
        log.warning(
            f"Arquivo IDHM ausente em {base}/.\n"
            "  Esperado: idhm_municipal.xlsx (ou .csv).\n"
            "  Baixe manualmente em http://www.atlasbrasil.org.br/consulta/planilha\n"
            "  Veja passo-a-passo em DATASETS.md secao 3.3."
        )
        return pd.DataFrame()

    # Le o arquivo (xlsx ou csv) com deteccao automatica
    log.info(f"Carregando IDHM de {caminho.name}")
    try:
        if caminho.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(caminho)
        else:
            # CSV: tenta varios separadores/encodings
            df = None
            for sep in [";", ",", "\t"]:
                for enc in ["utf-8", "latin-1", "cp1252"]:
                    try:
                        tmp = pd.read_csv(caminho, sep=sep, encoding=enc, decimal=",")
                        if len(tmp.columns) >= 3:
                            df = tmp
                            break
                    except Exception:
                        continue
                if df is not None:
                    break
            if df is None:
                log.error(f"Nao foi possivel ler {caminho}")
                return pd.DataFrame()
    except Exception as e:  # noqa: BLE001
        log.error(f"Falha lendo {caminho}: {e}")
        return pd.DataFrame()

    # Identifica coluna do nome/territorialidade
    col_terr = None
    for c in df.columns:
        cl = str(c).lower().strip()
        if "territorial" in cl or "municipio" in cl or "localidade" in cl:
            col_terr = c
            break
    if col_terr is None:
        # Assume primeira coluna como territorialidade
        col_terr = df.columns[0]

    # Mapeia colunas de IDHM (flexivel a variacoes de capitalizacao/sufixos)
    mapa = {}
    for c in df.columns:
        cl = str(c).lower().strip().replace(" ", "").replace("_", "")
        if "idhmrenda" in cl or ("renda" in cl and "idhm" in cl):
            mapa[c] = "idhm_renda"
        elif "idhmlong" in cl or ("long" in cl and "idhm" in cl):
            mapa[c] = "idhm_long"
        elif "idhmeduc" in cl or ("educ" in cl and "idhm" in cl):
            mapa[c] = "idhm_educ"
        elif cl.startswith("idhm") and "renda" not in cl and "long" not in cl and "educ" not in cl:
            mapa[c] = "idhm"

    df = df.rename(columns={**mapa, col_terr: "_territorialidade"})
    cols_idhm = [c for c in ["idhm", "idhm_renda", "idhm_long", "idhm_educ"]
                 if c in df.columns]
    if not cols_idhm:
        log.error(f"Nenhuma coluna IDHM encontrada em {caminho.name}. "
                  f"Colunas: {list(df.columns)}")
        return pd.DataFrame()

    # Filtra apenas linhas com padrao "Nome (UF)"
    df = df.dropna(subset=["_territorialidade"]).copy()
    mask = df["_territorialidade"].astype(str).str.contains(
        r"\([A-Z]{2}\)\s*$", regex=True
    )
    n_descartados = (~mask).sum()
    df = df[mask].copy()
    if n_descartados > 0:
        log.info(f"  Descartadas {n_descartados} linhas (rodape, 'Brasil', estados, etc.)")

    # Extrai nome e UF do padrao "Nome (UF)"
    df["municipio_nome"] = (
        df["_territorialidade"].str.replace(r"\s*\([A-Z]{2}\)\s*$", "", regex=True).str.strip()
    )
    df["uf_sigla"] = df["_territorialidade"].str.extract(r"\(([A-Z]{2})\)\s*$")[0]
    df["nome_normalizado"] = df["municipio_nome"].apply(_normalizar_nome)

    # Faz matching com a tabela de municipios IBGE
    munic_path = base / "municipios_ibge.csv"
    if not munic_path.exists():
        log.error(
            f"Arquivo {munic_path} ausente. Rode primeiro:\n"
            "  python src/collect_ibge_pni.py\n"
            "para gerar a tabela de municipios IBGE."
        )
        return pd.DataFrame()

    mun = pd.read_csv(munic_path, dtype={"cod_ibge_7": str, "cod_ibge_6": str})
    mun["nome_normalizado"] = mun["municipio"].apply(_normalizar_nome)

    # Merge por (nome_normalizado, uf_sigla)
    matched = df.merge(
        mun[["cod_ibge_7", "nome_normalizado", "uf_sigla", "municipio"]],
        on=["nome_normalizado", "uf_sigla"],
        how="left",
        suffixes=("", "_ibge"),
    )

    n_match = matched["cod_ibge_7"].notna().sum()
    n_total = len(matched)
    log.info(f"  Matching nome+UF: {n_match}/{n_total} municipios "
             f"({100*n_match/n_total:.1f}%)")

    if n_match < n_total * 0.95:
        # Lista os primeiros 10 sem match para inspecao
        sem_match = matched[matched["cod_ibge_7"].isna()][
            ["municipio_nome", "uf_sigla"]
        ].head(10)
        log.warning(f"  Exemplos sem match (primeiros 10):\n{sem_match.to_string(index=False)}")

    # Mantem apenas os com match e colunas finais
    final = matched.dropna(subset=["cod_ibge_7"]).copy()
    cols_finais = ["cod_ibge_7", "municipio"] + cols_idhm
    final = final[cols_finais].drop_duplicates(subset="cod_ibge_7")
    final["cod_ibge_7"] = final["cod_ibge_7"].astype(str).str.zfill(7)

    log.info(f"IDHM final: {len(final)} municipios com codigo IBGE.")
    return final


def carregar_saneamento_censo2010() -> pd.DataFrame:
    """
    Carrega indicadores de saneamento basico do Atlas Brasil 2013
    (base Censo 2010, mesma fonte do IDHM).

    Por que essa fonte e nao a PNSB 2017?
      - A PNSB 2017 do IBGE entrevista as ENTIDADES executoras de
        servicos de saneamento (companhias), nao os municipios em si.
        Os resultados sao publicados agregados em Brasil/Regioes/UFs,
        nao em granularidade municipal.
      - O Atlas Brasil 2013, ao contrario, fornece indicadores
        municipais (5.565 municipios) de COBERTURA do saneamento
        com base nos microdados do Censo Demografico 2010.
      - Como o IDHM tambem e do Censo 2010 (3.3), usar o saneamento
        da mesma fonte garante consistencia temporal entre todas as
        variaveis socioeconomicas do modelo.
      - E o caminho adotado pela maior parte da literatura epidemio-
        logica brasileira que usa saneamento como preditor de
        arboviroses.

    Aceita o arquivo .XLSX exportado do
    `atlasbrasil.org.br/consulta/planilha` (mesma interface do IDHM).

    Indicadores esperados no arquivo:
      - % da populacao em domicilios com agua encanada (2010)
      - % da populacao que vive em domicilios com banheiro e
        agua encanada (2010)
      - % de pessoas em domicilios urbanos com coleta de lixo (2010)
      - % de pessoas em domicilios com saneamento inadequado (2010)
        [opcional, complementar]

    Saida (DataFrame):
        cod_ibge_7, pct_agua_encanada, pct_banheiro_agua,
        pct_coleta_lixo, pct_sanea_inadequado, score_saneamento

    `score_saneamento` (0 a 1) e uma media ponderada dos 3 indicadores
    positivos (agua=0.3, banheiro_agua=0.4, coleta_lixo=0.3) que
    sintetiza a cobertura geral de saneamento do municipio.
    """
    base = cfg.raw_dir / "ibge"

    # Procura o arquivo (XLSX e prioritario, CSV como fallback)
    candidatos = [
        base / "saneamento_municipal.xlsx",
        base / "saneamento_municipal.csv",
    ]
    candidatos += list(base.glob("*saneamento*.xlsx"))

    caminho = next((c for c in candidatos if c.exists()), None)
    if caminho is None:
        log.warning(
            f"Arquivo de saneamento ausente em {base}/.\n"
            "  Esperado: saneamento_municipal.xlsx\n"
            "  Baixe do Atlas Brasil (mesma interface do IDHM):\n"
            "    http://www.atlasbrasil.org.br/consulta/planilha\n"
            "  Veja passo-a-passo em DATASETS.md secao 3.4."
        )
        return pd.DataFrame()

    # Le o arquivo
    log.info(f"Carregando saneamento de {caminho.name}")
    try:
        if caminho.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(caminho)
        else:
            df = None
            for sep in [";", ","]:
                for enc in ["utf-8", "latin-1", "cp1252"]:
                    try:
                        tmp = pd.read_csv(caminho, sep=sep, encoding=enc, decimal=",")
                        if len(tmp.columns) >= 2:
                            df = tmp
                            break
                    except Exception:
                        continue
                if df is not None:
                    break
            if df is None:
                log.error(f"Nao foi possivel ler {caminho}")
                return pd.DataFrame()
    except Exception as e:  # noqa: BLE001
        log.error(f"Falha lendo {caminho}: {e}")
        return pd.DataFrame()

    # Helper: normaliza nome da coluna removendo acentos para matching robusto
    def _strip_acentos(s):
        import unicodedata
        s = unicodedata.normalize("NFKD", str(s))
        return "".join(c for c in s if not unicodedata.combining(c)).lower()

    # Mapeia colunas (ordem importa: testar combinacoes mais especificas primeiro)
    mapa = {}
    col_terr = df.columns[0]  # primeira coluna sempre e Territorialidades
    for c in df.columns:
        cl = _strip_acentos(c)
        if "banheiro" in cl and "agua encanada" in cl:
            mapa[c] = "pct_banheiro_agua"
        elif "agua encanada" in cl:
            mapa[c] = "pct_agua_encanada"
        elif "coleta de lixo" in cl:
            mapa[c] = "pct_coleta_lixo"
        elif "inadequad" in cl:
            mapa[c] = "pct_sanea_inadequado"

    if not mapa:
        log.error(f"Nenhum indicador de saneamento encontrado em {caminho.name}. "
                  f"Colunas: {list(df.columns)}")
        return pd.DataFrame()

    df = df.rename(columns={**mapa, col_terr: "_territorialidade"})

    # Filtra padrao "Nome (UF)" - descarta 'Brasil' e linhas de rodape
    df = df.dropna(subset=["_territorialidade"]).copy()
    mask = df["_territorialidade"].astype(str).str.contains(
        r"\([A-Z]{2}\)\s*$", regex=True
    )
    n_descartados = (~mask).sum()
    df = df[mask].copy()
    if n_descartados > 0:
        log.info(f"  Descartadas {n_descartados} linhas (rodape, 'Brasil').")

    # Converte indicadores em numerico
    cols_sanea = [c for c in df.columns if c.startswith("pct_")]
    for c in cols_sanea:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Extrai nome e UF
    df["municipio_nome"] = (
        df["_territorialidade"].str.replace(r"\s*\([A-Z]{2}\)\s*$", "", regex=True).str.strip()
    )
    df["uf_sigla"] = df["_territorialidade"].str.extract(r"\(([A-Z]{2})\)\s*$")[0]
    df["nome_normalizado"] = df["municipio_nome"].apply(_normalizar_nome)

    # Matching nome+UF -> codigo IBGE
    munic_path = base / "municipios_ibge.csv"
    if not munic_path.exists():
        log.error(
            f"Arquivo {munic_path} ausente. Rode primeiro:\n"
            "  python src/collect_ibge_pni.py"
        )
        return pd.DataFrame()

    mun = pd.read_csv(munic_path, dtype={"cod_ibge_7": str})
    mun["nome_normalizado"] = mun["municipio"].apply(_normalizar_nome)

    matched = df.merge(
        mun[["cod_ibge_7", "nome_normalizado", "uf_sigla"]],
        on=["nome_normalizado", "uf_sigla"],
        how="left",
    )

    n_match = matched["cod_ibge_7"].notna().sum()
    n_total = len(matched)
    log.info(f"  Matching nome+UF: {n_match}/{n_total} municipios "
             f"({100*n_match/n_total:.1f}%)")

    final = matched.dropna(subset=["cod_ibge_7"]).copy()

    # Score consolidado: media ponderada dos 3 indicadores positivos em [0, 1]
    # Pesos: agua=0.3, banheiro_agua=0.4 (indicador mais discriminante), lixo=0.3
    componentes = {}
    if "pct_agua_encanada" in final.columns:
        componentes["pct_agua_encanada"] = 0.3
    if "pct_banheiro_agua" in final.columns:
        componentes["pct_banheiro_agua"] = 0.4
    if "pct_coleta_lixo" in final.columns:
        componentes["pct_coleta_lixo"] = 0.3

    if componentes:
        peso_total = sum(componentes.values())
        score = sum(final[col].fillna(0) * peso for col, peso in componentes.items())
        final["score_saneamento"] = (score / (peso_total * 100)).round(4)

    cols_finais = ["cod_ibge_7"] + cols_sanea
    if "score_saneamento" in final.columns:
        cols_finais.append("score_saneamento")
    final = final[cols_finais].drop_duplicates(subset="cod_ibge_7")
    final["cod_ibge_7"] = final["cod_ibge_7"].astype(str).str.zfill(7)

    log.info(f"Saneamento (Censo 2010) carregado: {len(final)} municipios. "
             f"Score medio: {final['score_saneamento'].mean():.3f}"
             if "score_saneamento" in final.columns else "")
    return final


# Mantem o nome antigo como alias por retrocompatibilidade
carregar_saneamento_pnsb = carregar_saneamento_censo2010


def carregar_vacinacao_binaria() -> pd.DataFrame:
    """
    Carrega a lista de municipios incluidos na campanha de vacinacao
    contra dengue (Qdenga) por ano, como variavel BINARIA.

    Esperamos um CSV em `data/raw/pni/vacinacao_municipal.csv` com
    estrutura minima:

        cod_ibge_7,ano,vacinou_dengue
        5208707,2024,1
        3304557,2024,1
        ...

    Para os 5.570 municipios em todos os anos 2024-2026 que NAO estao
    no arquivo, o valor sera preenchido como 0 (nao vacinou) ao fazer
    merge na tabela analitica. Para anos < 2024, sempre 0 (vacina nao
    existia no SUS).

    Veja passo-a-passo em DATASETS.md secao 4.
    """
    caminho = cfg.raw_dir / "pni" / "vacinacao_municipal.csv"
    if not caminho.exists():
        log.warning(
            f"Arquivo {caminho} ausente.\n"
            "  Crie manualmente conforme DATASETS.md secao 4.\n"
            "  Sem ele, vacinou_dengue sera tratado como 0 para todos os municipios."
        )
        return pd.DataFrame()

    try:
        df = pd.read_csv(caminho, dtype={"cod_ibge_7": str})
    except Exception as e:  # noqa: BLE001
        log.error(f"Falha ao ler {caminho}: {e}")
        return pd.DataFrame()

    # Validacao basica
    obrigatorias = {"cod_ibge_7", "ano", "vacinou_dengue"}
    if not obrigatorias.issubset(df.columns):
        log.error(f"Colunas obrigatorias ausentes em {caminho}. "
                  f"Esperado: {obrigatorias}, encontrado: {set(df.columns)}")
        return pd.DataFrame()

    df["cod_ibge_7"] = df["cod_ibge_7"].astype(str).str.zfill(7)
    df["ano"] = df["ano"].astype(int)
    df["vacinou_dengue"] = df["vacinou_dengue"].astype("Int8")

    # Mantem so linhas com vacinou_dengue == 1 (as outras serao 0 por default)
    df = df[df["vacinou_dengue"] == 1].copy()

    por_ano = df.groupby("ano").size().to_dict()
    log.info(f"Vacinacao dengue (binaria): {len(df)} municipios-ano "
             f"com campanha: {por_ano}")
    return df


def main() -> None:
    out_dir = cfg.raw_dir / "ibge"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info(" Coleta IBGE/PNI ")
    log.info("=" * 60)

    # --- automaticos (API IBGE) ---
    municipios = baixar_municipios_ibge()
    municipios.to_csv(out_dir / "municipios_ibge.csv", index=False)

    populacao = baixar_populacao_municipal()
    populacao.to_csv(out_dir / "populacao_municipal.csv", index=False)

    # --- carregam de CSVs baixados manualmente ---
    log.info("-" * 60)
    log.info(" Verificando arquivos manuais (ver DATASETS.md) ")
    log.info("-" * 60)

    idhm = carregar_idhm_pnud()
    if not idhm.empty:
        idhm.to_csv(out_dir / "idhm_municipal_normalizado.csv", index=False)

    saneamento = carregar_saneamento_censo2010()
    if not saneamento.empty:
        saneamento.to_csv(out_dir / "saneamento_municipal_normalizado.csv", index=False)

    vacina = carregar_vacinacao_binaria()
    if not vacina.empty:
        (cfg.raw_dir / "pni").mkdir(parents=True, exist_ok=True)
        vacina.to_csv(cfg.raw_dir / "pni" / "vacinacao_municipal_normalizado.csv",
                      index=False)

    log.info("=" * 60)
    log.info(" Resumo da coleta ")
    log.info("=" * 60)
    log.info(f"  Municipios:           {len(municipios):>6,} (esperado ~5.570)")
    log.info(f"  Populacao (linhas):   {len(populacao):>6,} (esperado ~66.840)")
    log.info(f"  IDHM (municipios):    {len(idhm):>6,} (esperado ~5.565)")
    log.info(f"  Saneamento (PNSB):    {len(saneamento):>6,} (esperado ~5.570)")
    log.info(f"  Vacinacao (campanha): {len(vacina):>6,} (esperado ~521+)")

    # Avisos de arquivos faltantes
    faltantes = []
    if idhm.empty:       faltantes.append("IDHM (idhm_municipal.csv)")
    if saneamento.empty: faltantes.append("Saneamento (saneamento_municipal.csv)")
    if vacina.empty:     faltantes.append("Vacinacao (vacinacao_municipal.csv)")
    if faltantes:
        log.warning("")
        log.warning(f"  ARQUIVOS MANUAIS FALTANTES: {len(faltantes)}")
        for f in faltantes:
            log.warning(f"    - {f}")
        log.warning("  Veja DATASETS.md para instrucoes de download.")
        log.warning("  O pipeline ainda funciona, mas variaveis correspondentes")
        log.warning("  serao tratadas como NaN no modelo preditivo.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
