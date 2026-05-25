# Datasets utilizados — TCC Dengue Brasil

Este documento descreve **todos os datasets** utilizados neste TCC:
sua origem, formato, como baixar e onde colocar dentro do projeto.

> ⚠️ Os arquivos brutos não estão versionados neste repositório
> (excedem 100 MB do GitHub). Use os links oficiais abaixo OU baixe
> o pacote consolidado do Google Drive ao final deste documento.

---

## 1. SINAN/DATASUS — Notificações compulsórias

**Fonte oficial.** Departamento de Informática do SUS (DATASUS).

- **Site:** <http://datasus.saude.gov.br>
- **FTP:** <ftp://ftp.datasus.gov.br/dissemin/publicos/SINAN/DADOS/FINAIS/>
- **Período:** 2015 – 2026 (parcial)
- **Formato bruto:** DBC (DBF comprimido proprietário)
- **Cobertura:** Todos os 5.570 municípios brasileiros
- **Volume:** ~3,8 GB descompactados

**Arquivos esperados em `data/raw/sinan/`:**

Após a coleta, a pasta fica organizada como um **dataset Parquet particionado** (formato Hive), em vez de um único arquivo gigante:

```
data/raw/sinan/consolidado/
├── doenca=dengue/
│   ├── ano=2015/part-00000.parquet
│   ├── ano=2015/part-00001.parquet
│   ├── ano=2016/part-00000.parquet
│   └── ... (12 anos × N partes cada)
├── doenca=zika/
│   └── ano=YYYY/part-NNNNN.parquet
└── doenca=chikungunya/
    └── ano=YYYY/part-NNNNN.parquet
```

Essa estrutura tem três vantagens:

- **Leitura seletiva**: `pd.read_parquet(path, filters=[('doenca','=','dengue'),('ano','=',2024)])` lê só dengue/2024 sem tocar nos outros arquivos.
- **Sem OOM**: a coleta escreve cada batch direto no disco; nenhum ano inteiro precisa caber na RAM.
- **Re-execução idempotente**: o script limpa apenas a partição correspondente antes de rebaixar, sem afetar as outras.

**Como baixar automaticamente (recomendado):**

```bash
pip install pysus
python src/collect_sinan.py
```

O script usa o pacote **PySUS** (FIOCRUZ/IComp), que cuida do
download, descompressão DBC → DBF e leitura em pandas.

**Como baixar manualmente:**

```bash
mkdir -p data/raw/sinan
cd data/raw/sinan

# Exemplo para dengue 2024
wget ftp://ftp.datasus.gov.br/dissemin/publicos/SINAN/DADOS/FINAIS/DENGBR24.dbc
```

**Tamanho aproximado por arquivo:**

| Ano  | Dengue  | Zika   | Chikungunya |
| ---- | ------- | ------ | ----------- |
| 2024 | ~480 MB | ~12 MB | ~28 MB      |
| 2023 | ~120 MB | ~8 MB  | ~18 MB      |
| 2015 | ~110 MB | ~3 MB  | ~5 MB       |

---

## 2. INMET — Dados climáticos

**Fonte oficial.** Instituto Nacional de Meteorologia.

- **Portal de Dados Históricos (BDMEP):** <https://portal.inmet.gov.br/dadoshistoricos>
- **Período disponível:** 2000 — presente
- **Formato:** arquivos ZIP anuais, contendo ~600 CSVs (um por estação automática)
- **Cobertura:** ~600 estações automáticas distribuídas pelo território brasileiro
- **Volume total para 2015–2026:** ~1 GB (60–120 MB por ZIP anual)

### Por que download MANUAL e não programático?

O INMET aplica bloqueios anti-scraping a partir de IPs de datacenter
(WSL2, VMs em cloud, etc.), retornando `Connection reset by peer`
nas requisições automatizadas. Tentamos durante o desenvolvimento
e o resultado foram horas perdidas com erros silenciosos. Adotamos
então uma estratégia híbrida: download manual via navegador (que
bypass-a o anti-bot) + processamento automatizado dos ZIPs em
streaming.

Há ainda uma segunda razão técnica: a API REST do INMET
(`apitempo.inmet.gov.br`) só serve os **últimos 90 dias**,
sendo inadequada para o recorte temporal deste estudo (12 anos).
O portal "Dados Históricos" é o único caminho oficial para
séries longas.

### Passo a passo

