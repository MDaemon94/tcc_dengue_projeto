# TCC — Ciência de Dados Aplicada à Dengue no Brasil (2015–2026)

> **Trabalho de Conclusão de Curso** — Tecnologia em Sistemas de Computação
> Universidade Federal Fluminense (UFF) / Consórcio CEDERJ
> Autor: **Murillo Daemon Neto**
> Orientador: **Prof. Dr. Luís Fernando Monsores Passos Maia**
> Ano: **2026**

Pipeline reproduzível em Python para descoberta de padrões epidemiológicos
de **dengue** no Brasil entre 2015 e 2026, com análise exploratória,
decomposição de séries temporais, análise geoespacial e modelos preditivos
de aprendizado de máquina.

---

## 1. Escopo

O escopo analítico **rigoroso** deste TCC é a **dengue** — doença para a qual
existe cobertura completa em correlações, modelos preditivos e validação.
Zika e chikungunya aparecem somente em análise exploratória/descritiva
auxiliar (Objetivos OE2 e OE3), sem modelagem preditiva.

Essa redução de escopo foi adotada após a revisão do TCC pelo orientador,
que apontou (com razão) que o trabalho prometia mais do que entregava
para Zika e chikungunya.

---

## 2. Estrutura do repositório

```
tcc_dengue_brasil/
├── data/                       # Dados brutos, processados e geográficos
│   ├── raw/                    # Não versionado (download pelos scripts)
│   ├── processed/              # Parquets intermediários
│   └── geo/                    # Shapefiles IBGE
├── docs/                       # TCC, e-mails de orientação, README
├── figures/                    # Saídas .png das figuras do TCC
├── models/                     # Modelos treinados (.joblib)
├── outputs/                    # Tabelas finais (.csv, .json)
├── scripts/                    # Shell helpers (Linux/Mac)
├── src/                        # Código-fonte do pipeline
│   ├── config.py
│   ├── collect_sinan.py        # Coleta SINAN via PySUS
│   ├── collect_inmet.py        # Coleta INMET (API)
│   ├── collect_ibge_pni.py     # Coleta IBGE + cobertura vacinal Qdenga
│   ├── preprocess.py           # Limpeza dos microdados
│   ├── integrate.py            # Integração SINAN + INMET + IBGE + PNI
│   ├── eda.py                  # Análise exploratória
│   ├── stl_analysis.py         # Decomposição STL
│   ├── correlation_analysis.py # Correlações com lag
│   ├── spatial_analysis.py     # Moran I + DBSCAN
│   ├── features.py             # Engenharia de variáveis
│   ├── train_models.py         # Modelos RF/XGBoost/Linear
│   ├── prophet_forecast.py     # Previsão Prophet
│   ├── make_concept_figures.py # Figuras esquemáticas 1, 2 e 3
│   ├── generate_synthetic_data.py  # Dados sintéticos p/ testes
│   └── run_pipeline.py         # Orquestrador
├── DATASETS.md                 # Como obter os datasets brutos
├── requirements.txt            # Dependências Python
└── README.md                   # Este arquivo
```

---

## 3. Como reproduzir

### 3.1. Requisitos

- Python ≥ 3.11
- ~6 GB de espaço em disco (dados brutos do SINAN)
- Conexão de internet (para coleta inicial)
- (Opcional) GPU para acelerar treino de LSTM

### 3.2. Instalação

```bash
git clone https://github.com/<seu-usuario>/tcc_dengue_brasil.git
cd tcc_dengue_brasil

# Ambiente virtual recomendado
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
# .venv\Scripts\activate           # Windows

pip install --upgrade pip
pip install -r requirements.txt
```

### 3.3. Execução completa (com dados reais)

```bash
# 1) Coleta automatizada (SINAN, IBGE/população)
#    Estratégia "streaming": cada ano é processado em batches de
#    200k linhas para evitar OOM em WSL com 8-16 GB de RAM.
python src/collect_sinan.py
python src/collect_ibge_pni.py

# 2) Coleta INMET (download MANUAL + processamento automático)
#    Baixe os 12 ZIPs anuais (2015–2026) do portal:
#      https://portal.inmet.gov.br/dadoshistoricos
#    Coloque-os em data/raw/inmet/zips/ e então:
python src/collect_inmet.py

# 3) Pré-processamento e integração (em streaming)
python src/preprocess.py
python src/integrate.py

# 4) Pipeline analítico completo
python src/run_pipeline.py
```

### 3.4. Checklist de downloads manuais

Quatro conjuntos de dados precisam ser **baixados pelo navegador** porque
não há API estável ou os portais bloqueiam coleta automatizada.
Marque cada item conforme for concluindo. Detalhes completos em
**[DATASETS.md](DATASETS.md)**.

| ☐ | Dataset                       | Onde baixar                                                         | Onde colocar                                | Tempo aprox. |
|---|-------------------------------|---------------------------------------------------------------------|---------------------------------------------|--------------|
| ☐ | **INMET — clima (12 ZIPs)**   | <https://portal.inmet.gov.br/dadoshistoricos>                       | `data/raw/inmet/zips/2015.zip ... 2026.zip` | 15 min       |
| ☐ | **IDHM 2010 (XLSX)**          | <http://www.atlasbrasil.org.br/consulta/planilha>                   | `data/raw/ibge/idhm_municipal.xlsx`         | 10 min       |
| ☐ | **Saneamento 2010 (XLSX)**    | <http://www.atlasbrasil.org.br/consulta/planilha>                   | `data/raw/ibge/saneamento_municipal.xlsx`   | 10 min       |
| ☐ | **Vacinação dengue (lista)**  | Informe Técnico 2024 do MS (ver DATASETS.md)                        | `data/raw/pni/vacinacao_municipal.csv`      | 10 min       |
| ☐ | **Malha municipal IBGE 2022** | <https://geoftp.ibge.gov.br/.../BR_Municipios_2022.zip>             | `data/geo/`                                 | 2 min        |

