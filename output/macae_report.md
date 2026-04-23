# Vending Machine Heatmap — Macaé

## Metodologia resumida

O mapa representa uma **heurística espacial** de potencial de prospecção para instalação de vending machines. O território é particionado em hexágonos H3 (~150-300m) e para cada célula calculamos:

- **Sinais positivos**: densidade e diversidade de POIs (comércio, alimentação, farmácia, academia, educação, saúde, escritórios, transporte, lazer), cobertura residencial e comercial (landuse/buildings), densidade viária e diversidade de usos (entropia de Shannon sobre categorias).
- **Penalidades**: fração de landuse inviável (água, mata, wetland, aeródromo, militar, agrícola), fração industrial, baixa conectividade viária e isolamento (poucos POIs nas redondezas).
- **Suavização espacial**: cada célula incorpora parte do sinal dos seus vizinhos H3 (anéis 1 e 2 com decaimento), simulando raio de caminhada / catchment.
- **Normalização**: min-max robusto winsorizado em p95 por feature.
- **Combinação**: soma ponderada (pesos em `configs/macae.yaml`) - penalidades, reescalada para 0-100 com âncoras em p5/p98.
- **Salvaguardas**: células com >60% landuse inviável ficam capadas em 12; células muito isoladas ficam capadas em 35 mesmo com POI forte.


## Área de estudo

Polígono customizado (vértices: 8), cobrindo a área urbana consolidada do lado principal antes da Ponte da Barra. Barra de Macaé (outro lado), aeroporto e periferia rural ficam excluídos do recorte principal.


## Estatísticas da malha

- **cells total**: 790
- **score min**: 0.08
- **score mean**: 40.68
- **score median**: 37.77
- **score max**: 99.85
- **cells >= 60 (bom+)**: 119
- **cells >= 80 (muito bom)**: 65
- **POIs total**: 350
- **road segments**: 665

## Top áreas (ranking)

| rank | score | class | h3 | lat | lon |
| --- | --- | --- | --- | --- | --- |
| 1 | 99.848 | muito bom | 89a8b1a20d3ffff | -22.405 | -41.802 |
| 2 | 99.392 | muito bom | 89a8b1a26afffff | -22.405 | -41.796 |
| 3 | 99.316 | muito bom | 89a8b1a26a7ffff | -22.407 | -41.799 |
| 4 | 98.937 | muito bom | 89a8b1a2633ffff | -22.404 | -41.792 |
| 5 | 98.785 | muito bom | 89a8b1a2297ffff | -22.394 | -41.792 |
| 6 | 98.481 | muito bom | 89a8b1a2293ffff | -22.396 | -41.789 |
| 7 | 98.405 | muito bom | 89a8b1a204bffff | -22.393 | -41.795 |
| 8 | 98.329 | muito bom | 89a8b1a263bffff | -22.402 | -41.789 |
| 9 | 98.176 | muito bom | 89a8b1a246bffff | -22.408 | -41.802 |
| 10 | 97.403 | muito bom | 89a8b1a2667ffff | -22.398 | -41.786 |
| 11 | 96.766 | muito bom | 89a8b1a26abffff | -22.407 | -41.793 |
| 12 | 96.349 | muito bom | 89a8b1a229bffff | -22.395 | -41.786 |
| 13 | 95.727 | muito bom | 89a8b1a26a3ffff | -22.408 | -41.796 |
| 14 | 95.555 | muito bom | 89a8b1a2283ffff | -22.393 | -41.789 |
| 15 | 95.214 | muito bom | 89a8b1a2287ffff | -22.391 | -41.792 |
| 16 | 95.117 | muito bom | 89a8b1a2607ffff | -22.405 | -41.789 |
| 17 | 94.769 | muito bom | 89a8b1a2677ffff | -22.401 | -41.786 |
| 18 | 94.604 | muito bom | 89a8b1a26b7ffff | -22.410 | -41.799 |
| 19 | 93.995 | muito bom | 89a8b1a22d7ffff | -22.393 | -41.783 |
| 20 | 93.549 | muito bom | 89a8b1a2463ffff | -22.410 | -41.805 |
| 21 | 93.380 | muito bom | 89a8b1a228bffff | -22.391 | -41.786 |
| 22 | 92.997 | muito bom | 89a8b1a22c7ffff | -22.390 | -41.783 |
| 23 | 92.877 | muito bom | 89a8b1a22c3ffff | -22.391 | -41.780 |
| 24 | 92.750 | muito bom | 89a8b1a22cfffff | -22.388 | -41.780 |
| 25 | 92.670 | muito bom | 89a8b1a266fffff | -22.396 | -41.783 |
| 26 | 92.051 | muito bom | 89a8b1a22cbffff | -22.390 | -41.777 |
| 27 | 91.467 | muito bom | 89a8b1a221bffff | -22.387 | -41.783 |
| 28 | 91.368 | muito bom | 89a8b1a2257ffff | -22.385 | -41.780 |
| 29 | 91.142 | muito bom | 89a8b1a2253ffff | -22.387 | -41.777 |
| 30 | 91.006 | muito bom | 89a8b1a22dbffff | -22.393 | -41.777 |
| 31 | 90.833 | muito bom | 89a8b1a228fffff | -22.390 | -41.789 |
| 32 | 90.297 | muito bom | 89a8b1a2017ffff | -22.397 | -41.811 |
| 33 | 90.115 | muito bom | 89a8b1a2003ffff | -22.396 | -41.808 |
| 34 | 89.981 | muito bom | 89a8b1a22d3ffff | -22.395 | -41.780 |
| 35 | 89.818 | muito bom | 89a8b1a2243ffff | -22.384 | -41.777 |
| 36 | 89.647 | muito bom | 89a8b1a225bffff | -22.385 | -41.774 |
| 37 | 89.549 | muito bom | 89a8b1a247bffff | -22.411 | -41.802 |
| 38 | 89.301 | muito bom | 89a8b1a26bbffff | -22.410 | -41.793 |
| 39 | 89.195 | muito bom | 89a8b1a3527ffff | -22.388 | -41.774 |
| 40 | 89.059 | muito bom | 89a8b1a204fffff | -22.391 | -41.798 |

## Limitações

- Dados OSM: cobertura variável; POIs podem estar faltando em áreas onde o mapeamento comunitário é mais raso.
- Dados socioeconômicos (IBGE, renda) não foram integrados por questões de disponibilidade direta; a densidade residencial é aproximada por cobertura de edifícios/landuse.
- O score mede *potencial de área para prospecção* - não substitui visita técnica nem análise de host específico.
- Ajustes finos de pesos em `configs/macae.yaml` mudam o resultado; a fórmula é transparente para iterar.


## Próximos upgrades

- Integrar grade censitária IBGE para densidade populacional/renda.
- Incorporar dados de mobilidade (GTFS, paradas/viagens reais).
- Pesos aprendidos a partir de histórico de máquinas já instaladas.
- Clusterização de zonas contíguas de alto score para demarcar microrregiões de prospecção.
