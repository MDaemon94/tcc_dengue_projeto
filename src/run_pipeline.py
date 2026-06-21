"""
run_pipeline.py
===============

Pipeline orquestrador — executa as etapas do projeto em ordem:

1. (opcional) gera dados sintéticos APENAS se solicitado
   explicitamente via --permitir-sintetico;
2. valida se a tabela integrada representa dados reais;
3. análise exploratória (EDA);
4. decomposição STL;
5. análise de correlação;
6. análise geoespacial (Moran I, DBSCAN);
7. engenharia de features;
8. treinamento e avaliação dos modelos preditivos;
9. previsão univariada com Prophet;
10. figuras conceituais.

Para coleta real, execute antes:
    python src/collect_sinan.py
    python src/collect_inmet.py
    python src/collect_ibge_pni.py
    python src/preprocess.py
    python src/build_clima_municipal.py
    python src/integrate.py

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("pipeline")


ETAPAS = [
    ("EDA",                 "eda"),
    ("STL",                 "stl_analysis"),
    ("Correlação",          "correlation_analysis"),
    ("Geoespacial",         "spatial_analysis"),
    ("Features",            "features"),
    ("Modelos preditivos",  "train_models"),
    ("Prophet",             "prophet_forecast"),
    ("Figuras conceituais", "make_concept_figures"),
]


def garantir_dados(permitir_sintetico: bool = False) -> None:
    """Garante existência de uma tabela integrada (real ou sintética).

    Por padrão, NÃO gera dados sintéticos automaticamente: isso evita que
    resultados oficiais sejam produzidos a partir de dados fictícios sem
    o autor perceber. Use --permitir-sintetico para gerar de propósito.
    """
    real  = cfg.processed_dir / f"dados_integrados_{cfg.ano_inicio}_{cfg.ano_fim}.parquet"
    synth = cfg.processed_dir / "dados_integrados_sinteticos.parquet"
    if real.exists() or synth.exists():
        return
    if not permitir_sintetico:
        raise FileNotFoundError(
            "Nenhuma tabela integrada REAL encontrada em "
            f"{cfg.processed_dir}.\n"
            "Rode a coleta/integração real antes:\n"
            "  python src/build_clima_municipal.py && python src/integrate.py\n"
            "Ou, para fins de demonstração apenas, rode:\n"
            "  python src/run_pipeline.py --permitir-sintetico"
        )
    log.warning("Gerando dados SINTÉTICOS (modo demonstração, --permitir-sintetico).")
    import generate_synthetic_data
    generate_synthetic_data.main()


def main(permitir_sintetico: bool = False) -> None:
    log.info("=" * 60)
    log.info(" PIPELINE TCC – DENGUE BRASIL ")
    log.info("=" * 60)

    garantir_dados(permitir_sintetico=permitir_sintetico)

    # Trava: valida se os dados sao reais antes de produzir resultados oficiais.
    # Em modo demonstracao (--permitir-sintetico) a validacao apenas avisa.
    from eda import carregar_dados
    from validate_real_data import validar_dataset_real
    df_check = carregar_dados()
    validar_dataset_real(df_check, abortar=not permitir_sintetico)
    del df_check

    for nome, modulo in ETAPAS:
        log.info("─" * 60)
        log.info(f" Etapa: {nome}")
        log.info("─" * 60)
        try:
            mod = __import__(modulo)
            if hasattr(mod, "main"):
                mod.main()
            else:
                log.warning(f"Módulo {modulo} sem função main().")
        except Exception as e:  # noqa: BLE001
            log.error(f"ERRO em {nome}: {e}")
            log.debug(traceback.format_exc())

    log.info("=" * 60)
    log.info(" PIPELINE CONCLUÍDO ")
    log.info("=" * 60)
    log.info(f"Figuras em: {cfg.figures_dir}")
    log.info(f"Saídas em:  {cfg.outputs_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline analítico do TCC (dengue).")
    parser.add_argument(
        "--permitir-sintetico",
        action="store_true",
        help="Permite gerar/usar dados sintéticos (apenas demonstração; "
             "NÃO use para os resultados oficiais do TCC).",
    )
    args = parser.parse_args()
    main(permitir_sintetico=args.permitir_sintetico)