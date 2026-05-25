"""
make_concept_figures.py
=======================

Gera as figuras CONCEITUAIS (esquemas e diagramas) do TCC:

- Figura 1 — Fluxo metodológico geral da pesquisa.
- Figura 2 — Arquitetura do pipeline de coleta e integração.
- Figura 3 — Estrutura das bases SINAN, INMET e IBGE.

Essas figuras são esquemas em matplotlib (sem dados).

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

from config import cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("concept")


# Cores padronizadas
COR_AZUL  = "#1976D2"
COR_VERDE = "#2E7D32"
COR_AMARELO = "#F9A825"
COR_LARANJA = "#EF6C00"
COR_CINZA = "#546E7A"


def caixa(ax, x, y, w, h, texto, cor, cor_texto="white", fontsize=10):
    """Desenha uma caixa retangular com texto centralizado."""
    rect = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.1",
        facecolor=cor, edgecolor="black", linewidth=1.0,
    )
    ax.add_patch(rect)
    ax.text(
        x + w / 2, y + h / 2, texto,
        ha="center", va="center", color=cor_texto,
        fontsize=fontsize, weight="bold", wrap=True,
    )


def seta(ax, x1, y1, x2, y2, cor="black"):
    """Desenha uma seta entre dois pontos."""
    ax.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle="->", color=cor, lw=1.5),
    )


def figura_fluxo_metodologico() -> None:
    """Figura 1 — fluxo metodológico geral."""
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.set_aspect("equal")
    ax.axis("off")

    etapas = [
        (0.5, 5.0, "1. Coleta\n(SINAN, INMET,\nIBGE, PNI)",     COR_AZUL),
        (3.0, 5.0, "2. Pré-processamento\n(limpeza, validação)", COR_VERDE),
        (5.5, 5.0, "3. Integração\n(município × SE)",            COR_AMARELO),
        (8.0, 5.0, "4. Análise\nexploratória",                   COR_LARANJA),
        (3.0, 2.0, "5. STL e\nséries temporais",                 COR_AZUL),
        (5.5, 2.0, "6. Análise\ngeoespacial\n(Moran/DBSCAN)",    COR_VERDE),
        (8.0, 2.0, "7. Modelos\npreditivos\n(RF, XGB, Prophet)", COR_AMARELO),
        (10.5, 3.5, "8. Discussão e\nconclusões",                COR_LARANJA),
    ]
    for (x, y, t, c) in etapas:
        caixa(ax, x, y, 1.5, 1.0, t, c, fontsize=8.5)

    # Setas
    seta(ax, 2.0, 5.5, 3.0, 5.5)
    seta(ax, 4.5, 5.5, 5.5, 5.5)
    seta(ax, 7.0, 5.5, 8.0, 5.5)
    seta(ax, 8.75, 5.0, 8.75, 3.0)
    seta(ax, 7.0, 2.5, 8.0, 2.5)
    seta(ax, 4.5, 2.5, 5.5, 2.5)
    seta(ax, 3.75, 5.0, 3.75, 3.0)
    seta(ax, 9.5, 2.7, 10.5, 3.7)
    seta(ax, 8.75, 5.0, 10.5, 4.4)

    ax.set_title("Figura 1 — Fluxo metodológico geral da pesquisa",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    dest = cfg.figures_dir / "fig01_fluxo_metodologico.png"
    fig.savefig(dest, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def figura_arquitetura_pipeline() -> None:
    """Figura 2 — arquitetura do pipeline de coleta/integração."""
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.set_aspect("equal")
    ax.axis("off")

    # Fontes
    caixa(ax, 0.3, 4.5, 1.7, 0.8, "SINAN/DATASUS\n(PySUS)",  COR_AZUL,  fontsize=8.5)
    caixa(ax, 0.3, 3.3, 1.7, 0.8, "INMET API\n(clima)",       COR_VERDE, fontsize=8.5)
    caixa(ax, 0.3, 2.1, 1.7, 0.8, "IBGE SIDRA\n(IDHM, pop.)", COR_AMARELO, fontsize=8.5)
    caixa(ax, 0.3, 0.9, 1.7, 0.8, "PNI/OpenDataSUS\n(vacina)", COR_LARANJA, fontsize=8.5)

    # Processamento
    caixa(ax, 3.0, 2.5, 2.0, 1.0, "Coleta\n(scripts collect_*)", COR_CINZA, fontsize=9)
    caixa(ax, 6.0, 2.5, 2.0, 1.0, "Pré-processo\n(preprocess.py)", COR_CINZA, fontsize=9)
    caixa(ax, 9.0, 2.5, 2.0, 1.0, "Integração\n(integrate.py)",    COR_CINZA, fontsize=9)

    # Setas
    for y_origem in [4.9, 3.7, 2.5, 1.3]:
        seta(ax, 2.0, y_origem, 3.0, 3.0)
    seta(ax, 5.0, 3.0, 6.0, 3.0)
    seta(ax, 8.0, 3.0, 9.0, 3.0)

    # Saída final
    caixa(ax, 6.0, 0.5, 2.0, 0.8, "Tabela analítica\nintegrada (parquet)",
          COR_VERDE, fontsize=8.5)
    seta(ax, 10.0, 2.5, 8.0, 1.3)

    ax.set_title("Figura 2 — Arquitetura do pipeline de coleta e integração",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    dest = cfg.figures_dir / "fig02_arquitetura_pipeline.png"
    fig.savefig(dest, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def figura_estrutura_bases() -> None:
    """Figura 3 — esquema das bases de dados utilizadas."""
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # SINAN
    caixa(ax, 0.5, 3.5, 3.0, 2.0,
          "SINAN/DATASUS\n\n• dt_sin_pri\n• co_mun_res\n• cs_sexo / idade\n"
          "• classi_fin\n• doenca (DENG/ZIKA/CHIK)",
          COR_AZUL, fontsize=8.5)

    # INMET
    caixa(ax, 4.5, 3.5, 3.0, 2.0,
          "INMET\n\n• precipitação (mm)\n• temp. média (°C)\n"
          "• umidade rel. (%)\n• estação × dia",
          COR_VERDE, fontsize=8.5)

    # IBGE/PNI
    caixa(ax, 8.5, 3.5, 3.0, 2.0,
          "IBGE + PNI\n\n• população\n• IDHM\n• densidade demo.\n"
          "• saneamento\n• cobertura vacinal (Qdenga)",
          COR_LARANJA, fontsize=8.5)

    # Integrado
    caixa(ax, 3.0, 0.7, 6.0, 1.8,
          "TABELA ANALÍTICA INTEGRADA\n"
          "município × SE × doença → casos, clima, IDHM, saneamento, vacina",
          COR_CINZA, fontsize=10)

    seta(ax, 2.0, 3.5, 4.5, 2.5)
    seta(ax, 6.0, 3.5, 6.0, 2.5)
    seta(ax, 10.0, 3.5, 7.5, 2.5)

    ax.set_title("Figura 3 — Estrutura das bases SINAN, INMET e IBGE utilizadas",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    dest = cfg.figures_dir / "fig03_estrutura_bases.png"
    fig.savefig(dest, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log.info(f"Figura salva: {dest}")


def main() -> None:
    figura_fluxo_metodologico()
    figura_arquitetura_pipeline()
    figura_estrutura_bases()


if __name__ == "__main__":
    main()
