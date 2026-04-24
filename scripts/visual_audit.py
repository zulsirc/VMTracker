"""Visual-audit pack:
- 8 screenshots covering overview / top-3 clusters / mid / bad / border / transition
- per-shot markdown explaining what should be seen and the verdict
   (true positive / false positive / true negative / false negative).
"""
from __future__ import annotations

import asyncio
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright


HTML = Path("/home/user/VMTracker/output/macae_vending_heatmap.html").resolve()
SHORTLIST = Path("/home/user/VMTracker/output/field_visit_shortlist.csv").resolve()
SPATIAL = Path("/home/user/VMTracker/output/audit/spatial_validation.csv").resolve()
OUT = Path("/home/user/VMTracker/output/visual_audit").resolve()
OUT.mkdir(parents=True, exist_ok=True)
PORT = 8801


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_a, **_k): pass


def start_server(directory: Path, port: int) -> socketserver.TCPServer:
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(directory), **kw)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ----------------------------------------------------------------------------
# Build per-shot specs from real data
# ----------------------------------------------------------------------------
def build_shots() -> list[dict]:
    short = pd.read_csv(SHORTLIST)
    spv = pd.read_csv(SPATIAL)

    # 1) overview
    shots = [{
        "name": "01_overview.png",
        "lat": -22.412,
        "lon": -41.797,
        "zoom": 14,
        "label": "Visão geral da cidade (recorte completo)",
        "expectation": (
            "Polígono inteiro visível com gradiente do vermelho (SW) ao verde (NE). "
            "Top clusters numerados 1-10 sobre as áreas verdes. Costa hugged pela borda."
        ),
        "verdict_hint": "TP global: gradiente coerente com a geografia urbana de Macaé sul.",
    }]

    # 2-4) top 3 clusters
    for i, row in short.head(3).iterrows():
        shots.append({
            "name": f"0{2+i}_cluster_top_{int(row['cluster_rank'])}.png",
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "zoom": 16,
            "label": f"Top cluster #{int(row['cluster_rank'])} — {row['bairro_aproximado']}",
            "expectation": (
                f"Cluster #{int(row['cluster_rank'])} ({int(row['n_cells'])} células, "
                f"raio ~{int(row['raio_m'])}m, score médio {row['score_cluster']:.0f}). "
                f"Sinais: {row['principais_sinais']}. "
                f"Esperado: ruas com comércio ativo visíveis sob o overlay verde, "
                f"label '{int(row['cluster_rank'])}' centrado no cluster."
            ),
            "verdict_hint": (
                "TP esperado: área comercial real. Verificar se a cor verde "
                "coincide com o tecido urbano denso visível no basemap."
            ),
        })

    # 5) middle band — pick a cell with class=médio
    mid = spv[(spv["score_final"] >= 40) & (spv["score_final"] < 60)]
    mid = mid.sort_values("score_final", ascending=False).head(1)
    if not mid.empty:
        r = mid.iloc[0]
        shots.append({
            "name": "05_mid_zone.png",
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "zoom": 16,
            "label": "Faixa média (40-60) — transição",
            "expectation": (
                f"Célula score {r['score_final']:.0f} (classe {r['classe_final']}); "
                f"direct={r['direct_activity_score']:.0f} inherited={r['neighborhood_inherited_score']:.0f}. "
                "Esperado: cor amarela/clara com basemap mostrando residencial moderado, "
                "alguma rua arterial, sem aglomeração comercial densa."
            ),
            "verdict_hint": (
                "TP se for residencial com pouco comércio; FP se for "
                "área obviamente sem nada (mato/lote vazio)."
            ),
        })
    else:
        shots.append({"name": "05_mid_zone.png", "lat": -22.42, "lon": -41.79, "zoom": 16,
                      "label": "Faixa média", "expectation": "—", "verdict_hint": "—"})

    # 6) bad area
    bad = spv.sort_values("score_final").head(20)
    # pick one not at extreme polygon corner
    cand = bad[(bad["lat"].between(-22.46, -22.40)) & (bad["lon"].between(-41.83, -41.79))].head(1)
    if cand.empty:
        cand = bad.head(1)
    r = cand.iloc[0]
    shots.append({
        "name": "06_bad_area.png",
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "zoom": 16,
        "label": "Área classificada ruim",
        "expectation": (
            f"Célula score {r['score_final']:.1f}, raw_unsuitable_frac={r['raw_unsuitable_frac']:.2f}. "
            "Esperado: cor vermelha sob basemap mostrando área de baixíssima atividade "
            "(periferia, lote vazio, ou landuse natural)."
        ),
        "verdict_hint": (
            "TN se for visivelmente área inviável; FN se houver comércio "
            "que o OSM simplesmente não mapeou."
        ),
    })

    # 7) polygon border
    shots.append({
        "name": "07_polygon_border.png",
        "lat": -22.385,
        "lon": -41.795,
        "zoom": 15,
        "label": "Borda norte do polígono (perto da Ponte da Barra)",
        "expectation": (
            "A linha tracejada preta do polígono visível atravessando o mapa. "
            "Acima dela = fora do recorte (não analisado). Abaixo = células coloridas. "
            "Esperado: corte limpo no rio/centro."
        ),
        "verdict_hint": (
            "TP: validar que o recorte não foi 'contaminado' por células do "
            "outro lado da Ponte da Barra ou área do aeroporto."
        ),
    })

    # 8) strong transition
    shots.append({
        "name": "08_transition.png",
        "lat": -22.413,
        "lon": -41.815,
        "zoom": 15,
        "label": "Transição forte verde→vermelho (oeste-leste)",
        "expectation": (
            "Lateral oeste em vermelho (Virgem Santa / borda), lateral leste "
            "em amarelo/verde (chegando em Bosque Azul / Glória). Gradiente claro."
        ),
        "verdict_hint": (
            "TP: a transição deve coincidir com mudança real no tecido urbano "
            "(rua/avenida arterial separando densidades)."
        ),
    })
    return shots


