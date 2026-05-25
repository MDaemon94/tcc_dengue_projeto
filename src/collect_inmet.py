"""
collect_inmet.py
================

Processamento dos dados meteorologicos do INMET-BDMEP, periodo 2015-2026.

ESTRATEGIA: DOWNLOAD MANUAL + PROCESSAMENTO AUTOMATIZADO
---------------------------------------------------------
O INMET aplica bloqueios anti-scraping a partir de IPs de datacenter
(WSL2, VMs em cloud, etc.), o que torna o download programatico
instavel. Adotamos uma abordagem hibrida:

    1. VOCE baixa manualmente os 12 ZIPs anuais do portal:
         https://portal.inmet.gov.br/dadoshistoricos
       Coloque-os em: data/raw/inmet/zips/2015.zip, 2016.zip, ...

    2. ESTE SCRIPT le esses ZIPs em streaming, extrai metadados das
       estacoes (lat/lon/alt/UF/codigo WMO) e agrega os dados horarios
       em frequencia diaria e semanal, gravando em Parquet particionado
       por ano e UF.

Estrutura interna de cada ZIP:
- ~600 arquivos CSV, um por estacao automatica
- Primeiras 8 linhas: metadados da estacao
- Linha 9: cabecalho dos dados
- Demais linhas: dados horarios (24/dia x 365 dias = 8760/ano/estacao)

Saidas:
    data/raw/inmet/
    |-- zips/                              # downloads manuais
    |-- estacoes_metadados.parquet         # 1 linha por estacao
    |-- horario/ano=YYYY/uf=XX/part.parquet
    |-- diario/ano=YYYY/uf=XX/part.parquet
    |-- semanal/ano=YYYY/uf=XX/part.parquet
    |-- falhas.csv                         # ZIPs com problema (opcional)

Como rodar:
    python src/collect_inmet.py

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import gc
import io
import logging
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("collect_inmet")


# ---------------------------------------------------------------------
# Leitor de metadados (cabecalho de cada CSV)
# ---------------------------------------------------------------------

# Padroes esperados no cabecalho do CSV do INMET (variam ligeiramente
# por ano; usamos regex tolerantes a maiusculas/minusculas e acentos).
PADROES_META = {
    "regiao":     re.compile(r"REGI\u00c3O[:\s;]+([A-Za-z\u00e3\u00f4\u00e7]+)", re.I),
    "uf":         re.compile(r"UF[:\s;]+([A-Z]{2})", re.I),
    "estacao":    re.compile(r"ESTA[CC]\u00c3O[:\s;]+(.+?)[\r\n;]", re.I),
    "codigo_wmo": re.compile(r"CODIGO\s*\(WMO\)[:\s;]+([A-Z0-9]+)", re.I),
    "latitude":   re.compile(r"LATITUDE[:\s;]+(-?\d+[.,]?\d*)", re.I),
    "longitude":  re.compile(r"LONGITUDE[:\s;]+(-?\d+[.,]?\d*)", re.I),
    "altitude":   re.compile(r"ALTITUDE[:\s;]+(-?\d+[.,]?\d*)", re.I),
    "data_fund":  re.compile(r"DATA DE FUNDA\u00c7\u00c3O[:\s;]+([\d/\-]+)", re.I),
}


def parsear_metadados(linhas_cabecalho: list[str]) -> dict:
    """Extrai metadados das primeiras ~8 linhas do CSV do INMET."""
    texto = "\n".join(linhas_cabecalho)
    meta = {}
    for chave, regex in PADROES_META.items():
        m = regex.search(texto)
        if m:
            valor = m.group(1).strip()
            if chave in ("latitude", "longitude", "altitude"):
                valor = float(valor.replace(",", "."))
            meta[chave] = valor
    return meta


# ---------------------------------------------------------------------
# Renomeacao de colunas do CSV (variam por ano, mas a semantica e estavel)
# ---------------------------------------------------------------------

# Mapeamento das colunas brutas do INMET -> snake_case interno.
# Substrings mais SELETIVAS para evitar colisoes (palavra "horaria"
# aparece em quase todas as colunas do INMET; "hora" sozinho daria
# match em precipitacao, pressao, temperatura, umidade etc.).
# Ordem importa: a primeira que casar vence.
COLUNAS_MAP = [
    ("precipita",                            "precip_mm"),
    ("press\u00e3o atmosferica ao nivel",    "pressao_hpa"),
    ("temperatura do ar",                    "temp_c"),
    ("temperatura m\u00e1xima",              "temp_max_c"),
    ("temperatura m\u00ednima",              "temp_min_c"),
    ("umidade relativa do ar",               "umidade_pct"),
    ("vento, velocidade",                    "vento_ms"),
    ("vento, dire",                          "vento_dir"),
    ("radia",                                "radiacao"),
]


def mapear_colunas(colunas_brutas: list[str]) -> dict:
    """Mapeia colunas brutas do INMET para nomes internos."""
    mapa = {}
    for c in colunas_brutas:
        c_low = c.lower().strip()
        for substr, alvo in COLUNAS_MAP:
            if substr in c_low:
                mapa[c] = alvo
                break
    return mapa


# ---------------------------------------------------------------------
# Processamento de UM CSV de UMA estacao
# ---------------------------------------------------------------------

def processar_csv_estacao(
    zip_obj: zipfile.ZipFile, nome_arquivo: str,
) -> tuple[dict, pd.DataFrame] | None:
    """
    Le um CSV de estacao de dentro do ZIP, separa metadados e dados.
    Retorna (meta_dict, df_horario) ou None se falhar.
    """
    try:
        with zip_obj.open(nome_arquivo) as f:
            # Le bytes e tenta UTF-8, depois Latin-1 (INMET varia)
            raw = f.read()
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                texto = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            log.warning(f"  Encoding desconhecido em {nome_arquivo}")
            return None

        linhas = texto.split("\n")
        # Localiza o cabecalho da TABELA de dados. Criterios:
        #   - comeca com "DATA" (ou variantes) seguido de ";" ou outro
        #     separador, mas nao por ":" (que indica metadado);
        #   - contem ao menos 5 separadores (cabecalho de tabela real,
        #     nao uma linha de metadado como "DATA DE FUNDACAO:;2016-...").
        idx_dados = None
        for i, linha in enumerate(linhas[:20]):
            if not re.match(r"^\s*data\b", linha, re.I):
                continue
            # rejeita metadados, que tem ":" antes do ";"
            antes_sep = linha.split(";")[0]
            if ":" in antes_sep:
                continue
            # cabecalho de tabela deve ter muitos ";"
            if linha.count(";") < 5:
                continue
            idx_dados = i
            break

        if idx_dados is None:
            log.warning(f"  Cabecalho de dados nao encontrado em {nome_arquivo}")
            return None

        meta = parsear_metadados(linhas[:idx_dados])

        # Le os dados a partir do cabecalho identificado
        buffer = io.StringIO("\n".join(linhas[idx_dados:]))
        df = pd.read_csv(
            buffer,
            sep=";",
            decimal=",",
            # -9999 e variacoes sao codigo de "sem dado" no INMET-BDMEP.
            na_values=["", " ", "-9999", "-9999.0", "-9999,0", "null", "NULL"],
            low_memory=False,
        )

        # Padroniza nomes de colunas
        mapa = mapear_colunas(df.columns.tolist())
        df = df.rename(columns=mapa)

        # Identifica as colunas de data e hora (nomes variam por ano:
        # "Data", "DATA (YYYY-MM-DD)", "Data Medicao", etc.)
        col_data = None
        col_hora = None
        for c in df.columns:
            c_low = c.lower().strip()
            if col_data is None and c_low.startswith("data"):
                col_data = c
            elif col_hora is None and c_low.startswith("hora"):
                col_hora = c

        # Filtra colunas: mantem as mapeadas + data e hora identificadas
        cols_uteis = [a for _, a in COLUNAS_MAP if a in df.columns]
        cols_uteis += [c for c in (col_data, col_hora) if c is not None]
        df = df[cols_uteis]

        # Constroi datetime a partir das colunas identificadas
        if col_data is not None and col_hora is not None:
            data_s = df[col_data].astype(str).str.strip()
            hora_s = df[col_hora].astype(str).str.strip()
            # A hora pode vir como "00:00", "0000" ou "00:00 UTC".
            # Extraimos os 4 primeiros digitos (HH e MM).
            hora_s = hora_s.str.replace(":", "", regex=False).str.slice(0, 4)
            # Pad com zeros a esquerda para garantir HHMM
            hora_s = hora_s.str.zfill(4)
            df["datetime"] = pd.to_datetime(
                data_s + " " + hora_s,
                format="%Y-%m-%d %H%M",
                errors="coerce",
            )
            # Fallback: alguns anos usam dia/mes/ano
            if df["datetime"].isna().mean() > 0.5:
                df["datetime"] = pd.to_datetime(
                    data_s + " " + hora_s,
                    dayfirst=True, errors="coerce",
                )
            df = df.drop(columns=[col_data, col_hora])

        return meta, df

    except Exception as e:  # noqa: BLE001
        log.warning(f"  Falha processando {nome_arquivo}: {e}")
        return None


# ---------------------------------------------------------------------
# Agregacao para diario e semanal
# ---------------------------------------------------------------------

def agregar_diario(df_horario: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Agrega horario -> diario por estacao."""
    if df_horario.empty or "datetime" not in df_horario.columns:
        return pd.DataFrame()
    df = df_horario.dropna(subset=["datetime"]).copy()
    df["data"] = df["datetime"].dt.date

    agg = {}
    if "precip_mm" in df.columns:    agg["precip_mm"] = "sum"
    if "temp_c" in df.columns:       agg["temp_c"]    = "mean"
    if "temp_max_c" in df.columns:   agg["temp_max_c"] = "max"
    if "temp_min_c" in df.columns:   agg["temp_min_c"] = "min"
    if "umidade_pct" in df.columns:  agg["umidade_pct"] = "mean"
    if "pressao_hpa" in df.columns:  agg["pressao_hpa"] = "mean"
    if "vento_ms" in df.columns:     agg["vento_ms"]    = "mean"

    diario = df.groupby("data", as_index=False).agg(agg)
    diario["codigo_wmo"] = meta.get("codigo_wmo", "")
    diario["uf"]         = meta.get("uf", "")
    diario["latitude"]   = meta.get("latitude")
    diario["longitude"]  = meta.get("longitude")
    diario["altitude"]   = meta.get("altitude")
    return diario


