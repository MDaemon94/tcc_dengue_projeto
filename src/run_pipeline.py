"""
run_pipeline.py
===============

Pipeline orquestrador — executa as etapas do projeto em ordem:

1. (opcional) gera dados sintéticos se a tabela integrada
   ainda não existir;
2. análise exploratória (EDA);
3. decomposição STL;
4. análise de correlação;
5. análise geoespacial (Moran I, DBSCAN);
6. engenharia de features;
7. treinamento e avaliação dos modelos preditivos;
8. previsão univariada com Prophet.

Para coleta real, execute antes:
    python src/collect_sinan.py
    python src/collect_inmet.py
    python src/collect_ibge_pni.py
    python src/preprocess.py
    python src/integrate.py

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

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
    ("EDA",               "eda"),
    ("STL",               "stl_analysis"),
    ("Correlação",        "correlation_analysis"),
    ("Geoespacial",       "spatial_analysis"),
    ("Features",          "features"),
    ("Modelos preditivos", "train_models"),
    ("Prophet",           "prophet_forecast"),
    ("Figuras conceituais", "make_concept_figures"),
]


def garantir_dados() -> None:
    """Garante existência de uma tabela integrada (real ou sintética)."""
    real  = cfg.processed_dir / f"dados_integrados_{cfg.ano_inicio}_{cfg.ano_fim}.parquet"
    synth = cfg.processed_dir / "dados_integrados_sinteticos.parquet"
    if real.exists() or synth.exists():
        return
    log.warning("Nenhuma tabela integrada encontrada — gerando dados sintéticos.")
    import generate_synthetic_data
    generate_synthetic_data.main()


def main() -> None:
    log.info("=" * 60)
    log.info(" PIPELINE TCC – DENGUE BRASIL ")
    log.info("=" * 60)

    garantir_dados()

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
    main()