# ----------------------------------------------------------------------------
# Capture
# ----------------------------------------------------------------------------
_FIND_MAP_JS = """
() => {
    if (window.__theMap && typeof window.__theMap.setView === 'function') return true;
    // Search container's own keys (Leaflet attaches there in some folium versions)
    const c = document.querySelector('.leaflet-container');
    if (c) {
        for (const k of Object.keys(c)) {
            const v = c[k];
            if (v && typeof v.setView === 'function') {
                window.__theMap = v;
                return true;
            }
        }
    }
    // Fallback: scan window for an object whose _container matches
    for (const k of Object.keys(window)) {
        try {
            const v = window[k];
            if (v && v._container === c && typeof v.setView === 'function') {
                window.__theMap = v;
                return true;
            }
        } catch (e) {}
    }
    // Folium also exports map_<hash> on window directly
    for (const k of Object.keys(window)) {
        if (k.startsWith('map_')) {
            const v = window[k];
            if (v && typeof v.setView === 'function') {
                window.__theMap = v;
                return true;
            }
        }
    }
    return false;
}
"""


async def capture_one(page, lat, lon, zoom, out_path):
    found = await page.evaluate(_FIND_MAP_JS)
    if not found:
        raise RuntimeError("map not found")
    await page.evaluate(
        """({lat, lon, zoom}) => { window.__theMap.setView([lat, lon], zoom); }""",
        {"lat": lat, "lon": lon, "zoom": zoom},
    )
    try:
        await page.wait_for_function(
            "document.querySelectorAll('.leaflet-tile-loaded').length / "
            "Math.max(1,document.querySelectorAll('.leaflet-tile').length) >= 0.95 "
            "&& document.querySelectorAll('.leaflet-tile').length >= 6",
            timeout=20_000,
        )
    except Exception:
        pass
    await page.wait_for_timeout(2500)
    await page.screenshot(path=str(out_path), full_page=False)


def write_metadata(shot: dict, png_path: Path) -> Path:
    md = png_path.with_suffix(".md")
    md.write_text(
        f"# {shot['label']}\n\n"
        f"![]({png_path.name})\n\n"
        f"- **lat / lon / zoom**: {shot['lat']:.5f}, {shot['lon']:.5f}, z={shot['zoom']}\n\n"
        f"## O que deveria ser visto\n{shot['expectation']}\n\n"
        f"## Verdict (TP/FP/TN/FN — preencher após inspeção visual)\n"
        f"_{shot['verdict_hint']}_\n",
        encoding="utf-8",
    )
    return md


async def main():
    if not HTML.exists():
        print("HTML missing", file=sys.stderr); return 2
    httpd = start_server(HTML.parent, PORT)
    try:
        shots = build_shots()
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--ignore-certificate-errors", "--disable-web-security", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                viewport={"width": 1400, "height": 900},
                ignore_https_errors=True,
            )
            page = await ctx.new_page()
            url = f"http://127.0.0.1:{PORT}/{HTML.name}"
            print(f"opening {url}")
            await page.goto(url, wait_until="load", timeout=60_000)
            await page.wait_for_selector(".leaflet-container", timeout=45_000)
            try:
                await page.wait_for_function(
                    "document.querySelectorAll('.leaflet-tile-loaded').length >= 4",
                    timeout=30_000,
                )
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            # Resolve the map instance once and stash it for re-use.
            ok = await page.evaluate(_FIND_MAP_JS)
            print(f"map detected: {ok}")
            # Toggle on Audit Mode automatically (presses the button we injected)
            try:
                await page.evaluate("window._auditOn && window._auditOn()")
                await page.wait_for_timeout(1500)
            except Exception:
                pass

            for shot in shots:
                print(f"- {shot['label']}")
                png = OUT / shot["name"]
                await capture_one(page, shot["lat"], shot["lon"], shot["zoom"], png)
                write_metadata(shot, png)
            await browser.close()

        # Index file
        idx_lines = [
            "# Visual audit pack",
            "",
            "Each shot has a sibling `.md` with what should be seen and the verdict hint.",
            "",
        ]
        for s in shots:
            idx_lines.append(f"- **{s['label']}** — `{s['name']}` ([metadata]({Path(s['name']).with_suffix('.md').name}))")
        (OUT / "INDEX.md").write_text("\n".join(idx_lines), encoding="utf-8")
        print(f"\nVisual audit pack ready in {OUT}/")
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
