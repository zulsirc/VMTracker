"""Take screenshots of the generated Folium map at several zooms / regions.

Uses Playwright / Chromium headless. We serve the HTML over a local HTTP
server (so CDN cross-origin/cert handling works correctly) and wait for
tiles to render before capturing.
"""
from __future__ import annotations

import asyncio
import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

from playwright.async_api import async_playwright


HTML = Path("/home/user/VMTracker/output/macae_vending_heatmap.html").resolve()
OUT = Path("/home/user/VMTracker/output/screenshots").resolve()
OUT.mkdir(parents=True, exist_ok=True)
SERVE_DIR = HTML.parent
PORT = 8799


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args, **_kw):  # noqa: D401
        pass


def start_server(directory: Path, port: int) -> socketserver.TCPServer:
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(directory), **kw)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


# (filename, center_lat, center_lon, zoom, label)
SHOTS: list[tuple[str, float, float, int, str]] = [
    ("01_wide_overview.png",          -22.415, -41.795, 14, "wide overview of the study area"),
    ("02_zoom_granja_cavaleiros.png", -22.400, -41.792, 15, "zoom on Granja dos Cavaleiros / Glória commercial core"),
    ("03_zoom_mid_praia_campista.png",-22.425, -41.790, 15, "mid-range zone (Praia Campista)"),
    ("04_zoom_periphery_west.png",    -22.405, -41.820, 15, "peripheral west edge"),
    ("05_zoom_top_cluster.png",       -22.403, -41.795, 16, "top-cluster detail"),
    ("06_zoom_centro_imbetiba.png",   -22.392, -41.790, 15, "transition zone / centro-imbetiba edge"),
]


async def capture_one(page, lat: float, lon: float, zoom: int, out_path: Path) -> None:
    await page.evaluate(
        """
        ({lat, lon, zoom}) => {
            const container = document.querySelector('.leaflet-container');
            if (!container) throw new Error('no leaflet container');
            let map = null;
            for (const k of Object.keys(container)) {
                const v = container[k];
                if (v && typeof v.setView === 'function') { map = v; break; }
            }
            if (!map) {
                for (const k of Object.keys(window)) {
                    const v = window[k];
                    if (v && v._container === container && typeof v.setView === 'function') {
                        map = v; break;
                    }
                }
            }
            if (!map) throw new Error('no leaflet map instance found');
            map.setView([lat, lon], zoom);
            window.__map = map;
        }
        """,
        {"lat": lat, "lon": lon, "zoom": zoom},
    )
    # Wait for the tile layer to be reasonably loaded: the ratio of
    # loaded/total tiles should be high, then we let it paint for ~1s.
    try:
        await page.wait_for_function(
            """
            () => {
                const loaded = document.querySelectorAll('.leaflet-tile-loaded').length;
                const total  = document.querySelectorAll('.leaflet-tile').length;
                return total > 0 && loaded / total >= 0.95 && total >= 6;
            }
            """,
            timeout=30_000,
        )
    except Exception:
        pass
    await page.wait_for_timeout(3000)
    await page.screenshot(path=str(out_path), full_page=False)
    print(f"  wrote {out_path.name}")


async def main() -> int:
    if not HTML.exists():
        print(f"HTML not found: {HTML}", file=sys.stderr)
        return 2

    httpd = start_server(SERVE_DIR, PORT)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--ignore-certificate-errors",
                    "--disable-web-security",
                    "--no-sandbox",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1400, "height": 900},
                ignore_https_errors=True,
            )
            page = await context.new_page()
            page.on("pageerror", lambda err: print(f"[pageerror] {err}"))

            url = f"http://127.0.0.1:{PORT}/{HTML.name}"
            print(f"opening {url}")
            await page.goto(url, wait_until="load", timeout=60_000)
            await page.wait_for_selector(".leaflet-container", timeout=45_000)
            # wait for actual tiles to paint (soft)
            try:
                await page.wait_for_function(
                    "document.querySelectorAll('.leaflet-tile-loaded').length >= 4",
                    timeout=45_000,
                )
            except Exception:
                pass
            await page.wait_for_timeout(4000)

            for name, lat, lon, zoom, label in SHOTS:
                print(f"- {label}")
                await capture_one(page, lat, lon, zoom, OUT / name)

            await browser.close()
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
