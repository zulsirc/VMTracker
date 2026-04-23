# Vending Machine Heatmap

Heurística espacial para **prospecção de áreas** (não hosts específicos) onde
uma vending machine tem maior potencial. A saída é um **mapa HTML navegável**
com overlay hexagonal sobre o mapa real, tooltip por célula mostrando o
breakdown do score, heatmap suavizado opcional e marcadores de ranking das
melhores áreas.

Primeira cidade alvo: **Macaé / RJ**, recortada no lado principal antes da
Ponte da Barra (Barra de Macaé, aeroporto e periferia ficam de fora).
Parametrizável para qualquer cidade via YAML.

---

## Como rodar

```bash
# 1. dependências
pip install -r requirements.txt

# 2. execução — default = Macaé
python main.py --city macae
# ou equivalente:
python main.py --config configs/macae.yaml

# 3. abra o HTML no navegador
xdg-open output/macae_vending_heatmap.html     # Linux
open  output/macae_vending_heatmap.html         # macOS
start output/macae_vending_heatmap.html         # Windows
```

Opcional:
```bash
python main.py --city macae --no-fetch   # usa apenas o cache local
pytest -q                                 # roda os testes offline
```

A primeira execução baixa POIs, landuse e malha viária do Overpass API (OSM)
para a área de estudo. Os resultados ficam cacheados em `output/cache/` e as
execuções seguintes são quase instantâneas.

---

## O que sai no diretório `output/`

| arquivo                         | descrição                                              |
|---------------------------------|--------------------------------------------------------|
| `macae_vending_heatmap.html`    | mapa interativo (Folium/Leaflet) — **abra isto**       |
| `macae_grid_scores.geojson`     | malha H3 + score + breakdown (para QGIS/kepler/etc)    |
| `macae_all_cells.csv`           | tabela completa (todas as células, todas as colunas)   |
| `macae_top_cells.csv`           | ranking das top-N áreas (default 40)                   |
| `macae_report.md`               | relatório metodológico + top ranking                   |
| `cache/`                        | JSON cru das queries Overpass (reuso)                  |

---

## Estrutura do projeto

```
VMTracker/
├── README.md
├── requirements.txt
├── main.py                    # CLI / pipeline orchestrator
├── configs/
│   └── macae.yaml             # área, pesos, paleta, saídas, queries
├── src/
│   ├── __init__.py
│   ├── utils.py               # logging, YAML, hashing
│   ├── overpass_client.py     # cliente Overpass com cache + retries
│   ├── data_sources.py        # fetch de POIs / landuse / roads
│   ├── geometry.py            # polígono de estudo, H3 grid, clip, intersect
│   ├── features.py            # contagens, densidade viária, anchor-proximity,
│   │                          # diversidade, smoothing por anéis H3
│   ├── scoring.py             # normalização + weighted sum + rank blend
│   ├── visualization.py       # Folium map + GeoJson + HeatMap + markers
│   └── report.py              # markdown report
├── tests/
│   └── test_pipeline.py       # 7 testes offline (grid, score, rendering)
└── output/
    └── ...                    # gerado pelo pipeline
```

---

## Metodologia

### 1. Área de estudo
Polígono custom definido em `configs/macae.yaml` → `study_area.polygon`.
Para Macaé, o recorte cobre a zona sul/consolidada (Centro, Imbetiba,
Cavaleiros, Granja dos Cavaleiros, Glória, Praia Campista, Costa do Sol,
Lagomar, Riviera, Nova Holanda…) e exclui Barra de Macaé, aeroporto e
periferia rural.

Para outra cidade: copie o YAML, troque `polygon` + `bbox` + `map.center` e
rode.

### 2. Grid
Hexágonos H3 na resolução **9** (~174m de aresta, ~0,10 km² por célula).
Ajustável em `grid.h3_resolution` (res 10 = ~66m, res 8 = ~460m).

### 3. Coleta de dados (Overpass / OSM)

Para cada categoria em `poi_categories`, o pipeline faz uma query Overpass
pegando nós/ways/relations com as tags listadas e extrai o ponto
(`out center tags`). Categorias cobertas:

`shop`, `supermarket`, `food` (restaurante/bar/café/fast-food/gelateria),
`pharmacy`, `healthcare`, `education`, `fitness`, `office`, `bank`,
`transport` (parada de ônibus, terminal, estação), `leisure` (parque,
hotel, atração), `fuel`.

Landuse é baixado como polígono (`out geom`) para 4 classes:
`residential`, `commercial`, `industrial` e `unsuitable`
(mata/água/wetland/aeródromo/militar/agrícola).

Vias (`roads`) também em polígono/linha, cobrindo `primary` até
`living_street`, usadas para densidade viária.

### 4. Features por célula

Para cada célula H3:

- **Contagens por categoria** de POI (point-in-polygon)
- **Fração de landuse** (área das polys ∩ área da célula) → residential,
  commercial, industrial, unsuitable
- **Densidade viária** (metros de via / km² da célula)
- **Anchor proximity** — distância média às 3 POIs âncora mais próximas
  (food/shop/supermarket/pharmacy/transport) mapeada por `1/(1 + d/500m)`.
  Dá um sinal **contínuo** para toda célula — mesmo as vazias se
  diferenciam pela distância à mancha urbana.
- **Diversidade (mixed-use)** — entropia de Shannon normalizada sobre as
  contagens smoothed de POI, atenuada pelo total (evita "diversidade" em
  células quase vazias).
- **Isolation** — `exp(-sum_POIs / 3)`, penalidade contínua.
- **Low connectivity** — `1 - minmax(road_density)`.

