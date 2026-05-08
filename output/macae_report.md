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

Polígono customizado (vértices: 18), cobrindo a área urbana consolidada do lado principal antes da Ponte da Barra. Barra de Macaé (outro lado), aeroporto e periferia rural ficam excluídos do recorte principal.


## Estatísticas da malha

- **cells total**: 5892
- **score min**: 0.01
- **score mean**: 47.83
- **score median**: 30.0
- **score max**: 100.0
- **cells >= 60 (bom+)**: 1842
- **cells >= 80 (muito bom)**: 878
- **POIs total**: 394
- **road segments**: 1199

## Top áreas (ranking)

| rank | score | class | h3 | lat | lon |
| --- | --- | --- | --- | --- | --- |
| 1 | 100.000 | muito bom | 8aa8b1a201b7fff | -22.398 | -41.804 |
| 2 | 99.995 | muito bom | 8aa8b1a20c5ffff | -22.399 | -41.804 |
| 3 | 99.990 | muito bom | 8aa8b1a201a7fff | -22.398 | -41.805 |
| 4 | 99.985 | muito bom | 8aa8b1a20577fff | -22.397 | -41.801 |
| 5 | 99.980 | muito bom | 8aa8b1a20547fff | -22.396 | -41.801 |
| 6 | 99.975 | muito bom | 8aa8b1a20567fff | -22.397 | -41.802 |
| 7 | 99.969 | muito bom | 8aa8b1a20557fff | -22.396 | -41.800 |
| 8 | 99.964 | muito bom | 8aa8b1a20c47fff | -22.400 | -41.805 |
| 9 | 99.959 | muito bom | 8aa8b1a20187fff | -22.397 | -41.805 |
| 10 | 99.954 | muito bom | 8aa8b1a2050ffff | -22.397 | -41.799 |
| 11 | 99.949 | muito bom | 8aa8b1a20197fff | -22.397 | -41.803 |
| 12 | 99.944 | muito bom | 8aa8b1a20c57fff | -22.400 | -41.803 |
| 13 | 99.939 | muito bom | 8aa8b1a246dffff | -22.406 | -41.804 |
| 14 | 99.934 | muito bom | 8aa8b1a20a67fff | -22.397 | -41.820 |
| 15 | 99.929 | muito bom | 8aa8b1a20ccffff | -22.398 | -41.802 |
| 16 | 99.924 | muito bom | 8aa8b1a20d4ffff | -22.403 | -41.806 |
| 17 | 99.919 | muito bom | 8aa8b1a2056ffff | -22.396 | -41.803 |
| 18 | 99.913 | muito bom | 8aa8b1a2051ffff | -22.396 | -41.798 |
| 19 | 99.908 | muito bom | 8aa8b1a2055ffff | -22.395 | -41.801 |
| 20 | 99.903 | muito bom | 8aa8b1a201affff | -22.398 | -41.806 |
| 21 | 99.898 | muito bom | 8aa8b1a20c4ffff | -22.400 | -41.806 |
| 22 | 99.893 | muito bom | 8aa8b1a20a77fff | -22.396 | -41.819 |
| 23 | 99.888 | muito bom | 8aa8b1a2042ffff | -22.395 | -41.800 |
| 24 | 99.883 | muito bom | 8aa8b1a20c67fff | -22.402 | -41.805 |
| 25 | 99.878 | muito bom | 8aa8b1a20d67fff | -22.405 | -41.805 |
| 26 | 99.873 | muito bom | 8aa8b1a246d7fff | -22.407 | -41.803 |
| 27 | 99.868 | muito bom | 8aa8b1a20a47fff | -22.396 | -41.820 |
| 28 | 99.863 | muito bom | 8aa8b1a20467fff | -22.394 | -41.802 |
| 29 | 99.857 | muito bom | 8aa8b1a20d77fff | -22.404 | -41.804 |
| 30 | 99.852 | muito bom | 8aa8b1a20997fff | -22.405 | -41.807 |
| 31 | 99.847 | muito bom | 8aa8b1a2054ffff | -22.395 | -41.802 |
| 32 | 99.842 | muito bom | 8aa8b1a20477fff | -22.394 | -41.801 |
| 33 | 99.837 | muito bom | 8aa8b1a20d6ffff | -22.404 | -41.806 |
| 34 | 99.832 | muito bom | 8aa8b1a20097fff | -22.394 | -41.803 |
| 35 | 99.827 | muito bom | 8aa8b1a20a57fff | -22.395 | -41.819 |
| 36 | 99.822 | muito bom | 8aa8b1a20a0ffff | -22.396 | -41.818 |
| 37 | 99.817 | muito bom | 8aa8b1a2018ffff | -22.396 | -41.805 |
| 38 | 99.812 | muito bom | 8aa8b1a2468ffff | -22.407 | -41.803 |
| 39 | 99.807 | muito bom | 8aa8b1a20a6ffff | -22.396 | -41.821 |
| 40 | 99.801 | muito bom | 8aa8b1a2040ffff | -22.393 | -41.799 |

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
