"""
geo_utils.py
============
Carrega os centroides REAIS dos municípios a partir do shapefile
oficial do IBGE (data/geo/BR_Municipios_2022.shp), substituindo as
pseudocoordenadas aleatórias usadas anteriormente no spatial_analysis.

Por que isto importa
--------------------
O Moran I e o DBSCAN dependem das coordenadas geográficas reais para
medir vizinhança. Coordenadas aleatórias produzem Moran I ≈ 0 (falsa
ausência de autocorrelação) e clusters sem sentido. Com os centroides
reais, a autocorrelação espacial passa a refletir o padrão real da
dengue no território.

Uso
---
    from geo_utils import carregar_centroides
    cent = carregar_centroides()          # DataFrame: cod_ibge_7, lat, lon
    df_mun = df_mun.merge(cent, on="cod_ibge_7", how="left")

Autor : Murillo Daemon Neto
Data  : 2026
"""
from __future__ import annotations

import logging

import pandas as pd

from config import cfg

log = logging.getLogger("geo")


def carregar_centroides() -> pd.DataFrame:
    """
    Lê o shapefile do IBGE e devolve os centroides (lat/lon) por município.
    Retorna DataFrame vazio se geopandas ou o shapefile não estiverem
    disponíveis (mantém compatibilidade — o chamador deve tratar isso).
    """
    shp = cfg.geo_dir / "BR_Municipios_2022.shp"
    if not shp.exists():
        log.warning(f"Shapefile não encontrado em {shp}. Sem centroides reais.")
        return pd.DataFrame(columns=["cod_ibge_7", "lat", "lon"])

    try:
        import geopandas as gpd
    except ImportError:
        log.warning("geopandas não instalado (pip install geopandas). "
                    "Sem centroides reais.")
        return pd.DataFrame(columns=["cod_ibge_7", "lat", "lon"])

    gdf = gpd.read_file(shp)

    # Coluna do código do município no shapefile do IBGE 2022 = 'CD_MUN'
    col_cod = next((c for c in ["CD_MUN", "CD_GEOCMU", "GEOCODIGO", "cod_ibge_7"]
                    if c in gdf.columns), None)
    if col_cod is None:
        log.error(f"Coluna de código não encontrada. Colunas: {list(gdf.columns)}")
        return pd.DataFrame(columns=["cod_ibge_7", "lat", "lon"])

    # Centroide em CRS projetado (evita o aviso de centroide em lat/lon),
    # depois reprojeta para WGS84 para obter lat/lon em graus.
    gdf_proj = gdf.to_crs(epsg=5880)          # SIRGAS 2000 / Brazil Polyconic
    cent = gdf_proj.geometry.centroid.to_crs(epsg=4326)

    out = pd.DataFrame({
        "cod_ibge_7": gdf[col_cod].astype(str).str.zfill(7),
        "lat": cent.y.values,
        "lon": cent.x.values,
    })
    log.info(f"Centroides reais carregados: {len(out):,} municípios.")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s")
    c = carregar_centroides()
    print(c.head())
    print(f"Total: {len(c)} municípios com centroide.")