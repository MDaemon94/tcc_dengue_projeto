"""
processar_vacinacao.py

Processa as planilhas baixadas do painel LocalizaSUS (Calendário Nacional /
Ocorrência) com filtro Imunobiológico = "Vacina dengue (atenuada)" e gera o
arquivo `vacinacao_municipal.csv` no formato esperado pelo pipeline do TCC.

ENTRADAS ESPERADAS:
    data/raw/pni/extracao_2024.xlsx
    data/raw/pni/extracao_2025.xlsx
    data/raw/pni/extracao_2026.xlsx   (opcional)

FORMATO DO LocalizaSUS (Tabela > Baixar Dados):
    Colunas: UF Ocorrência | Cod Mun Ocorrência | Mês Vacina | jan | fev | ... | dez
    - "Cod Mun Ocorrência" é o código IBGE de 6 dígitos (sem dígito verificador)
    - Células com "-" representam zero doses no mês
    - Cada linha = 1 município que registrou ao menos 1 dose no ano

REGRA DE NEGÓCIO:
    Se o município aparece na planilha (qualquer mês > 0), vacinou_dengue = 1.
    O LocalizaSUS já filtra municípios sem doses, então o critério é simples:
    presença na planilha => vacinou.

USO:
    python processar_vacinacao.py \
        --input-dir data/raw/pni \
        --output data/raw/pni/vacinacao_municipal.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez"]


def calcular_dv_ibge(codigo6: int) -> int:
    """Calcula o dígito verificador do código IBGE de município.

    Algoritmo oficial: pesos [1,2,1,2,1,2] aplicados aos 6 dígitos, com regra
    de "noves fora" quando o produto >= 10, e DV = (10 - (soma % 10)) % 10.
    Validado em 8 capitais (SP, RJ, BH, BSB, GYN, BSB, SSA, CWB, CGB).
    """
    pesos = [1, 2, 1, 2, 1, 2]
    s = str(codigo6).zfill(6)
    soma = 0
    for d, p in zip(s, pesos):
        prod = int(d) * p
        soma += prod if prod < 10 else (prod - 9)
    return (10 - (soma % 10)) % 10


def codigo_ibge_7(codigo6: int) -> str:
    """Converte código IBGE de 6 dígitos para 7 dígitos (com DV)."""
    dv = calcular_dv_ibge(codigo6)
    return f"{codigo6:06d}{dv}"


def carregar_extracao(caminho: Path, ano: int) -> pd.DataFrame:
    """Lê uma planilha do LocalizaSUS e devolve DataFrame com cod_ibge_7, ano, doses."""
    df = pd.read_excel(caminho)

    # Validação de colunas esperadas
    if "Cod Mun Ocorrência" not in df.columns:
        raise ValueError(
            f"Coluna 'Cod Mun Ocorrência' não encontrada em {caminho}. "
            f"Colunas disponíveis: {list(df.columns)}"
        )

    # Identifica colunas de meses presentes (2026 só tem até maio, por exemplo)
    meses_presentes = [m for m in MESES if m in df.columns]

    # "-" vira 0; converte para numérico
    for m in meses_presentes:
        df[m] = pd.to_numeric(df[m].replace("-", 0), errors="coerce").fillna(0)

    df["doses_total"] = df[meses_presentes].sum(axis=1).astype(int)

    # Filtra códigos válidos e converte para 7 dígitos
    df = df[df["Cod Mun Ocorrência"].notna()].copy()
    df["cod_ibge_7"] = df["Cod Mun Ocorrência"].astype(int).apply(codigo_ibge_7)
    df["ano"] = ano

    return df[["cod_ibge_7", "ano", "doses_total"]]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera vacinacao_municipal.csv a partir das extrações do LocalizaSUS."
    )
    parser.add_argument(
        "--input-dir", type=Path, default=Path("data/raw/pni"),
        help="Diretório com extracao_YYYY.xlsx",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/raw/pni/vacinacao_municipal.csv"),
        help="Caminho do CSV final",
    )
    parser.add_argument(
        "--anos", type=int, nargs="+", default=[2024, 2025, 2026],
        help="Anos a processar (default: 2024 2025 2026)",
    )
    args = parser.parse_args()

    frames = []
    for ano in args.anos:
        caminho = args.input_dir / f"extracao_{ano}.xlsx"
        if not caminho.exists():
            print(f"[AVISO] {caminho} não encontrado — pulando.", file=sys.stderr)
            continue
        df_ano = carregar_extracao(caminho, ano)
        print(f"[OK] {caminho.name}: {len(df_ano)} municípios.")
        frames.append(df_ano)

    if not frames:
        print("[ERRO] Nenhum arquivo carregado.", file=sys.stderr)
        return 1

    df_total = pd.concat(frames, ignore_index=True)
    # Presença na planilha = vacinou (LocalizaSUS já filtra municípios com zero)
    df_total["vacinou_dengue"] = (df_total["doses_total"] > 0).astype(int)

    df_saida = (
        df_total[df_total["vacinou_dengue"] == 1]
        [["cod_ibge_7", "ano", "vacinou_dengue"]]
        .drop_duplicates()
        .sort_values(["ano", "cod_ibge_7"])
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df_saida.to_csv(args.output, index=False)

    print("\n=== Sumário ===")
    for ano in args.anos:
        n = (df_saida["ano"] == ano).sum()
        if n:
            print(f"  {ano}: {n} municípios com vacinou_dengue=1")
    print(f"\nArquivo final: {args.output} ({len(df_saida)} linhas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
