"""
validate_real_data.py
======================

Trava de seguranca: valida se a tabela integrada carregada
representa os MICRODADOS REAIS do DATASUS — e nao o dataset
sintetico de demonstracao ou um arquivo corrompido.

Motivacao
---------
O `run_pipeline.py` gera dados sinteticos automaticamente quando
nao encontra a tabela real, e o loader os carrega de forma
silenciosa. Sem esta trava, resultados oficiais podem ser
produzidos a partir de dados ficticios sem que o autor perceba
(ex.: 200 municipios, incidencia > 100.000/100k, regioes
inconsistentes com o codigo IBGE).

Uso
---
    from validate_real_data import validar_dataset_real
    validar_dataset_real(df)            # levanta ValueError se suspeito
    validar_dataset_real(df, abortar=False)  # apenas retorna o relatorio

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

log = logging.getLogger("validate")

# Limiares de plausibilidade (Brasil real)
MIN_MUNICIPIOS = 5_000          # real ~5.570; sintetico ~200
TETO_INCIDENCIA_SEMANAL = 100_000  # impossivel ultrapassar (toda a populacao)
REGIOES_VALIDAS = {"Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"}

# Mapa oficial: 1o digito do codigo IBGE -> regiao
PREFIXO2REGIAO = {
    "1": "Norte", "2": "Nordeste", "3": "Sudeste",
    "4": "Sul", "5": "Centro-Oeste",
}


@dataclass
class Relatorio:
    problemas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problemas


def validar_dataset_real(df: pd.DataFrame, abortar: bool = True) -> Relatorio:
    """
    Verifica indicadores de que `df` sao os dados reais do DATASUS.
    Se `abortar=True` e houver problemas, levanta ValueError.
    """
    rel = Relatorio()

    # 1. Numero de municipios distintos
    if "cod_ibge_7" in df.columns:
        n_mun = df["cod_ibge_7"].nunique()
        if n_mun < MIN_MUNICIPIOS:
            rel.problemas.append(
                f"Apenas {n_mun} municipios distintos (esperado ~5.570). "
                f"Indica dataset SINTETICO ou incompleto."
            )
    else:
        rel.problemas.append("Coluna 'cod_ibge_7' ausente.")

    # 2. Coluna regiao presente, valida e coerente com o codigo IBGE
    if "regiao" not in df.columns:
        rel.problemas.append("Coluna 'regiao' ausente.")
    else:
        invalidas = set(df["regiao"].dropna().unique()) - REGIOES_VALIDAS
        if invalidas:
            rel.problemas.append(f"Valores de 'regiao' invalidos: {invalidas}.")
        if "cod_ibge_7" in df.columns:
            amostra = df[["cod_ibge_7", "regiao"]].dropna().drop_duplicates().head(5000)
            esperado = amostra["cod_ibge_7"].astype(str).str[0].map(PREFIXO2REGIAO)
            inconsist = (amostra["regiao"].values != esperado.values).mean()
            if inconsist > 0.05:
                rel.problemas.append(
                    f"{inconsist*100:.1f}% das linhas tem 'regiao' incoerente com o "
                    f"prefixo do codigo IBGE (ex.: codigo 11xxxxx rotulado fora de Norte). "
                    f"Indica dado sintetico ou merge geografico errado."
                )

    # 3. Faixa de incidencia plausivel (semanal por municipio)
    if "tx_incidencia" in df.columns:
        tx_max = df["tx_incidencia"].max()
        if tx_max > TETO_INCIDENCIA_SEMANAL:
            rel.problemas.append(
                f"tx_incidencia maxima = {tx_max:,.0f}/100k (> {TETO_INCIDENCIA_SEMANAL:,}), "
                f"fisicamente impossivel. Verifique casos/populacao e o ano da populacao."
            )

    # 4. Colunas climaticas e socioeconomicas preenchidas (necessarias p/ Tab.4 e modelos)
    for col, rotulo in [
        ("precipitacao", "clima (precipitacao)"),
        ("temp_media",   "clima (temperatura)"),
        ("idhm",         "socioeconomico (IDHM)"),
        ("dens_demo",    "socioeconomico (densidade)"),
    ]:
        if col not in df.columns:
            rel.avisos.append(f"Coluna '{col}' [{rotulo}] AUSENTE — analises dependentes ficarao vazias.")
        elif df[col].notna().mean() < 0.10:
            rel.avisos.append(
                f"Coluna '{col}' [{rotulo}] {df[col].notna().mean()*100:.1f}% preenchida "
                f"(<10%) — Tabela 4 / features podem sair vazias."
            )

    # 5. Volume total de notificacoes de dengue (real ~24,5 milhoes)
    if "doenca" in df.columns and "casos" in df.columns:
        total_dengue = int(df.loc[df["doenca"] == "dengue", "casos"].sum())
        if total_dengue < 5_000_000:
            rel.avisos.append(
                f"Total de casos de dengue = {total_dengue:,} (esperado ~24,5 milhoes). "
                f"Confirme se o recorte 2015-2026 esta completo."
            )

    # Relatorio
    for p in rel.problemas:
        log.error(f"[FALHA] {p}")
    for a in rel.avisos:
        log.warning(f"[AVISO] {a}")
    if rel.ok:
        log.info("[OK] Dataset compativel com os microdados reais do DATASUS.")

    if abortar and not rel.ok:
        raise ValueError(
            "Validacao de dados REAIS falhou. O pipeline foi interrompido para "
            "evitar gerar resultados oficiais a partir de dados sinteticos ou "
            "corrompidos. Corrija as fontes (rode collect_ibge_pni.py / integrate.py) "
            "ou rode com --permitir-sintetico para fins de demonstracao.\n  - "
            + "\n  - ".join(rel.problemas)
        )
    return rel


def main() -> None:
    """Permite rodar a validacao isoladamente: python src/validate_real_data.py"""
    from eda import carregar_dados
    df = carregar_dados()
    rel = validar_dataset_real(df, abortar=False)
    print("\n=== RESULTADO DA VALIDACAO ===")
    print("Status:", "APROVADO (dados reais)" if rel.ok else "REPROVADO (dados suspeitos)")
    if rel.problemas:
        print("\nProblemas (bloqueiam o pipeline):")
        for p in rel.problemas:
            print("  -", p)
    if rel.avisos:
        print("\nAvisos (nao bloqueiam, mas degradam resultados):")
        for a in rel.avisos:
            print("  -", a)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
    main()
