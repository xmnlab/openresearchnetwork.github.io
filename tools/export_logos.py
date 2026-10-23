#!/usr/bin/env python3
"""Export the ORN brand kit from its outlined, palette-correct SVG master.

Requires CairoSVG, Pillow, pypdf and fonttools (plus system Cairo).
Run from any directory: python tools/export_logos.py
"""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import math
import re
import xml.etree.ElementTree as ET

import cairosvg
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, FloatObject
from fontTools.pens.basePen import BasePen
from fontTools.svgLib.path import parse_path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "theme/images/logos"
ICONS = ROOT / "theme/icons"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
PALETTE = {"gold": "#FFCC00", "teal": "#14A389", "ink": "#102723"}
MASTER = ET.parse(OUT / "source/logo-master.svg").getroot()
PATHS = {p.attrib["id"]: p for p in MASTER.findall(f"{{{SVG}}}path")}
LAYOUTS = {
    "logo": ("212 289 1128 422", 1128, 422),
    "logo-stacked": ("0 0 714 887", 714, 887),
    "symbol": ("212 280 438 438", 438, 438),
    "wordmark": ("664 289 673 422", 673, 422),
}
STYLES = ("color", "reverse", "black", "white")


def artwork(layout, style="color"):
    viewbox, width, height = LAYOUTS[layout]
    svg = ET.Element(f"{{{SVG}}}svg", {
        "viewBox": viewbox, "width": str(width), "height": str(height),
        "role": "img", "aria-labelledby": "title",
    })
    ET.SubElement(svg, f"{{{SVG}}}title", {"id": "title"}).text = "Open Research Network"
    for name, original in PATHS.items():
        if layout == "symbol" and name == "name":
            continue
        if layout == "wordmark" and name != "name":
            continue
        path = deepcopy(original)
        if style in ("black", "white"):
            path.set("fill", "#000000" if style == "black" else "#FFFFFF")
        elif style == "reverse" and name == "name":
            path.set("fill", "#FFFFFF")
        if layout == "logo-stacked":
            path.set("transform", "translate(-644 159)" if name == "name" else "translate(-74 -280)")
        svg.append(path)
    return ET.tostring(svg, encoding="utf-8", xml_declaration=True)


def png(svg, width, background=None):
    return cairosvg.svg2png(bytestring=svg, output_width=width, background_color=background)


def cmyk_pdf(rgb_pdf, destination):
    """Use explicit DeviceCMYK fills; preserve paths and pure K monochrome.

    This is a nominal process conversion, not an ICC press proof.
    """
    reader = PdfReader(BytesIO(rgb_pdf))
    writer = PdfWriter()
    for page in reader.pages:
        page = writer.add_page(page)
        content = ContentStream(page.get_contents(), writer)
        operations = []
        for operands, operator in content.operations:
            if operator in (b"rg", b"RG"):
                r, g, b = map(float, operands)
                k = 1 - max(r, g, b)
                cmyk = (0, 0, 0, 1) if k >= 1 else (
                    (1-r-k)/(1-k), (1-g-k)/(1-k), (1-b-k)/(1-k), k,
                )
                operands = [FloatObject(round(value, 6)) for value in cmyk]
                operator = b"k" if operator == b"rg" else b"K"
            operations.append((operands, operator))
        content.operations = operations
        page.replace_contents(content)
    writer.add_metadata({"/Title": "Open Research Network logo", "/Subject": "Outlined vector artwork; nominal DeviceCMYK process colors"})
    with destination.open("wb") as stream:
        writer.write(stream)


class EPSPen(BasePen):
    """Write actual cubic vector paths without a PostScript raster fallback."""
    def __init__(self):
        super().__init__(None)
        self.commands = []

    def _moveTo(self, p):
        self.commands.append(f"{p[0]:.3f} {p[1]:.3f} moveto")

    def _lineTo(self, p):
        self.commands.append(f"{p[0]:.3f} {p[1]:.3f} lineto")

    def _curveToOne(self, p1, p2, p3):
        self.commands.append(" ".join(f"{v:.3f}" for p in (p1,p2,p3) for v in p)+" curveto")

    def _closePath(self):
        self.commands.append("closepath")


