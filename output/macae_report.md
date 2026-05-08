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

Polígono customizado (vértices: 13), cobrindo a área urbana consolidada do lado principal antes da Ponte da Barra. Barra de Macaé (outro lado), aeroporto e periferia rural ficam excluídos do recorte principal.


## Estatísticas da malha

- **cells total**: 1942
- **score min**: 0.02
- **score mean**: 34.0
- **score median**: 24.05
- **score max**: 100.0
- **cells >= 60 (bom+)**: 447
- **cells >= 80 (muito bom)**: 222
- **POIs total**: 287
- **road segments**: 485

## Top áreas (ranking)

| rank | score | class | h3 | lat | lon |
| --- | --- | --- | --- | --- | --- |
| 1 | 100.000 | muito bom | 8aa8b1a20c9ffff | -22.399 | -41.798 |
| 2 | 99.985 | muito bom | 8aa8b1a20c97fff | -22.400 | -41.797 |
| 3 | 99.969 | muito bom | 8aa8b1a2626ffff | -22.399 | -41.797 |
| 4 | 99.954 | muito bom | 8aa8b1a20c87fff | -22.401 | -41.799 |
| 5 | 99.938 | muito bom | 8aa8b1a26267fff | -22.400 | -41.796 |
| 6 | 99.923 | muito bom | 8aa8b1a2634ffff | -22.401 | -41.796 |
| 7 | 99.907 | muito bom | 8aa8b1a20537fff | -22.398 | -41.798 |
| 8 | 99.892 | muito bom | 8aa8b1a20daffff | -22.404 | -41.800 |
| 9 | 99.876 | muito bom | 8aa8b1a2635ffff | -22.401 | -41.795 |
| 10 | 99.861 | muito bom | 8aa8b1a20ca7fff | -22.402 | -41.799 |
| 11 | 99.846 | muito bom | 8aa8b1a20d8ffff | -22.403 | -41.799 |
| 12 | 99.830 | muito bom | 8aa8b1a20d1ffff | -22.404 | -41.801 |
| 13 | 99.815 | muito bom | 8aa8b1a20d17fff | -22.405 | -41.800 |
| 14 | 99.799 | muito bom | 8aa8b1a26247fff | -22.399 | -41.795 |
| 15 | 99.784 | muito bom | 8aa8b1a20cb7fff | -22.401 | -41.798 |
| 16 | 99.768 | muito bom | 8aa8b1a26347fff | -22.402 | -41.795 |
| 17 | 99.753 | muito bom | 8aa8b1a26277fff | -22.400 | -41.795 |
| 18 | 99.737 | muito bom | 8aa8b1a20d87fff | -22.404 | -41.799 |
| 19 | 99.722 | muito bom | 8aa8b1a20d9ffff | -22.403 | -41.798 |
| 20 | 99.706 | muito bom | 8aa8b1a20da7fff | -22.405 | -41.799 |
| 21 | 99.691 | muito bom | 8aa8b1a2636ffff | -22.402 | -41.797 |
| 22 | 99.676 | muito bom | 8aa8b1a26357fff | -22.402 | -41.794 |
| 23 | 99.660 | muito bom | 8aa8b1a20c8ffff | -22.400 | -41.799 |
| 24 | 99.645 | muito bom | 8aa8b1a20d97fff | -22.403 | -41.797 |
| 25 | 99.629 | muito bom | 8aa8b1a20caffff | -22.401 | -41.800 |
| 26 | 99.614 | muito bom | 8aa8b1a20d07fff | -22.405 | -41.802 |
| 27 | 99.598 | muito bom | 8aa8b1a20db7fff | -22.405 | -41.798 |
| 28 | 99.583 | muito bom | 8aa8b1a26377fff | -22.403 | -41.795 |
| 29 | 99.567 | muito bom | 8aa8b1a26257fff | -22.399 | -41.794 |
| 30 | 99.552 | muito bom | 8aa8b1a2624ffff | -22.398 | -41.796 |
| 31 | 99.537 | muito bom | 8aa8b1a20d0ffff | -22.404 | -41.803 |
| 32 | 99.521 | muito bom | 8aa8b1a20c27fff | -22.403 | -41.802 |
| 33 | 99.506 | muito bom | 8aa8b1a26a4ffff | -22.406 | -41.800 |
| 34 | 99.490 | muito bom | 8aa8b1a2622ffff | -22.401 | -41.794 |
| 35 | 99.475 | muito bom | 8aa8b1a2620ffff | -22.400 | -41.793 |
| 36 | 99.459 | muito bom | 8aa8b1a26367fff | -22.403 | -41.796 |
| 37 | 99.444 | muito bom | 8aa8b1a20c07fff | -22.402 | -41.802 |
| 38 | 99.428 | muito bom | 8aa8b1a26a5ffff | -22.406 | -41.798 |
| 39 | 99.413 | muito bom | 8aa8b1a2630ffff | -22.403 | -41.793 |
| 40 | 99.398 | muito bom | 8aa8b1a2625ffff | -22.398 | -41.795 |

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