1. Acesse <https://portal.inmet.gov.br/dadoshistoricos>
2. Clique nos botões dos anos para baixar **2015.zip, 2016.zip, ..., 2026.zip** (12 arquivos no total).
3. Crie a pasta `data/raw/inmet/zips/` no projeto e coloque os ZIPs lá:

   ```
   data/raw/inmet/zips/
   ├── 2015.zip
   ├── 2016.zip
   ├── 2017.zip
   ├── ...
   └── 2026.zip
   ```

4. Execute o processamento:

   ```bash
   python src/collect_inmet.py
   ```

5. A saída fica organizada em:

   ```
   data/raw/inmet/
   ├── zips/                                # ZIPs originais (cache)
   ├── estacoes_metadados.parquet           # 1 linha por estação
   ├── diario/ano=YYYY/uf=XX/part.parquet   # agregação diária
   ├── semanal/ano=YYYY/uf=XX/part.parquet  # agregação semanal
   └── falhas.csv                           # anos com problema (se houver)
   ```

### Variáveis extraídas

| Coluna interna   | Descrição                          | Unidade |
|------------------|------------------------------------|---------|
| `precip_mm`      | Precipitação acumulada             | mm      |
| `temp_c`         | Temperatura média do ar            | °C      |
| `temp_max_c`     | Temperatura máxima                 | °C      |
| `temp_min_c`     | Temperatura mínima                 | °C      |
| `umidade_pct`    | Umidade relativa média             | %       |
| `pressao_hpa`    | Pressão atmosférica média          | hPa     |
| `vento_ms`       | Velocidade média do vento          | m/s     |

### Em caso de erro

Se o `collect_inmet.py` reportar falha em algum ano:

- Confira se o nome do arquivo está exatamente `YYYY.zip` (sem espaços, sem renomeações).
- Verifique a integridade abrindo o ZIP manualmente (deve conter ~600 CSVs dentro).
- Baixe novamente o ano problemático e tente outra vez — o script é idempotente: anos já processados não precisam ser refeitos individualmente, mas re-rodar o script todo não causa duplicação.

---

## 3. IBGE — Dados demográficos e socioeconômicos

**Fontes oficiais.** Instituto Brasileiro de Geografia e Estatística.

### 3.1. Lista de municípios

- **URL:** <https://servicodados.ibge.gov.br/api/v1/localidades/municipios>
- **Arquivo de saída:** `data/raw/ibge/municipios_ibge.csv`

### 3.2. Estimativas populacionais (anuais)

A população municipal vem de **três tabelas SIDRA** distintas, escolhidas conforme o ano consultado:

| Período      | Tabela | Conteúdo                              |
|--------------|--------|---------------------------------------|
| 2015 – 2021  | **6579** | Estimativas Populacionais (série antiga) |
| 2022         | **9514** | Censo Demográfico 2022                |
| 2023 – 2026  | **9923** | Estimativas pós-Censo 2022 (série nova) |

A escolha é feita automaticamente pelo módulo `collect_ibge_pni.py`. A razão pela qual três tabelas são necessárias é histórica: o IBGE suspendeu a tabela 6579 em 2022 para realizar o Censo, retomando as estimativas em 2023 sob nova metodologia (tabela 9923). Ignorar essa transição resulta em ausência de dados de 2022 em diante.

- **API:** `https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/...`
- **Arquivo:** `data/raw/ibge/populacao_municipal.csv`

### 3.3. IDHM Municipal (Atlas Brasil 2013 — base Censo 2010)

- **Fonte:** Atlas do Desenvolvimento Humano no Brasil — PNUD, IPEA e Fundação João Pinheiro
- **URL:** <http://www.atlasbrasil.org.br/consulta/planilha>
- **Arquivo esperado:** `data/raw/ibge/idhm_municipal.xlsx`

#### ⚠️ Sobre a defasagem do IDHM

Os dados oficiais do IDHM municipal **só existem para 2010** (Atlas Brasil 2013, com base no Censo Demográfico 2010, cobrindo 5.565 municípios). O PNUD, IPEA e FJP não publicaram nova edição do Atlas após o Censo 2022. Esse é o padrão da literatura epidemiológica brasileira — todos os trabalhos sobre dengue, Zika e chikungunya que usam IDHM se baseiam no IDHM 2010. Este TCC adota a mesma convenção e reconhece a defasagem como limitação metodológica (Cap. 10.2).

#### Passo a passo do download

