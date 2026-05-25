"""
check_data.py
=============

Verifica se todas as fontes de dados necessarias estao presentes
e em estado utilizavel ANTES de rodar o pipeline analitico.

Lista cada dataset e indica:
  [OK]      - presente e valido
  [AUSENTE] - precisa ser baixado/coletado
  [PARCIAL] - presente mas com problemas

Como rodar:
    python src/check_data.py

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import sys
from pathlib import Path

from config import cfg


VERDE   = "\033[92m"
AMARELO = "\033[93m"
VERMELHO = "\033[91m"
RESET   = "\033[0m"


def status(ok: bool, parcial: bool = False) -> str:
    if ok:
        return f"{VERDE}[ OK     ]{RESET}"
    if parcial:
        return f"{AMARELO}[ PARCIAL]{RESET}"
    return f"{VERMELHO}[ AUSENTE]{RESET}"


def check_sinan() -> tuple[bool, str]:
    root = cfg.raw_dir / "sinan" / "consolidado"
    if not root.exists():
        return False, "Rode: python src/collect_sinan.py"
    particoes = list(root.glob("doenca=*/ano=*"))
    if not particoes:
        return False, "Diretorio existe mas sem particoes. Re-rode collect_sinan.py"
    n_dengue = len(list(root.glob("doenca=dengue/ano=*/part-*.parquet")))
    if n_dengue < 5:
        return False, f"Apenas {n_dengue} arquivos de dengue. Esperado >= 12 anos."
    return True, f"{len(particoes)} particoes encontradas"


def check_inmet_zips() -> tuple[bool, str]:
    zips_dir = cfg.raw_dir / "inmet" / "zips"
    if not zips_dir.exists():
        return False, ("Crie a pasta e baixe os ZIPs anuais em\n"
                       "    https://portal.inmet.gov.br/dadoshistoricos")
    zips = list(zips_dir.glob("*.zip"))
    esperado = cfg.ano_fim - cfg.ano_inicio + 1
    if len(zips) < esperado:
        anos_presentes = {int(z.stem) for z in zips if z.stem.isdigit()}
        anos_faltantes = sorted(
            set(range(cfg.ano_inicio, cfg.ano_fim + 1)) - anos_presentes
        )
        return False, f"{len(zips)}/{esperado} ZIPs. Faltando: {anos_faltantes}"
    return True, f"{len(zips)} ZIPs presentes"


def check_inmet_processado() -> tuple[bool, str]:
    proc = cfg.raw_dir / "inmet" / "semanal"
    if not proc.exists():
        return False, "Rode: python src/collect_inmet.py"
    parquets = list(proc.glob("ano=*/uf=*/part*.parquet"))
    if not parquets:
        return False, "Nenhum parquet de saida. Re-rode collect_inmet.py"
    return True, f"{len(parquets)} parquets processados"


def check_arquivo(caminho: Path, descricao: str,
                  fonte: str, secao_docs: str,
                  tam_minimo_kb: int = 5) -> tuple[bool, str]:
    if not caminho.exists():
        return False, f"Baixe de {fonte}\n              Ver DATASETS.md {secao_docs}"
    tam_kb = caminho.stat().st_size / 1024
    if tam_kb < tam_minimo_kb:
        return False, f"Arquivo presente mas muito pequeno ({tam_kb:.1f} KB)."
    return True, f"{tam_kb:.1f} KB"


def check_idhm() -> tuple[bool, str]:
    """Procura idhm_municipal.xlsx ou .csv ou qualquer data*.xlsx."""
    base = cfg.raw_dir / "ibge"
    candidatos = [
        base / "idhm_municipal.xlsx",
        base / "idhm_municipal.csv",
        base / "data.xlsx",
    ] + list(base.glob("*idhm*.xlsx")) + list(base.glob("data*.xlsx"))
    encontrado = next((c for c in candidatos if c.exists()), None)
    if encontrado is None:
        return False, ("Baixe de atlasbrasil.org.br/consulta/planilha\n"
                       "              Ver DATASETS.md secao 3.3")
    tam_kb = encontrado.stat().st_size / 1024
    return True, f"{encontrado.name} ({tam_kb:.1f} KB)"


def check_saneamento() -> tuple[bool, str]:
    """Procura saneamento_municipal.xlsx ou .csv."""
    base = cfg.raw_dir / "ibge"
    candidatos = [
        base / "saneamento_municipal.xlsx",
        base / "saneamento_municipal.csv",
    ] + list(base.glob("*saneamento*.xlsx"))
    encontrado = next((c for c in candidatos if c.exists()), None)
    if encontrado is None:
        return False, ("Baixe de atlasbrasil.org.br/consulta/planilha\n"
                       "              (4 indicadores de saneamento 2010)\n"
                       "              Ver DATASETS.md secao 3.4")
    tam_kb = encontrado.stat().st_size / 1024
    return True, f"{encontrado.name} ({tam_kb:.1f} KB)"


def main() -> int:
    print("=" * 78)
    print(" VERIFICACAO DE DADOS - TCC Dengue Brasil ")
    print("=" * 78)

    checks = [
        # (nome, funcao, eh_obrigatorio)
        ("SINAN (coleta automatica)",      check_sinan, True),
        ("INMET (ZIPs manuais)",           check_inmet_zips, True),
        ("INMET (processado)",             check_inmet_processado, False),
        ("IBGE - municipios",
         lambda: check_arquivo(
             cfg.raw_dir / "ibge" / "municipios_ibge.csv",
             "municipios IBGE",
             "API IBGE (automatico)",
             "secao 3.1", tam_minimo_kb=200,
         ), True),
        ("IBGE - populacao",
         lambda: check_arquivo(
             cfg.raw_dir / "ibge" / "populacao_municipal.csv",
             "populacao municipal",
             "API IBGE (automatico)",
             "secao 3.2", tam_minimo_kb=200,
         ), True),
        ("IDHM (Atlas Brasil 2010)",
         lambda: check_idhm(), False),
        ("Saneamento (Censo 2010)",
         lambda: check_saneamento(), False),
        ("Vacinacao dengue (lista)",
         lambda: check_arquivo(
             cfg.raw_dir / "pni" / "vacinacao_municipal.csv",
             "lista de municipios da campanha",
             "Informe Tecnico MS 2024",
             "secao 4", tam_minimo_kb=5,
         ), False),
    ]

    n_ok = n_faltantes = n_obrigatorios_faltantes = 0
    for nome, fn, obrigatorio in checks:
        try:
            ok, msg = fn()
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"ERRO: {e}"

        marca = "*" if obrigatorio else " "
        print(f"  {status(ok)} {marca} {nome:<35} {msg}")
        if ok:
            n_ok += 1
        else:
            n_faltantes += 1
            if obrigatorio:
                n_obrigatorios_faltantes += 1

    print("=" * 78)
    print(f"  Total: {n_ok} OK, {n_faltantes} faltantes "
          f"({n_obrigatorios_faltantes} obrigatorios)")
    print("  (* = obrigatorio para o pipeline rodar)")
    print("=" * 78)

    if n_obrigatorios_faltantes > 0:
        print(f"\n{VERMELHO}Pipeline NAO pode rodar: existem datasets obrigatorios faltando.{RESET}")
        return 1
    if n_faltantes > 0:
        print(f"\n{AMARELO}Pipeline pode rodar com dados parciais. "
              f"Variaveis dos datasets faltantes serao tratadas como NaN.{RESET}")
        return 0
    print(f"\n{VERDE}Tudo pronto! Pode rodar: python src/run_pipeline.py{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
