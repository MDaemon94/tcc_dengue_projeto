"""
preprocess.py
=============

Limpeza, padronizacao e validacao dos dados brutos do SINAN.

ESTRATEGIA DE BAIXA MEMORIA:
   Le o dataset particionado (data/raw/sinan/consolidado/) UMA
   PARTICAO POR VEZ (doenca x ano), processa, e grava em outro
   dataset particionado (data/processed/sinan_limpo/). Em nenhum
   momento o consolidado inteiro precisa caber na RAM.

Etapas por particao:
1. Conversao de datas (dt_sin_pri, dt_notific, dt_obito).
2. Calculo da semana epidemiologica (padrao ISO 8601).
3. Filtro temporal 2015-2026 (defensive).
4. Validacao de codigos municipais contra tabela IBGE 2022.
5. Remocao de duplicatas dentro da particao.
6. Relatorio de completude por particao.

Saida: data/processed/sinan_limpo/doenca=X/ano=Y/part-*.parquet

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("preprocess")


COLUNAS_DATA = ["dt_notific", "dt_sin_pri", "dt_obito", "dt_digita"]
COLUNAS_ESSENCIAIS = [
    "dt_sin_pri",
    "id_mn_resi",
    "classi_fin",
    "cs_sexo",
    "nu_idade_n",
]


def carregar_municipios_ibge() -> set[str] | None:
    """Carrega os codigos IBGE de 6 digitos validos (set)."""
    munic_path = cfg.raw_dir / "ibge" / "municipios_ibge.csv"
    if not munic_path.exists():
        log.warning(f"Tabela IBGE nao encontrada em {munic_path}. "
                    "Pulando validacao de municipios.")
        return None
    mun = pd.read_csv(munic_path, dtype={"cod_ibge_6": str})
    return set(mun["cod_ibge_6"].str.zfill(6))


def converter_datas(df: pd.DataFrame) -> pd.DataFrame:
    """Converte colunas de data para datetime."""
    for col in COLUNAS_DATA:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    return df


def calcular_semana_epidem(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula semana e ano epidemiologicos (ISO 8601)."""
    if "dt_sin_pri" not in df.columns:
        return df
    iso = df["dt_sin_pri"].dt.isocalendar()
    df["sem_epidem"] = iso.week.astype("Int64")
    df["ano_epidem"] = iso.year.astype("Int64")
    return df


def filtrar_periodo(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra registros do periodo do estudo."""
    if "dt_sin_pri" not in df.columns:
        return df
    mask = df["dt_sin_pri"].between(
        f"{cfg.ano_inicio}-01-01",
        f"{cfg.ano_fim}-12-31",
    )
    return df.loc[mask].copy()


def validar_municipios(df: pd.DataFrame, validos: set[str] | None) -> pd.DataFrame:
    """Valida codigos municipais contra a tabela IBGE."""
    if validos is None or "id_mn_resi" not in df.columns:
        return df
    df["id_mn_resi"] = df["id_mn_resi"].astype(str).str.zfill(6)
    return df.loc[df["id_mn_resi"].isin(validos)].copy()


def remover_duplicatas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicatas exatas dentro da particao."""
    return df.drop_duplicates().reset_index(drop=True)


def processar_particao(
    src_parts: list[Path],
    doenca: str,
    ano: int,
    dest_root: Path,
    validos: set[str] | None,
) -> tuple[int, int]:
    """
    Processa todas as partes (.parquet) de uma particao (doenca, ano).
    Le, limpa e grava UM ARQUIVO DE SAIDA por particao (ou varios se
    o tamanho exigir).

    Retorna (n_in, n_out): registros lidos e gravados.
    """
    dest_dir = dest_root / f"doenca={doenca}" / f"ano={ano}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for antigo in dest_dir.glob("part-*.parquet"):
        antigo.unlink()

    n_in = 0
    n_out = 0
    partes_saida: list[pa.Table] = []
    tamanho_acumulado = 0
    LIMITE_GRAVACAO = 300_000  # linhas por arquivo de saida

    n_part_saida = 0
    for arq in src_parts:
        pf = pq.ParquetFile(arq)
        for batch in pf.iter_batches(batch_size=200_000):
            df = batch.to_pandas()
            n_in += len(df)

            # Marca a doenca/ano (a particao do diretorio se perde no batch)
            df["doenca"] = doenca

            df = converter_datas(df)
            df = calcular_semana_epidem(df)
            df = filtrar_periodo(df)
            df = validar_municipios(df, validos)
            df = remover_duplicatas(df)

            if df.empty:
                continue

            tabela = pa.Table.from_pandas(df, preserve_index=False)
            partes_saida.append(tabela)
            tamanho_acumulado += tabela.num_rows
            n_out += tabela.num_rows

            del df, batch
            gc.collect()

            # Descarrega se passou do limite
            if tamanho_acumulado >= LIMITE_GRAVACAO:
                combinada = pa.concat_tables(partes_saida, promote_options="default")
                pq.write_table(
                    combinada,
                    dest_dir / f"part-{n_part_saida:05d}.parquet",
                    compression="zstd",
                    compression_level=3,
                )
                partes_saida.clear()
                tamanho_acumulado = 0
                n_part_saida += 1
                del combinada
                gc.collect()

    # Grava o resto
    if partes_saida:
        combinada = pa.concat_tables(partes_saida, promote_options="default")
        pq.write_table(
            combinada,
            dest_dir / f"part-{n_part_saida:05d}.parquet",
            compression="zstd",
            compression_level=3,
        )
        del combinada
        gc.collect()

    return n_in, n_out


def main() -> None:
    src_root  = cfg.raw_dir / "sinan" / "consolidado"
    dest_root = cfg.processed_dir / "sinan_limpo"

    if not src_root.exists():
        log.error(f"Dataset bruto nao encontrado em {src_root}. "
                  "Execute antes: python src/collect_sinan.py")
        return

    dest_root.mkdir(parents=True, exist_ok=True)
    validos = carregar_municipios_ibge()

    total_in = 0
    total_out = 0

    for doenca in [cfg.doenca_principal, *cfg.arboviroses_exploratorias]:
        for ano in range(cfg.ano_inicio, cfg.ano_fim + 1):
            src_dir = src_root / f"doenca={doenca}" / f"ano={ano}"
            if not src_dir.exists():
                continue
            partes = sorted(src_dir.glob("part-*.parquet"))
            if not partes:
                continue

            log.info(f"[{doenca}/{ano}] processando {len(partes)} partes ...")
            n_in, n_out = processar_particao(
                partes, doenca, ano, dest_root, validos,
            )
            total_in += n_in
            total_out += n_out
            log.info(f"[{doenca}/{ano}] OK - lidos {n_in:,}, "
                     f"gravados {n_out:,} ({100*n_out/max(n_in,1):.1f}%)")
            gc.collect()

    log.info("=" * 60)
    log.info(f"Pre-processamento concluido.")
    log.info(f"  Total lido:   {total_in:,}")
    log.info(f"  Total saida:  {total_out:,} ({100*total_out/max(total_in,1):.1f}%)")
    log.info(f"  Saida em:     {dest_root}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
