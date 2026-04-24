"""Assemble the 8 audit screenshots into:
   - contact_sheet.png  (4×2 mosaic)
   - contact_sheet.html (portable HTML viewer)
   - index.md           (short links)
   - visual_audit_report.pdf (one page per screenshot + interpretation)

Does not require network. Reads existing PNGs + their sibling .md files
in output/visual_audit/."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (Image as RLImage, Paragraph, SimpleDocTemplate,
                                Spacer)


AUDIT_DIR = Path("/home/user/VMTracker/output/visual_audit")
SHOTS = [
    "01_overview.png",
    "02_cluster_top_1.png",
    "03_cluster_top_2.png",
    "04_cluster_top_3.png",
    "05_mid_zone.png",
    "06_bad_area.png",
    "07_polygon_border.png",
    "08_transition.png",
]
COLS, ROWS = 4, 2
TILE_W, TILE_H = 800, 520


def _load_caption(png: Path) -> str:
    md = png.with_suffix(".md")
    if not md.exists():
        return png.stem
    text = md.read_text(encoding="utf-8").splitlines()
    for line in text:
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return png.stem


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail((w, h), Image.LANCZOS)
    canvas_img = Image.new("RGB", (w, h), (255, 255, 255))
    ox = (w - img.width) // 2
    oy = (h - img.height) // 2
    canvas_img.paste(img, (ox, oy))
    return canvas_img


def build_contact_sheet(out_path: Path) -> Path:
    margin = 10
    caption_h = 34
    total_w = margin + COLS * (TILE_W + margin)
    total_h = margin + ROWS * (TILE_H + caption_h + margin)
    sheet = Image.new("RGB", (total_w, total_h), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
        )
    except OSError:
        font = ImageFont.load_default()

    for i, name in enumerate(SHOTS):
        r, c = divmod(i, COLS)
        x = margin + c * (TILE_W + margin)
        y = margin + r * (TILE_H + caption_h + margin)
        p = AUDIT_DIR / name
        if not p.exists():
            draw.rectangle([x, y, x + TILE_W, y + TILE_H], fill=(220, 0, 0))
            draw.text((x + 10, y + 10), f"MISSING: {name}", fill="white", font=font)
            continue
        img = Image.open(p)
        tile = _fit(img, TILE_W, TILE_H)
        sheet.paste(tile, (x, y))
        caption = f"{i+1}. {_load_caption(p)}"
        draw.rectangle(
            [x, y + TILE_H, x + TILE_W, y + TILE_H + caption_h],
            fill=(30, 30, 30),
        )
        draw.text(
            (x + 8, y + TILE_H + 8), caption, fill="white", font=font,
        )

    sheet.save(out_path, "PNG", optimize=True)
    return out_path


def build_contact_html(contact_png: Path, out_path: Path) -> Path:
    tiles_html = []
    for i, name in enumerate(SHOTS):
        p = AUDIT_DIR / name
        caption = _load_caption(p) if p.exists() else "(missing)"
        tiles_html.append(f"""
        <figure style="margin:0;border:1px solid #ddd;background:#fff">
          <img src="{name}" style="width:100%;display:block" alt="{caption}"/>
          <figcaption style="padding:6px 10px;font:13px sans-serif;background:#222;color:#fff">
            {i+1}. {caption}
          </figcaption>
        </figure>""")
    html = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"/>
<title>Visual audit — Macaé Vending Heatmap</title>
<style>
  body {{ font-family: system-ui, sans-serif; background:#f3f3f3; margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 12px 0; }}
  .grid {{ display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; }}
  @media (min-width:1200px) {{ .grid {{ grid-template-columns:repeat(4, 1fr); }} }}
  p.note {{ font-size:12px; color:#555; }}
</style></head><body>
  <h1>Visual audit — Macaé Vending Heatmap</h1>
  <p class="note">
    Os mesmos PNG estão listados abaixo. Cada um tem um arquivo <code>.md</code>
    ao lado com o verdict esperado (TP / FP / TN / FN). Veja também
    <a href="{contact_png.name}">{contact_png.name}</a> (mosaico).
  </p>
  <div class="grid">{''.join(tiles_html)}</div>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


def build_index_md(out_path: Path) -> Path:
    lines = [
        "# Visual audit — Macaé Vending Heatmap",
        "",
        "Contatos:",
        "- `contact_sheet.png` — mosaico 4×2 das 8 screenshots",
        "- `contact_sheet.html` — viewer HTML portátil",
        "- `visual_audit_report.pdf` — PDF A4 com 1 página por shot",
        "",
        "## Shots",
    ]
    for i, name in enumerate(SHOTS):
        p = AUDIT_DIR / name
        if not p.exists():
            lines.append(f"- **{i+1}.** `{name}` — _MISSING_")
            continue
        caption = _load_caption(p)
        lines.append(f"- **{i+1}.** [{caption}]({name}) — metadata: [{Path(name).stem}.md]({Path(name).with_suffix('.md').name})")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def build_pdf(out_path: Path) -> Path:
    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(A4),
        leftMargin=28, rightMargin=28, topMargin=28, bottomMargin=28,
    )
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("<b>Visual audit — Macaé Vending Heatmap</b>", styles["Title"]))
    story.append(Paragraph(
        "8 screenshots reais do HTML principal (audit mode habilitado). "
        "Cada página traz o nome, o que deveria ser visto e a hipótese "
        "de verdict (TP/FP/TN/FN).",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 10))

    for i, name in enumerate(SHOTS):
        p = AUDIT_DIR / name
        if not p.exists():
            continue
        md = p.with_suffix(".md")
        body = md.read_text(encoding="utf-8") if md.exists() else ""
        title = _load_caption(p)
        story.append(Paragraph(f"<b>{i+1}. {title}</b>", styles["Heading2"]))
        # Scale image to fit roughly 70% page width
        try:
            with Image.open(p) as im:
                w, h = im.size
            scale = 680 / w
            img = RLImage(str(p), width=680, height=h * scale)
            story.append(img)
        except Exception:
            pass
        story.append(Spacer(1, 6))
        # Extract the two sections we wrote
        expectation = ""
        verdict = ""
        for sec, key in (
            ("O que deveria ser visto", "expectation"),
            ("Verdict (TP/FP/TN/FN — preencher após inspeção visual)", "verdict"),
        ):
            marker = f"## {sec}"
            if marker in body:
                chunk = body.split(marker, 1)[1].strip()
                # stop at next ## header
                if "\n## " in chunk:
                    chunk = chunk.split("\n## ", 1)[0]
                if key == "expectation":
                    expectation = chunk.strip()
                else:
                    verdict = chunk.strip()
        if expectation:
            story.append(Paragraph(f"<b>Expectativa:</b> {expectation}", styles["BodyText"]))
        if verdict:
            story.append(Paragraph(f"<b>Verdict hint:</b> <i>{verdict}</i>", styles["BodyText"]))
        story.append(Spacer(1, 14))

    doc.build(story)
    return out_path


def main() -> int:
    if not AUDIT_DIR.exists():
        print(f"audit dir missing: {AUDIT_DIR}")
        return 2
    contact_png = build_contact_sheet(AUDIT_DIR / "contact_sheet.png")
    contact_html = build_contact_html(contact_png, AUDIT_DIR / "contact_sheet.html")
    index_md = build_index_md(AUDIT_DIR / "index.md")
    pdf = build_pdf(AUDIT_DIR / "visual_audit_report.pdf")
    for p in (contact_png, contact_html, index_md, pdf):
        print(f"wrote {p}  ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