def agregar_semanal(df_diario: pd.DataFrame) -> pd.DataFrame:
    """Agrega diario -> semanal (ISO 8601)."""
    if df_diario.empty:
        return pd.DataFrame()
    df = df_diario.copy()
    df["data"] = pd.to_datetime(df["data"])
    iso = df["data"].dt.isocalendar()
    df["ano_epidem"] = iso.year.astype("Int64")
    df["sem_epidem"] = iso.week.astype("Int64")

    agg = {
        c: ("sum" if c == "precip_mm" else "mean")
        for c in df.columns if c in
        ("precip_mm", "temp_c", "temp_max_c", "temp_min_c",
         "umidade_pct", "pressao_hpa", "vento_ms")
    }
    agg["latitude"]  = "first"
    agg["longitude"] = "first"
    agg["altitude"]  = "first"

    semanal = df.groupby(
        ["codigo_wmo", "uf", "ano_epidem", "sem_epidem"],
        as_index=False,
    ).agg(agg)
    return semanal


# ---------------------------------------------------------------------
# Orquestrador
# ---------------------------------------------------------------------

def processar_zip_ano(
    zip_path: Path, ano: int, dest_root: Path,
) -> tuple[int, list[dict]]:
    """Processa o ZIP de UM ano. Retorna (n_estacoes_ok, metadados)."""
    log.info(f"[{ano}] abrindo {zip_path.name} ({zip_path.stat().st_size/1e6:.1f} MB) ...")
    metadados_estacoes: list[dict] = []
    n_ok = 0

    with zipfile.ZipFile(zip_path) as zf:
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        log.info(f"[{ano}] {len(csvs)} arquivos CSV no ZIP.")

        # Acumula por UF para gravar em lote (menos arquivos pequenos)
        por_uf_diario: dict[str, list[pd.DataFrame]] = {}
        por_uf_semanal: dict[str, list[pd.DataFrame]] = {}

        for i, nome_csv in enumerate(csvs, 1):
            resultado = processar_csv_estacao(zf, nome_csv)
            if resultado is None:
                continue
            meta, df_h = resultado
            if df_h.empty:
                continue

            uf = meta.get("uf", "??")
            df_d = agregar_diario(df_h, meta)
            df_s = agregar_semanal(df_d)
            del df_h
            if df_d.empty:
                continue

            por_uf_diario.setdefault(uf, []).append(df_d)
            por_uf_semanal.setdefault(uf, []).append(df_s)
            metadados_estacoes.append({**meta, "ano": ano})
            n_ok += 1

            if i % 100 == 0:
                log.info(f"[{ano}] {i}/{len(csvs)} estacoes lidas, {n_ok} OK.")

        # Grava por UF
        for uf, lista in por_uf_diario.items():
            df_uf = pd.concat(lista, ignore_index=True)
            dest = dest_root / "diario" / f"ano={ano}" / f"uf={uf}"
            dest.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.Table.from_pandas(df_uf, preserve_index=False),
                dest / "part-00000.parquet",
                compression="zstd", compression_level=3,
            )
            del df_uf, lista
            gc.collect()

        for uf, lista in por_uf_semanal.items():
            df_uf = pd.concat(lista, ignore_index=True)
            dest = dest_root / "semanal" / f"ano={ano}" / f"uf={uf}"
            dest.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.Table.from_pandas(df_uf, preserve_index=False),
                dest / "part-00000.parquet",
                compression="zstd", compression_level=3,
            )
            del df_uf, lista
            gc.collect()

    log.info(f"[{ano}] OK - {n_ok} estacoes processadas.")
    return n_ok, metadados_estacoes