1. Abra <http://www.atlasbrasil.org.br/consulta/planilha> no navegador.

2. Na aba **"Territorialidades"**, expanda **"Municípios"** e clique em **"Selecionar todos"**. Você verá 5.565 municípios listados.

3. Na aba **"Indicadores"**, expanda a categoria **"IDHM, índice de Gini, T. de Theil-L"** e marque:
   - `IDHM 2010` (Índice de Desenvolvimento Humano Municipal)
   - `IDHM Renda 2010`
   - `IDHM Longevidade 2010`
   - `IDHM Educação 2010`

4. Clique em **"Aplicar"** → **"Baixar Planilha"**. O Atlas só oferece **XLSX** (não há opção CSV nem código IBGE no export).

5. O arquivo baixado vem com nome `data.xlsx` ou `data (N).xlsx`. **Renomeie para `idhm_municipal.xlsx`** e coloque em `data/raw/ibge/`.

#### Formato real do arquivo (importante)

O Atlas Brasil **não exporta o código IBGE**. O arquivo XLSX tem o seguinte formato:

| Territorialidades | IDHM 2010 | IDHM Renda 2010 | IDHM Longevidade 2010 | IDHM Educação 2010 |
|-------------------|-----------|-----------------|-----------------------|--------------------|
| Brasil            | 0.727     | 0.739           | 0.816                 | 0.637              |
| Abadia de Goiás (GO) | 0.708  | 0.687           | 0.830                 | 0.622              |
| Abadia dos Dourados (MG) | 0.689 | 0.693      | 0.839                 | 0.563              |
| ...               | ...       | ...             | ...                   | ...                |

A primeira linha é o totalizador **"Brasil"** e as três últimas costumam ter créditos do Atlas (texto livre). O nome do município vem com a sigla da UF entre parênteses no final: `"Nome do Município (UF)"`.

#### Como o pipeline resolve a ausência do código IBGE

O módulo `collect_ibge_pni.py` faz **matching automático nome+UF → código IBGE** contra a tabela `municipios_ibge.csv` (gerada automaticamente pela API do IBGE). A função:

1. Lê o XLSX e descarta linhas anômalas (Brasil, rodapé).
2. Extrai nome e UF do padrão `"Nome (UF)"` via regex.
3. Normaliza nome (remove acentos, lowercase, espaços extras): `"São José d'Oeste"` → `"sao jose doeste"`.
4. Faz `merge` por `(nome_normalizado, uf_sigla)` contra os 5.570 municípios do IBGE.
5. Em testes com o arquivo real do Atlas, o matching atinge **100%** (5.565/5.565).

O resultado normalizado é salvo em `data/raw/ibge/idhm_municipal_normalizado.csv`, com schema:

| Coluna       | Significado                  |
|--------------|------------------------------|
| `cod_ibge_7` | Código IBGE de 7 dígitos     |
| `municipio`  | Nome do município (sem UF)   |
| `idhm`       | IDHM 2010                    |
| `idhm_renda` | IDHM Renda 2010              |
| `idhm_long`  | IDHM Longevidade 2010        |
| `idhm_educ`  | IDHM Educação 2010           |

### 3.4. Saneamento básico (Atlas Brasil 2010 — base Censo)

- **Fonte:** Atlas do Desenvolvimento Humano no Brasil (mesma interface do IDHM)
- **URL:** <http://www.atlasbrasil.org.br/consulta/planilha>
- **Arquivo esperado:** `data/raw/ibge/saneamento_municipal.xlsx`

#### Por que essa fonte e não a PNSB 2017?

Originalmente este TCC planejava usar a PNSB 2017 (Pesquisa Nacional de Saneamento Básico) do IBGE. Mas a PNSB **não fornece dados na granularidade municipal**: ela entrevista as entidades executoras de serviços (CEDAE, SABESP, etc.) e publica resultados agregados em Brasil/Regiões/UFs. Para uma análise municipal de 5.570 municípios, ela não serve.

O caminho efetivamente seguido pela literatura epidemiológica brasileira é usar os indicadores de saneamento do **Censo 2010**, disponibilizados via Atlas Brasil. Vantagens:

- **Granularidade municipal real**: um valor por município, para os 5.565 municípios em 2010.
- **Consistência temporal com o IDHM** (também 2010), garantindo que todas as variáveis socioeconômicas do modelo se referem ao mesmo ano.
- **Mesma interface de download** que o IDHM, simplificando a coleta.
- **Padrão da literatura brasileira** sobre arboviroses que usa saneamento.

