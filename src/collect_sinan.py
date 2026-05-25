"""
collect_sinan.py
================

Coleta automatizada dos microdados do SINAN (Sistema de Informação de
Agravos de Notificação) para dengue, Zika e chikungunya, no período
2015-2026, utilizando a biblioteca PySUS (FIOCRUZ/IComp).

Estratégia para evitar OOM (out-of-memory) em máquinas com 8-16 GB:

  1. PySUS já baixa cada ano como uma PASTA com vários parquets
     pequenos (ParquetSet). NAO chamamos `.to_dataframe()` — isso
     carregaria o ano inteiro de uma vez (a base de dengue de 2024
     tem ~6,5M registros e ~5 GB em RAM, suficiente para travar o WSL).
  2. Em vez disso, abrimos o ParquetSet com `pyarrow.parquet.ParquetFile`
     e ITERAMOS sobre os RowGroups (batches), processando um lote por
     vez. Cada batch e tipicamente < 200 MB em RAM.
  3. Em cada batch:
        a) selecionamos APENAS as colunas relevantes (~15 de ~120);
        b) gravamos o batch direto em um dataset particionado por
           doenca/ano no disco (Parquet, codec zstd).
  4. O "consolidado" NAO e um unico parquet gigante (Parquet nao
     suporta append nativo de forma estavel). E um DATASET PARTICIONADO
     em `data/raw/sinan/consolidado/doenca=X/ano=Y/part-*.parquet`,
     que o pandas/pyarrow le transparentemente com `pd.read_parquet`
     e que pode ser consultado com filtros sem carregar tudo na memoria.

Documentacao do PySUS:
    https://pysus.readthedocs.io
DATASUS-SINAN:
    https://datasus.saude.gov.br/transferencia-de-arquivos/

Requisitos:
    pip install pysus pandas pyarrow

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import gc
import logging
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

try:
    from pysus.online_data import SINAN
except ImportError:
    print(
        "ERRO: a biblioteca 'pysus' nao esta instalada.\n"
        "Instale com:  pip install pysus",
        file=sys.stderr,
    )
    raise

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("collect_sinan")


# Mapeamento doenca -> codigo PySUS
DOENCA2COD = {
    "dengue":      "DENG",
    "zika":        "ZIKA",
    "chikungunya": "CHIK",
}

# Colunas relevantes para o TCC
# O SINAN bruto tem ~120 colunas; conservar todas estoura a RAM e o
# disco. Trazemos so o essencial para a analise epidemiologica.
COLUNAS_RELEVANTES = [
    "DT_NOTIFIC",    # data de notificacao
    "DT_SIN_PRI",    # data do inicio dos sintomas (chave temporal)
    "SEM_NOT",       # semana epidemiologica de notificacao
    "SEM_PRI",       # semana epidemiologica do inicio dos sintomas
    "NU_ANO",        # ano da notificacao
    "SG_UF_NOT",     # UF da notificacao
    "ID_MUNICIP",    # municipio de notificacao
    "ID_MN_RESI",    # municipio de residencia (chave geografica)
    "SG_UF",         # UF de residencia
    "CS_SEXO",       # sexo
    "NU_IDADE_N",    # idade codificada
    "CS_RACA",       # raca/cor
    "CS_ESCOL_N",    # escolaridade
    "CLASSI_FIN",    # classificacao final (confirmado/descartado)
    "CRITERIO",      # criterio de confirmacao (lab/clinico)
    "EVOLUCAO",      # evolucao (cura/obito)
    "DT_OBITO",      # data do obito (se houver)
    "SOROTIPO",      # sorotipo viral (DENV-1, -2, -3, -4)
    "DT_DIGITA",     # data de digitacao no sistema
]

# Tamanho do batch processado em RAM por vez (linhas).
# 200k linhas x ~20 colunas string ~= 80 MB - seguro em qualquer maquina.
BATCH_SIZE = 200_000


def localizar_parquetset(retorno_pysus) -> Path | None:
    """
    O PySUS pode retornar: (a) um ParquetSet com atributo `.path`,
    (b) uma lista deles, ou (c) um pd.DataFrame em versoes antigas.

    Esta funcao extrai o caminho da pasta parquet no disco.
    Retorna None se nao for possivel (fallback adiante).
    """
    if isinstance(retorno_pysus, list) and retorno_pysus:
        retorno_pysus = retorno_pysus[0]

    for attr in ("path", "_path", "parquet_dir"):
        if hasattr(retorno_pysus, attr):
            p = Path(getattr(retorno_pysus, attr))
            if p.exists():
                return p

    return None


def coletar_um(doenca: str, ano: int, dataset_root: Path) -> int:
    """
    Baixa SINAN de (doenca, ano) e grava em dataset particionado.
    Retorna o numero total de registros gravados.
    """
    cod = DOENCA2COD[doenca]
    log.info(f"[{doenca}/{ano}] baixando via PySUS ...")

    retorno = SINAN.download(cod, ano)
    parquet_dir = localizar_parquetset(retorno)

    # Caminho moderno: streaming dos parquets do disco
    if parquet_dir is not None:
        log.info(f"[{doenca}/{ano}] lendo {parquet_dir} em batches ...")
        return _gravar_em_batches(parquet_dir, doenca, ano, dataset_root)

    # Fallback: PySUS retornou DataFrame em memoria
    log.warning(f"[{doenca}/{ano}] fallback: PySUS devolveu DataFrame; "
                "uso de memoria pode ser alto.")
    df = retorno if hasattr(retorno, "to_parquet") else retorno.to_dataframe()
    n = _gravar_dataframe(df, doenca, ano, dataset_root)
    del df
    gc.collect()
    return n


def _gravar_em_batches(
    parquet_dir: Path, doenca: str, ano: int, dataset_root: Path,
) -> int:
    """
    Le o ParquetSet do PySUS em batches e grava cada batch como uma
    parte do dataset particionado de destino. Nunca carrega o ano
    inteiro em RAM.
    """
    arquivos = sorted(parquet_dir.glob("*.parquet"))
    if not arquivos:
        arquivos = sorted(parquet_dir.rglob("*.parquet"))
    if not arquivos:
        log.warning(f"[{doenca}/{ano}] nenhum .parquet em {parquet_dir}.")
        return 0

    # Descobre intersecao entre colunas relevantes e colunas existentes
    schema_amostra = pq.read_schema(arquivos[0])
    cols_disponiveis = set(schema_amostra.names)
    colunas_usar = [c for c in COLUNAS_RELEVANTES if c in cols_disponiveis]
    if not colunas_usar:
        colunas_usar = None  # schema imprevisto: le tudo (raro)

    pasta_destino = dataset_root / f"doenca={doenca}" / f"ano={ano}"
    pasta_destino.mkdir(parents=True, exist_ok=True)

    # Limpa partes antigas dessa particao (re-run idempotente)
    for antigo in pasta_destino.glob("part-*.parquet"):
        antigo.unlink()

    total = 0
    n_part = 0
    for arq in arquivos:
        pf = pq.ParquetFile(arq)
        for batch in pf.iter_batches(batch_size=BATCH_SIZE,
                                     columns=colunas_usar):
            tabela = pa.Table.from_batches([batch])
            tabela = _padronizar_tabela(tabela)
            destino = pasta_destino / f"part-{n_part:05d}.parquet"
            pq.write_table(
                tabela, destino,
                compression="zstd",
                compression_level=3,
                use_dictionary=True,
            )
            total += tabela.num_rows
            n_part += 1
            del tabela, batch
            gc.collect()

    log.info(f"[{doenca}/{ano}] OK - {total:,} registros em {n_part} partes.")
    return total


def _padronizar_tabela(tab: pa.Table) -> pa.Table:
    """Renomeia colunas para snake_case minusculo."""
    novos = [c.lower().strip() for c in tab.column_names]
    return tab.rename_columns(novos)


def _gravar_dataframe(df, doenca: str, ano: int, dataset_root: Path) -> int:
    """Fallback: grava um DataFrame inteiro em uma particao."""
    if df is None or len(df) == 0:
        return 0
    df.columns = [c.lower().strip() for c in df.columns]
    cols_usar = [c for c in (x.lower() for x in COLUNAS_RELEVANTES)
                 if c in df.columns]
    if cols_usar:
        df = df[cols_usar]
    tabela = pa.Table.from_pandas(df, preserve_index=False)
    pasta_destino = dataset_root / f"doenca={doenca}" / f"ano={ano}"
    pasta_destino.mkdir(parents=True, exist_ok=True)
    for antigo in pasta_destino.glob("part-*.parquet"):
        antigo.unlink()
    pq.write_table(tabela, pasta_destino / "part-00000.parquet",
                   compression="zstd", compression_level=3)
    return len(df)


def coletar_todos() -> None:
    """Coleta SINAN para todas as doencas e anos do recorte."""
    dataset_root = cfg.raw_dir / "sinan" / "consolidado"
    dataset_root.mkdir(parents=True, exist_ok=True)

    log.info(f"Dataset particionado de destino: {dataset_root}")

    total_geral = 0
    for doenca in [cfg.doenca_principal, *cfg.arboviroses_exploratorias]:
        for ano in range(cfg.ano_inicio, cfg.ano_fim + 1):
            try:
                n = coletar_um(doenca, ano, dataset_root)
                total_geral += n
            except Exception as e:  # noqa: BLE001
                log.warning(f"[{doenca}/{ano}] FALHA: {e}")
            finally:
                gc.collect()

    log.info("=" * 60)
    log.info(f" Coleta concluida - {total_geral:,} registros gravados.")
    log.info(f" Para ler todo o consolidado:")
    log.info(f"   import pandas as pd")
    log.info(f"   df = pd.read_parquet('{dataset_root}')")
    log.info(f" Para ler so dengue/2024 (sem carregar o resto):")
    log.info(f"   df = pd.read_parquet(")
    log.info(f"       '{dataset_root}',")
    log.info(f"       filters=[('doenca','=','dengue'),('ano','=',2024)])")
    log.info("=" * 60)


if __name__ == "__main__":
    coletar_todos()
