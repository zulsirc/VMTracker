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

Polígono customizado (vértices: 12), cobrindo a área urbana consolidada do lado principal antes da Ponte da Barra. Barra de Macaé (outro lado), aeroporto e periferia rural ficam excluídos do recorte principal.


## Estatísticas da malha

- **cells total**: 357
- **score min**: 0.08
- **score mean**: 41.96
- **score median**: 30.0
- **score max**: 100.0
- **cells >= 60 (bom+)**: 84
- **cells >= 80 (muito bom)**: 45
- **POIs total**: 296
- **road segments**: 530

## Top áreas (ranking)

| rank | score | class | h3 | lat | lon |
| --- | --- | --- | --- | --- | --- |
| 1 | 100.000 | muito bom | 89a8b1a2637ffff | -22.402 | -41.795 |
| 2 | 99.916 | muito bom | 89a8b1a20cbffff | -22.401 | -41.799 |
| 3 | 99.832 | muito bom | 89a8b1a2627ffff | -22.399 | -41.795 |
| 4 | 99.748 | muito bom | 89a8b1a2623ffff | -22.401 | -41.792 |
| 5 | 99.664 | muito bom | 89a8b1a20dbffff | -22.404 | -41.799 |
| 6 | 99.580 | muito bom | 89a8b1a2053ffff | -22.397 | -41.798 |
| 7 | 99.496 | muito bom | 89a8b1a20c3ffff | -22.402 | -41.802 |
| 8 | 99.412 | muito bom | 89a8b1a20d3ffff | -22.405 | -41.802 |
| 9 | 99.328 | muito bom | 89a8b1a262fffff | -22.398 | -41.792 |
| 10 | 99.244 | muito bom | 89a8b1a20cfffff | -22.399 | -41.802 |
| 11 | 99.160 | muito bom | 89a8b1a26afffff | -22.405 | -41.796 |
| 12 | 99.049 | muito bom | 89a8b1a205bffff | -22.396 | -41.795 |
| 13 | 98.199 | muito bom | 89a8b1a2633ffff | -22.404 | -41.792 |
| 14 | 98.084 | muito bom | 89a8b1a26a7ffff | -22.407 | -41.799 |
| 15 | 97.947 | muito bom | 89a8b1a262bffff | -22.399 | -41.789 |
| 16 | 97.118 | muito bom | 89a8b1a20d7ffff | -22.404 | -41.805 |
| 17 | 96.957 | muito bom | 89a8b1a20c7ffff | -22.400 | -41.805 |
| 18 | 94.889 | muito bom | 89a8b1a2043ffff | -22.394 | -41.798 |
| 19 | 94.754 | muito bom | 89a8b1a263bffff | -22.402 | -41.789 |
| 20 | 94.614 | muito bom | 89a8b1a246fffff | -22.407 | -41.805 |
| 21 | 94.164 | muito bom | 89a8b1a2293ffff | -22.396 | -41.789 |
| 22 | 93.491 | muito bom | 89a8b1a2297ffff | -22.394 | -41.792 |
| 23 | 92.967 | muito bom | 89a8b1a246bffff | -22.408 | -41.802 |
| 24 | 92.511 | muito bom | 89a8b1a26abffff | -22.407 | -41.793 |
| 25 | 91.995 | muito bom | 89a8b1a2057ffff | -22.396 | -41.801 |
| 26 | 91.739 | muito bom | 89a8b1a208bffff | -22.402 | -41.808 |
| 27 | 90.868 | muito bom | 89a8b1a204bffff | -22.393 | -41.795 |
| 28 | 90.208 | muito bom | 89a8b1a201bffff | -22.397 | -41.805 |
| 29 | 90.027 | muito bom | 89a8b1a26a3ffff | -22.408 | -41.796 |
| 30 | 89.602 | muito bom | 89a8b1a2667ffff | -22.398 | -41.786 |
| 31 | 89.439 | muito bom | 89a8b1a209bffff | -22.405 | -41.808 |
| 32 | 88.706 | muito bom | 89a8b1a2013ffff | -22.399 | -41.808 |
| 33 | 88.413 | muito bom | 89a8b1a2607ffff | -22.405 | -41.789 |
| 34 | 87.620 | muito bom | 89a8b1a26b7ffff | -22.410 | -41.799 |
| 35 | 86.646 | muito bom | 89a8b1a2283ffff | -22.393 | -41.789 |
| 36 | 85.948 | muito bom | 89a8b1a229bffff | -22.395 | -41.786 |
| 37 | 85.172 | muito bom | 89a8b1a2677ffff | -22.401 | -41.786 |
| 38 | 84.952 | muito bom | 89a8b1a2287ffff | -22.391 | -41.792 |
| 39 | 84.588 | muito bom | 89a8b1a2467ffff | -22.408 | -41.808 |
| 40 | 82.858 | muito bom | 89a8b1a2463ffff | -22.410 | -41.805 |

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