def main() -> None:
    """Processa todos os ZIPs anuais baixados manualmente."""
    inmet_dir = cfg.raw_dir / "inmet"
    zips_dir  = inmet_dir / "zips"
    inmet_dir.mkdir(parents=True, exist_ok=True)

    if not zips_dir.exists() or not list(zips_dir.glob("*.zip")):
        log.error("=" * 70)
        log.error(" Nenhum ZIP encontrado em data/raw/inmet/zips/")
        log.error("")
        log.error(" Para coletar os dados climaticos:")
        log.error("")
        log.error("  1. Acesse: https://portal.inmet.gov.br/dadoshistoricos")
        log.error(f"  2. Baixe os arquivos ZIP de {cfg.ano_inicio} a {cfg.ano_fim}")
        log.error("     (sao 12 arquivos, ~60-120 MB cada, total ~1 GB)")
        log.error("")
        log.error(f"  3. Coloque-os em: {zips_dir}")
        log.error("     Nomes esperados: 2015.zip, 2016.zip, ..., 2026.zip")
        log.error("")
        log.error("  4. Rode novamente: python src/collect_inmet.py")
        log.error("=" * 70)
        sys.exit(1)

    todos_metadados: list[dict] = []
    falhas: list[dict] = []
    total_estacoes = 0

    for ano in range(cfg.ano_inicio, cfg.ano_fim + 1):
        zip_path = zips_dir / f"{ano}.zip"
        if not zip_path.exists():
            log.warning(f"[{ano}] ZIP nao encontrado em {zip_path} - pulando.")
            falhas.append({"ano": ano, "motivo": "ZIP ausente"})
            continue
        try:
            n_ok, metas = processar_zip_ano(zip_path, ano, inmet_dir)
            total_estacoes += n_ok
            todos_metadados.extend(metas)
        except Exception as e:  # noqa: BLE001
            log.error(f"[{ano}] FALHA: {e}")
            falhas.append({"ano": ano, "motivo": str(e)})

    # Salva metadados consolidados
    if todos_metadados:
        meta_df = pd.DataFrame(todos_metadados)
        # Mantem 1 linha por estacao (a mais recente)
        if "codigo_wmo" in meta_df.columns:
            meta_df = meta_df.sort_values("ano").drop_duplicates(
                "codigo_wmo", keep="last",
            )
        meta_df.to_parquet(
            inmet_dir / "estacoes_metadados.parquet", index=False,
        )
        log.info(f"Metadados de {len(meta_df)} estacoes salvos.")

    # Registra falhas
    if falhas:
        pd.DataFrame(falhas).to_csv(inmet_dir / "falhas.csv", index=False)
        log.warning(f"{len(falhas)} ano(s) com falha - veja {inmet_dir}/falhas.csv")

    log.info("=" * 60)
    log.info(f" Processamento concluido.")
    log.info(f" Total estacao-ano processadas: {total_estacoes:,}")
    log.info(f" Saida em: {inmet_dir}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