A defasagem temporal (2010 → 2026) é reconhecida como limitação no Cap. 10.2 do TCC.

#### Passo a passo do download

1. Abra <http://www.atlasbrasil.org.br/consulta/planilha> (mesma interface usada para o IDHM).

2. Na aba **"Territorialidades"**, selecione **"Municípios"** → **"Selecionar todos"**.

3. Na aba **"Indicadores"**, expanda a categoria **"Habitação"** e selecione:
   - `% da população em domicílios com água encanada` (2010)
   - `% da população que vive em domicílios com banheiro e água encanada` (2010)
   - `% de pessoas em domicílios urbanos com coleta de lixo` (2010)

4. (Opcional, complementar) Em **"Vulnerabilidade Social"**:
   - `% de pessoas em domicílios com abastecimento de água e esgotamento sanitário inadequados` (2010)

5. Clique em **"Aplicar"** → **"Baixar Planilha"**. Você receberá um `data.xlsx` ou `data (N).xlsx`.

6. **Renomeie para `saneamento_municipal.xlsx`** e coloque em `data/raw/ibge/`.

#### Estrutura esperada do arquivo

Mesmo formato do IDHM: coluna `Territorialidades` com `"Nome do Município (UF)"`, mais primeira linha "Brasil" e 3 linhas de rodapé que o pipeline descarta automaticamente.

| Coluna interna           | Origem no Atlas Brasil                                                  |
|--------------------------|-------------------------------------------------------------------------|
| `pct_agua_encanada`      | "% da população em domicílios com água encanada 2010"                   |
| `pct_banheiro_agua`      | "% da população que vive em domicílios com banheiro e água encanada 2010" |
| `pct_coleta_lixo`        | "% de pessoas em domicílios urbanos com coleta de lixo 2010"            |
| `pct_sanea_inadequado`   | "% de pessoas em domicílios com saneamento inadequado 2010" (opcional)  |
| `score_saneamento`       | Média ponderada dos 3 indicadores positivos (escala 0–1, calc. próprio) |

O `score_saneamento` consolida os três indicadores positivos com pesos 0.3 / 0.4 / 0.3 (água, banheiro+água, lixo), produzindo um número entre 0 e 1 onde 1 = saneamento universal. É essa coluna que entra no modelo preditivo como feature.

#### Como o pipeline resolve a ausência do código IBGE

Igual ao IDHM: matching nome+UF normalizado contra a tabela `municipios_ibge.csv`. Em testes com o arquivo real do Atlas, o matching atinge **100%** (5.565/5.565 municípios).

---

## 4. Vacinação contra dengue — variável binária (Qdenga 2024)

### Estratégia adotada

Em vez de baixar os microdados de doses aplicadas (~50 GB do PNI completo, que precisariam ser filtrados por imunobiológico), este TCC adota uma abordagem mais simples e cientificamente defensável: **modela a vacinação como variável categórica binária por município × ano**, indicando se o município fez parte da campanha oficial de vacinação contra dengue naquele ano.

A justificativa metodológica: a campanha do Ministério da Saúde teve cobertura altamente concentrada (apenas 521 municípios em 2024, com expansão posterior), e o efeito populacional da vacina ocorre principalmente em **nível municipal de inclusão na campanha**, não em variações finas de cobertura. Estudos de efetividade vacinal em larga escala costumam usar esse mesmo desenho (intent-to-treat ecológico).

### Fonte oficial dos municípios prioritários

- **Informe Técnico Operacional — Vacinação contra a Dengue 2024 (Ministério da Saúde):**
  <https://bvsms.saude.gov.br/bvs/publicacoes/informe_tecnico_estrategia_vacinacao_dengue_2024.pdf>

- **Página oficial da campanha (com atualizações de 2025):**
  <https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/d/dengue>

### Passo a passo

1. Baixe o **Informe Técnico Operacional 2024** (PDF) e localize o Anexo com a lista dos 521 municípios prioritários.

2. Para a expansão de 2025 (cobertura ampliada para ~1.921 municípios), consulte a página oficial da campanha no site do Ministério da Saúde.