def eps(svg_bytes, destination):
    svg = ET.fromstring(svg_bytes)
    x,y,w,h = map(float,svg.attrib["viewBox"].split())
    pw,ph = w*.75,h*.75
    lines = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {math.ceil(pw)} {math.ceil(ph)}",
             f"%%HiResBoundingBox: 0 0 {pw:.3f} {ph:.3f}",
             "%%Title: Open Research Network", "%%Pages: 1", "%%EndComments", "gsave",
             f"0 {ph:.3f} translate", "0.75 -0.75 scale", f"{-x} {-y} translate"]
    for path in svg.findall(f"{{{SVG}}}path"):
        color = path.attrib["fill"].lstrip("#")
        rgb = [int(color[i:i+2],16)/255 for i in (0,2,4)]
        lines.append("gsave")
        if "transform" in path.attrib:
            dx,dy = map(float,re.findall(r"-?\d+(?:\.\d+)?",path.attrib["transform"]))
            lines.append(f"{dx} {dy} translate")
        lines.append(" ".join(f"{v:.6f}" for v in rgb)+" setrgbcolor")
        pen = EPSPen()
        parse_path(path.attrib["d"],pen)
        lines.extend(["newpath", *pen.commands, "eofill", "grestore"])
    lines.extend(["grestore", "showpage", "%%EOF", ""])
    destination.write_text("\n".join(lines))


def export_kit():
    for directory in (OUT / "png", OUT / "print", ICONS):
        directory.mkdir(parents=True, exist_ok=True)
    for layout in LAYOUTS:
        for style in STYLES:
            name = layout if style == "color" else f"{layout}-{style}"
            svg = artwork(layout, style)
            (OUT / f"{name}.svg").write_bytes(svg)
            for width in (1024, 2048):
                (OUT / "png" / f"{name}-{width}.png").write_bytes(png(svg, width))
            if style in ("color", "black"):
                rgb_pdf = cairosvg.svg2pdf(bytestring=svg)
                (OUT / "print" / f"{name}.pdf").write_bytes(rgb_pdf)
                cmyk_pdf(rgb_pdf, OUT / "print" / f"{name}-cmyk.pdf")
                eps(svg, OUT / "print" / f"{name}.eps")

    # Keep the established PNG URL usable by external consumers.
    (OUT / "logo.png").write_bytes(png(artwork("logo"), 1024))

    symbol = artwork("symbol")
    (ICONS / "favicon.svg").write_bytes(symbol)
    for size in (16, 32, 48):
        (ICONS / f"favicon-{size}x{size}.png").write_bytes(png(symbol, size))
    favicon = Image.open(BytesIO(png(symbol, 256))).convert("RGBA")
    favicon.save(ICONS / "favicon.ico", sizes=[(16,16), (32,32), (48,48), (64,64)])
    for filename, size in (("apple-touch-icon.png", 180),
                           ("android-chrome-192x192.png", 192),
                           ("android-chrome-256x256.png", 256),
                           ("android-chrome-512x512.png", 512),
                           ("mstile-150x150.png", 150)):
        # A white field keeps the symbol legible on arbitrary launcher surfaces.
        (ICONS / filename).write_bytes(png(symbol, size, "#FFFFFF"))

    # Branded share image, with ample safe margins for social crops.
    card = Image.new("RGB", (1200, 630), "#F7FBFA")
    mark = Image.open(BytesIO(png(artwork("logo"), 1000))).convert("RGBA")
    card.paste(mark, ((1200-mark.width)//2, (630-mark.height)//2), mark)
    card.save(OUT / "social-card.png", optimize=True)

    # One-glance overview with real exports, not alternate artwork.
    overview = Image.new("RGB", (1600, 1050), "#F7FBFA")
    draw = ImageDraw.Draw(overview)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 24)
    except OSError:
        font = ImageFont.load_default(size=24)
    for index, (style, label) in enumerate((("color", "Full color"), ("reverse", "Reverse"),
                                             ("black", "Black"), ("white", "White"))):
        x, y = 30+(index%2)*790, 30+(index//2)*440
        background = "#102723" if style in ("reverse", "white") else "#FFFFFF"
        draw.rounded_rectangle((x,y,x+750,y+400), radius=16, fill=background)
        draw.text((x+30,y+25), label, fill="#FFFFFF" if style in ("reverse", "white") else "#102723", font=font)
        mark = Image.open(BytesIO(png(artwork("logo",style),690))).convert("RGBA")
        overview.paste(mark,(x+30,y+115),mark)
    for index,(name,hexcolor) in enumerate(PALETTE.items()):
        x=40+index*520
        draw.rounded_rectangle((x,940,x+90,1010),radius=12,fill=hexcolor)
        draw.text((x+110,960),f"{name.capitalize()}  {hexcolor}",font=font,fill="#102723")
    overview.save(OUT / "brand-overview.png", optimize=True)
    (OUT / "palette.json").write_text(json.dumps(PALETTE, indent=2)+"\n")
    print("Exported 16 outlined SVGs, 32 transparent PNGs, 8 RGB PDFs, 8 CMYK PDFs, 8 EPS files, icons and previews.")


if __name__ == "__main__":
    export_kit()