> **Por que esses datasets são manuais?**
> - **INMET**: bloqueio anti-scraping em IPs de WSL/cloud.
> - **IDHM 2010** e **Saneamento 2010**: Atlas Brasil não tem API pública; só interface web. Mesma fonte (Censo 2010), mesma interface — você baixa os dois com 2 downloads consecutivos.
> - **Vacinação**: lista oficial publicada em PDF do Ministério da Saúde (não há endpoint estável).
> - **Malha geográfica**: arquivo único de ~250 MB, baixar uma vez é mais direto que via script.
>
> Todos os passos completos com prints e screenshots estão em
> **[DATASETS.md](DATASETS.md)**.

### 3.5. Como verificar se tudo foi baixado

Antes de rodar o pipeline analítico, confira a estrutura esperada:

```bash
python src/check_data.py
```

Esse comando lê todas as fontes e relata o que está presente, ausente
ou incompleto, com sugestão de ação para cada caso.

> **Sobre o uso de memória.** O pipeline foi projetado para rodar em
> máquinas modestas (8-16 GB de RAM, WSL incluso). O SINAN bruto chega
> a ter 6,5 milhões de notificações em um único ano (2024). Por isso:
>
> - **Não carregamos o ano inteiro em RAM**: usamos `pyarrow.parquet.ParquetFile.iter_batches` para processar 200k linhas por vez.
> - **Selecionamos apenas as ~15 colunas necessárias** (de ~120 do SINAN bruto), reduzindo o uso de memória em ~85%.
> - **Persistimos como dataset particionado** (`doenca=X/ano=Y/part-*.parquet`), evitando o problema do append não-suportado em Parquet.
> - Pico de RAM observado em todo o pipeline: **~1,2 GB**.

### 3.4. Execução rápida (dados sintéticos, sem download)

Para validar instalação e reproduzir a estrutura das figuras
sem precisar baixar microdados:

```bash
python src/generate_synthetic_data.py
python src/run_pipeline.py
```

> ⚠️ Os dados sintéticos têm **médias, sazonalidades e volumes
> calibrados pelos boletins do Ministério da Saúde**, mas não são
> dados reais. Use apenas para verificar o pipeline.

---

## 4. Onde estão os datasets

Os datasets brutos não são versionados no Git (excedem o limite de 100 MB
do GitHub). Veja **[DATASETS.md](DATASETS.md)** para:

- Links oficiais (DATASUS, INMET, IBGE, OpenDataSUS).
- Lista de arquivos esperados em `data/raw/`.
- Comandos `curl`/`wget` para download manual.
- Backup dos dados consolidados que utilizei (Google Drive).

---

## 5. Pipeline metodológico

```
[SINAN] [INMET] [IBGE] [PNI]
    \      |      |     /
     v     v      v    v
   coleta → preprocess → integrate
                            |
              ┌─────────────┼─────────────┐
              v             v             v
            EDA           STL          Spatial
              \           |           /
               v          v          v
                    features
                       |
            ┌──────────┴──────────┐
            v                     v
        Modelos ML            Prophet
        (RF, XGB)             (univariada)
            \                     /
             v                   v
              comparação e métricas
                       |
                       v
                discussão e conclusões
```

---

## 6. Principais resultados

Os resultados aqui apresentados foram obtidos com os **dados oficiais**
(SINAN/DATASUS, INMET, IBGE). Para resultados com dados sintéticos,
abra os arquivos em `outputs/`.

| Métrica                        | Valor                        |
| ------------------------------ | ---------------------------- |
| Período analisado              | 2015 – 2026 (parcial)        |
| Notificações de dengue (Brasil)| ~24,5 milhões                |
| Maior epidemia da história     | 2024 (~6,5 milhões de casos) |
| Força sazonal (Fs) — dengue    | 0,87                         |
| Moran I global (k-NN)          | 0,41 (p < 0,001)             |
| Clusters DBSCAN                | 23                           |
| Melhor R² (XGBoost, h=4 sem.)  | 0,89                         |

Detalhes em `outputs/tabela6_metricas_modelos.csv`.

---

## 7. Limitações reconhecidas

- **Estudo ecológico observacional** — as correlações encontradas
  são **indicadores de vulnerabilidade socioespacial** e **não implicam
  causalidade direta**.
- **Subnotificação estrutural** do SINAN (cerca de 10 % de casos
  confirmados em laboratório no Nordeste, ~30 % no Sul).
- **Cobertura vacinal** (Qdenga, incorporada em 2024) só atinge ~5,0 %
  da população alvo nos primeiros meses de campanha; ainda é cedo
  para isolar seu efeito no modelo.
- **Heterogeneidade regional**: o desempenho do modelo é melhor no
  Sudeste e Centro-Oeste e pior na Amazônia (menor densidade de
  estações INMET, maior subnotificação).

Discussão completa: Cap. 8.6 e 9.2 do TCC.

---

## 8. Licença

Código sob **MIT License** (veja `LICENSE`).
Dados públicos do SUS/INMET/IBGE: domínio público, mantendo créditos
aos órgãos produtores.

---

## 9. Contato

Murillo Daemon Neto – `mdaemonneto@gmail.com`
