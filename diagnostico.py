"""
diagnostico.py — Localiza onde o pipeline perde os dados reais.
Rode na raiz do projeto:  python diagnostico.py
"""
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"
RAW  = ROOT / "data" / "raw"

def linha(txt=""):
    print(txt)

linha("=" * 64)
linha(" DIAGNÓSTICO DE DADOS — TCC DENGUE")
linha("=" * 64)

# 1. municipios_ibge.csv real?
mun_path = RAW / "ibge" / "municipios_ibge.csv"
linha("\n[1] Malha de municípios (data/raw/ibge/municipios_ibge.csv)")
if mun_path.exists():
    mun = pd.read_csv(mun_path, dtype=str)
    n = len(mun)
    linha(f"    Existe. Linhas: {n}")
    linha(f"    -> {'OK (malha REAL)' if n >= 5000 else 'PROBLEMA: malha SINTÉTICA/incompleta (esperado ~5.570)'}")
    if "cod_ibge_7" in mun.columns and "regiao" in mun.columns:
        sp = mun[mun['cod_ibge_7'].astype(str).str.startswith('3550308')]
        if len(sp):
            linha(f"    Teste São Paulo (3550308): regiao = {sp.iloc[0]['regiao']} (esperado Sudeste)")
else:
    linha("    AUSENTE -> rode: python src/collect_ibge_pni.py")

# 2. sinan_limpo particionado real?
sinan_dir = PROC / "sinan_limpo"
linha("\n[2] SINAN limpo particionado (data/processed/sinan_limpo/)")
if sinan_dir.exists():
    parts = list(sinan_dir.rglob("*.parquet"))
    linha(f"    Existe. Arquivos parquet: {len(parts)}")
    doencas = {p.parent.parent.name for p in parts if 'doenca=' in str(p)}
    linha(f"    Partições de doença: {doencas or 'NENHUMA (layout inesperado)'}")
else:
    linha("    AUSENTE -> rode preprocess.py ou reparticione o sinan_limpo único.")

sinan_unico = list(PROC.glob("sinan_limpo*.parquet"))
if sinan_unico:
    linha(f"    (Há arquivo único: {sinan_unico[0].name} — precisa ser reparticionado p/ o integrate.py)")

# 3. tabela integrada — real ou sintética?
linha("\n[3] Tabela integrada (data/processed/)")
real = PROC / "dados_integrados_2015_2026.parquet"
synth = PROC / "dados_integrados_sinteticos.parquet"
alvo = real if real.exists() else (synth if synth.exists() else None)
if synth.exists():
    linha(f"    ATENÇÃO: existe dados_integrados_sinteticos.parquet (o pipeline pode usá-lo).")
if alvo:
    df = pd.read_parquet(alvo, columns=None)
    nmun = df['cod_ibge_7'].nunique() if 'cod_ibge_7' in df.columns else '?'
    linha(f"    Lendo: {alvo.name}")
    linha(f"    Municípios distintos: {nmun}  -> {'OK' if isinstance(nmun,int) and nmun>=5000 else 'SINTÉTICO/incompleto'}")
    if 'tx_incidencia' in df.columns:
        linha(f"    tx_incidencia máx: {df['tx_incidencia'].max():,.0f}/100k  -> {'OK' if df['tx_incidencia'].max()<=100000 else 'IMPOSSÍVEL (>100k)'}")
    for c in ['precipitacao','temp_media','idhm','dens_demo']:
        if c in df.columns:
            linha(f"    {c}: {df[c].notna().mean()*100:.1f}% preenchido")
        else:
            linha(f"    {c}: AUSENTE")
else:
    linha("    Nenhuma tabela integrada encontrada.")

linha("\n" + "=" * 64)
linha(" VEREDITO")
linha("=" * 64)
problema_mun = not mun_path.exists() or (mun_path.exists() and len(pd.read_csv(mun_path)) < 5000)
problema_sinan = not sinan_dir.exists()
if problema_mun:
    linha(" -> Malha de municípios NÃO é real. Rode: python src/collect_ibge_pni.py")
if problema_sinan:
    linha(" -> SINAN limpo real ausente. Rode coleta/preprocess ou reparticione.")
if not problema_mun and not problema_sinan:
    linha(" -> Fontes reais presentes. Apague dados_integrados_sinteticos.parquet,")
    linha("    rode integrate.py de novo e valide com validate_real_data.py.")