### 5. Smoothing espacial
POIs, landuse e densidade viária são propagados pelos vizinhos H3 em 3
anéis com decaimento 0.6 por anel. Isso simula o *catchment* de 1-2 quadras
ao redor: uma célula adjacente a um polo comercial recebe parte daquele
sinal.

### 6. Normalização
`robust_minmax` com winsorização no percentil 95 para cada feature
positiva → [0, 1]. Evita que um outlier (um shopping gigante) esmague as
demais células.

### 7. Combinação
```
raw = Σ (w_i · norm(feature_i))   -   Σ (p_j · penalty_j)
```

Para Macaé:

**Pesos positivos** (defaults, ajustáveis em YAML):
`food 1.6, shop 1.4, supermarket 1.3, pharmacy 1.1, fitness 1.0,
education 1.2, healthcare 1.0, office 1.0, bank 0.7, transport 1.1,
leisure 0.6, fuel 0.5, residential 1.0, commercial 1.2, mixed_use 1.5,
road_density 1.0, anchor_proximity 1.8`

**Penalidades**:
`unsuitable_landuse 2.2, industrial 0.4, isolation 0.9, low_connectivity 0.4`

### 8. Reescala final (0..100)

O `raw` passa por um **blend** de dois sinais para garantir ordenação
correta **e** boa distribuição visual:

```
physical = sqrt( (raw - min) / (p97 - min) )       # preserva física
rank_pct = rank percentile de raw                  # uniforme

score = 0.4 · physical + 0.6 · rank_pct            # blend
```

Isso evita o problema clássico de rodar este tipo de heurística em
polígonos grandes: sem o rank, ~80% das células (periferia vazia) caem no
mesmo bucket e o mapa vira dois tons. Com o blend, temos nuances contínuas
do 0 ao 100 e as células top continuam sendo as mais ativas.

### 9. Safeguards

- Células com mais de **60 %** de landuse inviável (água, mata, aeródromo,
  militar…) ficam **capadas em 15** (ficam sempre vermelhas), mesmo que
  um POI errado tenha sido mapeado dentro.

### 10. Classes (faixas de cor)

| faixa    | rótulo       | cor                     |
|----------|--------------|-------------------------|
| 0 – 20   | muito ruim   | vermelho escuro         |
| 20 – 40  | ruim         | laranja / salmão        |
| 40 – 60  | médio        | amarelo / palha         |
| 60 – 80  | bom          | verde-claro             |
| 80 – 100 | muito bom    | verde escuro            |

O colormap é **contínuo** (interpolação linear por faixa, ~10 stops),
então as células se distribuem em nuances e não apenas em 2 cores.

---

## Visualização

O HTML usa Folium/Leaflet com:

- **3 basemaps** selecionáveis (OpenStreetMap, Carto Positron, Carto Dark)
- **Overlay H3** com tooltip detalhado (score, classe, contribuições
  positivas e penalidades, h3 id)
- **HeatMap suavizado** opcional (camada separada, liga/desliga na UI)
- **Markers** das top-N áreas em cluster
- **Contorno da área de estudo** tracejado em preto
- **Legenda fixa** no canto inferior esquerdo
- **Controle de zoom / pan / escala**

Paleta: gradiente `RdYlGn` estendido com 10 stops para leitura suave.

---

## Testes

```bash
pytest -q
```

Cobre, offline:

- carregamento do config
- validade do polígono de estudo
- construção do grid H3 a partir de polígono pequeno
- bounds do `robust_minmax`
- intervalo e ordenação do `compute_score`
- labels de `classify`
- smoke test da renderização Folium (arquivo HTML gerado e não-vazio)

---

## Parametrizando para outra cidade

1. Copie `configs/macae.yaml` → `configs/<cidade>.yaml`
2. Ajuste:
   - `city.name` / `city.slug`
   - `study_area.bbox` (bbox amplo só para queries)
   - `study_area.polygon` (recorte efetivo — pontos `[lon, lat]`)
   - `map.center` (lat, lon padrão do zoom inicial)
   - `output.*` (nomes de arquivo)
3. `python main.py --city <cidade>`

Pesos e thresholds são os mesmos por default, mas você pode afinar em
`weights.*`.

---

## Limitações conhecidas

- **Cobertura OSM variável** — cidades brasileiras pequenas podem ter POIs
  subrepresentados. O pipeline não inventa; cai em "ruim" áreas pouco
  mapeadas. Trabalho manual pode completar lacunas editando o cache
  ou usando um polígono menor.
- **Sem IBGE / renda** — integração opcional não foi incluída para não
  travar o projeto em dependências externas. A densidade residencial é
  aproximada por cobertura OSM de buildings/landuse.
- **Sem GTFS / fluxo real** — `transport` usa só paradas mapeadas, não
  volume de viagens.
- **Heurística, não modelo preditivo** — os pesos são razoáveis por
  senso comercial; para um modelo treinado seria preciso histórico de
  instalações.
- **Overpass é público e tem limite de taxa** — o cache mitiga, mas a
  primeira execução pode levar ~1 min e em horários de pico a API pode
  retornar 429/504 (temos retries com backoff).

---

## Próximos upgrades

- Integrar grade censitária IBGE (setor censitário) para densidade
  populacional e renda média proxy.
- Usar GTFS (quando disponível) para peso real de transporte.
- Treinar pesos a partir de um histórico de vending machines instaladas
  com performance observada.
- Clusterização de zonas contíguas de alto score → microrregiões de
  prospecção (em vez de células isoladas).
- Export PNG estático com matplotlib + contextily para preview offline.
- Serviço FastAPI servindo tiles dinamicamente.

---

## Licenças de dados

- OpenStreetMap © contribuidores OSM — licença ODbL. Os dados derivados
  distribuídos daqui seguem o mesmo licenciamento; se publicar
  comercialmente, mantenha a atribuição.