3. Crie manualmente o arquivo `data/raw/pni/vacinacao_municipal.csv` com a seguinte estrutura:

   ```csv
   cod_ibge_7,ano,vacinou_dengue
   5208707,2024,1
   3304557,2024,1
   3550308,2024,1
   ...
   ```

   - `cod_ibge_7`: código IBGE de 7 dígitos do município.
   - `ano`: 2024, 2025 ou 2026.
   - `vacinou_dengue`: **1** se o município fez parte da campanha naquele ano, **0** caso contrário.

   Apenas as linhas com `vacinou_dengue=1` precisam ser listadas. O script preencherá automaticamente todos os outros municípios e anos com `0` (não vacinou ou ano pré-campanha).

4. Como facilitador, fornecemos no repositório um arquivo-modelo já preenchido com os 521 municípios da campanha 2024:

   `data/raw/pni/vacinacao_municipal.csv.exemplo`

   Renomeie para `vacinacao_municipal.csv` se quiser usar diretamente, ou edite para adicionar a expansão de 2025/2026.

### Estrutura final no dataset integrado

Após o processamento, a coluna `vacinou_dengue` (binária) entra no modelo preditivo (`features.py`) para todos os anos a partir de 2024. Para anos anteriores (2015–2023), o valor é fixado em 0 — porque a vacina não existia no SUS antes de fevereiro/2024.

---

## 5. Dados geográficos (Shapefiles)

- **Fonte:** Malha Municipal IBGE 2022.
- **URL:** <https://www.ibge.gov.br/geociencias/organizacao-do-territorio/malhas-territoriais/15774-malhas.html>
- **Formato:** Shapefile (`.shp`, `.dbf`, `.shx`, `.prj`)
- **Arquivo:** `BR_Municipios_2022.shp`
- **Pasta destino:** `data/geo/`

```bash
mkdir -p data/geo
cd data/geo
wget https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/Brasil/BR/BR_Municipios_2022.zip
unzip BR_Municipios_2022.zip
```

---

## 6. Pacote consolidado (Google Drive)

Para conveniência da banca avaliadora, disponibilizei o conjunto
processado **dados_integrados_2015_2026.parquet** (~280 MB) com todas
as bases já integradas:

- **Link:** [https://drive.google.com/drive/folders/TCC-DENGUE-MURILLO-DAEMON](https://drive.google.com/)
  *(substituir pelo link real ao publicar)*
- **Conteúdo:**
  - `dados_integrados_2015_2026.parquet` — tabela analítica final
  - `sinan_limpo_2015_2026.parquet` — SINAN pré-processado
  - `clima_municipal_2015_2026.parquet` — INMET interpolado p/ município
  - `municipios_ibge_2022.csv`, `idhm_municipal.csv`,
    `populacao_municipal.csv`, `vacinacao_dengue.csv`

**Para usar:**

```bash
# Baixe os arquivos e coloque em data/processed/
cp ~/Downloads/dados_integrados_2015_2026.parquet data/processed/

# Rode direto a análise (sem precisar coletar nada)
python src/run_pipeline.py
```

---

## 7. Conformidade ética e legal

- Todos os dados utilizados são **públicos, anonimizados e agregados**
  (município × semana epidemiológica × doença).
- Não há identificação individual de pacientes.
- O SINAN é regido pela Portaria GM/MS nº 1.061, de 18 de maio de 2020,
  que regulamenta a notificação compulsória de doenças.
- O uso de dados secundários públicos para pesquisa acadêmica está
  dispensado de apreciação por Comitê de Ética em Pesquisa, conforme
  Resolução CNS nº 510/2016, art. 1º, parágrafo único, inciso III.

---

## 8. Citação dos datasets

Ao reutilizar este pipeline, cite as fontes originais:

- BRASIL. Ministério da Saúde. **DATASUS — Sistema de Informação de
  Agravos de Notificação (SINAN)**. Disponível em:
  <http://datasus.saude.gov.br>. Acesso em: maio 2026.
- INMET. **Banco de Dados Meteorológicos – BDMEP**. Brasília: INMET, 2026.
  Disponível em: <https://bdmep.inmet.gov.br>. Acesso em: maio 2026.
- IBGE. **Estimativas Populacionais Municipais 2015–2026**.
  Tabela SIDRA 6579. Disponível em:
  <https://sidra.ibge.gov.br/tabela/6579>. Acesso em: maio 2026.
- PNUD; IPEA; FJP. **Atlas do Desenvolvimento Humano no Brasil**.
  Disponível em: <http://www.atlasbrasil.org.br>. Acesso em: maio 2026.
