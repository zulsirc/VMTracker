"""Markdown report generator."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Tiny markdown-table renderer so we don't depend on optional `tabulate`."""
    if df.empty:
        return "_(empty)_"
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    lines = [header, sep]
    for _, row in df.iterrows():
        vals = []
        for v in row.values:
            if isinstance(v, float):
                vals.append(f"{v:.3f}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_report(
    cfg: dict[str, Any],
    grid_stats: dict[str, Any],
    top_cells: pd.DataFrame,
    path: str | Path,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    city = cfg["city"]["name"]
    lines: list[str] = []
    lines.append(f"# Vending Machine Heatmap — {city}\n")
    lines.append("## Metodologia resumida\n")
    lines.append(
        "O mapa representa uma **heurística espacial** de potencial de "
        "prospecção para instalação de vending machines. O território é "
        "particionado em hexágonos H3 (~150-300m) e para cada célula "
        "calculamos:\n\n"
        "- **Sinais positivos**: densidade e diversidade de POIs (comércio, alimentação, "
        "farmácia, academia, educação, saúde, escritórios, transporte, lazer), "
        "cobertura residencial e comercial (landuse/buildings), densidade viária "
        "e diversidade de usos (entropia de Shannon sobre categorias).\n"
        "- **Penalidades**: fração de landuse inviável (água, mata, wetland, "
        "aeródromo, militar, agrícola), fração industrial, baixa conectividade "
        "viária e isolamento (poucos POIs nas redondezas).\n"
        "- **Suavização espacial**: cada célula incorpora parte do sinal dos "
        "seus vizinhos H3 (anéis 1 e 2 com decaimento), simulando raio de "
        "caminhada / catchment.\n"
        "- **Normalização**: min-max robusto winsorizado em p95 por feature.\n"
        "- **Combinação**: soma ponderada (pesos em `configs/macae.yaml`) - "
        "penalidades, reescalada para 0-100 com âncoras em p5/p98.\n"
        "- **Salvaguardas**: células com >60% landuse inviável ficam capadas "
        "em 12; células muito isoladas ficam capadas em 35 mesmo com POI forte.\n"
    )
    lines.append("\n## Área de estudo\n")
    poly = cfg["study_area"]["polygon"]
    lines.append(f"Polígono customizado (vértices: {len(poly)}), cobrindo a área "
                 "urbana consolidada do lado principal antes da Ponte da Barra. "
                 "Barra de Macaé (outro lado), aeroporto e periferia rural ficam "
                 "excluídos do recorte principal.\n")
    lines.append("\n## Estatísticas da malha\n")
    for k, v in grid_stats.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("\n## Top áreas (ranking)\n")
    cols = ["rank", "score", "class", "h3", "lat", "lon"]
    cols = [c for c in cols if c in top_cells.columns]
    lines.append(_df_to_markdown(top_cells[cols].head(cfg["output"]["top_n"])))
    lines.append("\n## Limitações\n")
    lines.append(
        "- Dados OSM: cobertura variável; POIs podem estar faltando em áreas "
        "onde o mapeamento comunitário é mais raso.\n"
        "- Dados socioeconômicos (IBGE, renda) não foram integrados por "
        "questões de disponibilidade direta; a densidade residencial é "
        "aproximada por cobertura de edifícios/landuse.\n"
        "- O score mede *potencial de área para prospecção* - não substitui "
        "visita técnica nem análise de host específico.\n"
        "- Ajustes finos de pesos em `configs/macae.yaml` mudam o resultado; "
        "a fórmula é transparente para iterar.\n"
    )
    lines.append("\n## Próximos upgrades\n")
    lines.append(
        "- Integrar grade censitária IBGE para densidade populacional/renda.\n"
        "- Incorporar dados de mobilidade (GTFS, paradas/viagens reais).\n"
        "- Pesos aprendidos a partir de histórico de máquinas já instaladas.\n"
        "- Clusterização de zonas contíguas de alto score para demarcar "
        "microrregiões de prospecção.\n"
    )
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
