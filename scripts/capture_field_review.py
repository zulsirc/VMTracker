"""Capture the field_review_map.html (lighter map for manual review)."""
import asyncio
import http.server
import socketserver
import threading
from pathlib import Path

from playwright.async_api import async_playwright

HTML = Path("/home/user/VMTracker/output/field_review_map.html").resolve()
OUT = Path("/home/user/VMTracker/output/visual_audit/field_review.png").resolve()
PORT = 8821


class _QH(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k): pass


async def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(
        ("127.0.0.1", PORT),
        lambda *a, **kw: _QH(*a, directory=str(HTML.parent), **kw),
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(
                headless=True,
                args=["--ignore-certificate-errors", "--disable-web-security", "--no-sandbox"],
            )
            ctx = await b.new_context(
                ignore_https_errors=True,
                viewport={"width": 1400, "height": 900},
            )
            page = await ctx.new_page()
            await page.goto(
                f"http://127.0.0.1:{PORT}/{HTML.name}",
                wait_until="load", timeout=60_000,
            )
            await page.wait_for_selector(".leaflet-container", timeout=30_000)
            try:
                await page.wait_for_function(
                    "document.querySelectorAll('.leaflet-tile-loaded').length >= 6",
                    timeout=30_000,
                )
            except Exception:
                pass
            # set view to center on the cluster cloud
            await page.evaluate(
                """() => {
                    let map = null;
                    for (const k of Object.keys(window)) {
                        if (k.startsWith('map_')) {
                            const v = window[k];
                            if (v && typeof v.setView === 'function') { map = v; break; }
                        }
                    }
                    if (map) map.setView([-22.405, -41.798], 14);
                }"""
            )
            await page.wait_for_timeout(4000)
            await page.screenshot(path=str(OUT), full_page=False)
            print(f"wrote {OUT}")
            await b.close()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
