"""
config.py
=========

Módulo de configuração centralizada do pipeline de análise epidemiológica
de dengue no Brasil (2015–2026).

Define caminhos, parâmetros temporais e códigos das doenças/sistemas
de notificação utilizados ao longo do projeto.

Autor : Murillo Daemon Neto
Data  : 2026
TCC   : Ciência de dados aplicada à dengue no Brasil
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Config:
    """Configurações centralizadas do projeto."""

    # ── Diretórios ───────────────────────────────────────────────
    project_root: Path = PROJECT_ROOT
    raw_dir:      Path = PROJECT_ROOT / "data" / "raw"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    geo_dir:      Path = PROJECT_ROOT / "data" / "geo"
    outputs_dir:  Path = PROJECT_ROOT / "outputs"
    figures_dir:  Path = PROJECT_ROOT / "figures"
    models_dir:   Path = PROJECT_ROOT / "models"

    # ── Recorte temporal ─────────────────────────────────────────
    # Estendido para incluir a maior epidemia da história (2024)
    # e os dados parciais de 2025 e 2026.
    ano_inicio: int = 2015
    ano_fim:    int = 2026

    # ── Doença principal do estudo ──────────────────────────────
    # O escopo do TCC foi reduzido para DENGUE, doença para a
    # qual há cobertura analítica completa (correlação, modelos
    # preditivos e validação). Zika e chikungunya entram apenas
    # como análise exploratória/descritiva auxiliar.
    doenca_principal: str = "dengue"
    arboviroses_exploratorias: tuple[str, ...] = ("zika", "chikungunya")

    # ── Códigos SINAN/DATASUS ───────────────────────────────────
    sinan_codigos: dict = field(default_factory=lambda: {
        "DENG": "dengue",
        "ZIKA": "zika",
        "CHIK": "chikungunya",
    })

    # ── URLs públicas (referência) ───────────────────────────────
    url_pysus_docs:   str = "https://pysus.readthedocs.io"
    url_datasus_ftp:  str = "ftp://ftp.datasus.gov.br/dissemin/publicos/SINAN/DADOS/FINAIS/"
    url_inmet_bdmep:  str = "https://bdmep.inmet.gov.br"
    url_ibge_censo:   str = "https://www.ibge.gov.br/estatisticas/sociais/populacao/22827-censo-demografico-2022.html"
    url_pni_vacinas:  str = "https://opendatasus.saude.gov.br"

    # ── Parâmetros de modelagem ─────────────────────────────────
    horizonte_previsao: int = 4  # semanas à frente
    n_lags_casos:       int = 8
    n_lags_clima:       int = 4
    random_state:       int = 42

    def __post_init__(self) -> None:
        """Garante existência dos diretórios do projeto."""
        for d in [
            self.raw_dir,
            self.processed_dir,
            self.geo_dir,
            self.outputs_dir,
            self.figures_dir,
            self.models_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


cfg = Config()


if __name__ == "__main__":
    # Sanity check: imprime as configurações do projeto.
    print("─" * 60)
    print(" Configuração do projeto — TCC Dengue Brasil ")
    print("─" * 60)
    print(f"Raiz do projeto      : {cfg.project_root}")
    print(f"Recorte temporal     : {cfg.ano_inicio}–{cfg.ano_fim}")
    print(f"Doença principal     : {cfg.doenca_principal}")
    print(f"Arboviroses (EDA)    : {cfg.arboviroses_exploratorias}")
    print(f"Horizonte previsão   : {cfg.horizonte_previsao} semanas")
    print(f"Lags de casos        : {cfg.n_lags_casos}")
    print(f"Diretórios criados   : ok")
