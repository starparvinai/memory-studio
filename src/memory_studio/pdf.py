"""Four cuttable photo cards on each A4 PDF page."""

from __future__ import annotations

import io
from math import cos, pi, sin

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .immich import Immich
from .media import MediaCache

register_heif_opener()


MM = 72 / 25.4
THEMES = {
    "peach": ("#FFF3EC", "#E98779", "#6D433F"),
    "sage": ("#F0F6EE", "#83A58C", "#355A49"),
    "lavender": ("#F4F0FA", "#A795C8", "#514568"),
    "sunshine": ("#FFF9E8", "#E9B85E", "#66512D"),
}


def _hex(value: str):
    return colors.HexColor(value)


def _fitted(data: bytes, crop_x: float, crop_y: float) -> Image.Image:
    source = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return ImageOps.fit(source, (1800, 1800), method=Image.Resampling.LANCZOS, centering=(crop_x, crop_y))


def _star(pdf: canvas.Canvas, cx: float, cy: float, radius: float, color) -> None:
    path = pdf.beginPath()
    for point in range(10):
        angle = pi / 2 + point * pi / 5
        r = radius if point % 2 == 0 else radius * 0.48
        x, y = cx + cos(angle) * r, cy + sin(angle) * r
        (path.moveTo if point == 0 else path.lineTo)(x, y)
    path.close()
    pdf.setFillColor(color)
    pdf.drawPath(path, fill=1, stroke=0)


def _cut_marks(pdf: canvas.Canvas, x: float, y: float, width: float, height: float) -> None:
    pdf.setStrokeColor(colors.HexColor("#B5B1AC"))
    pdf.setLineWidth(0.5)
    length, space = 3 * MM, 1 * MM
    for corner_x, sign_x in ((x, -1), (x + width, 1)):
        for corner_y, sign_y in ((y, -1), (y + height, 1)):
            pdf.line(corner_x + sign_x * space, corner_y, corner_x + sign_x * (space + length), corner_y)
            pdf.line(corner_x, corner_y + sign_y * space, corner_x, corner_y + sign_y * (space + length))


def _text_fit(pdf: canvas.Canvas, text: str, max_width: float, start_size: float, minimum: float = 8) -> float:
    size = start_size
    while size > minimum and pdf.stringWidth(text, "Helvetica", size) > max_width:
        size -= 0.5
    return size


def render_project(project: dict, immich: Immich, cache: MediaCache) -> bytes:
    if len(project.get("cards", [])) != 12:
        raise ValueError("This draft is not ready to export")
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(project["title"])
    page_width, page_height = A4
    outer = 12 * MM
    gutter = 7 * MM
    card_width = (page_width - 2 * outer - gutter) / 2
    card_height = (page_height - 2 * outer - gutter) / 2
    background, accent, ink = [_hex(item) for item in THEMES.get(project.get("theme"), THEMES["peach"])]

    for index, card in enumerate(project["cards"]):
        slot = index % 4
        col, row = slot % 2, slot // 2
        x = outer + col * (card_width + gutter)
        y = page_height - outer - card_height - row * (card_height + gutter)
        pdf.setFillColor(background)
        pdf.roundRect(x, y, card_width, card_height, 9, fill=1, stroke=0)
        photo_x = x + 4 * MM
        photo_size = card_width - 8 * MM
        photo_y = y + card_height - 15 * MM - photo_size
        if card.get("asset_id"):
            data = cache.get(immich, card["asset_id"], "original")
            fitted = _fitted(data, float(card.get("crop_x", 0.5)), float(card.get("crop_y", 0.5)))
            pdf.drawImage(ImageReader(fitted), photo_x, photo_y, photo_size, photo_size, mask="auto")
        else:
            pdf.setFillColor(colors.white)
            pdf.roundRect(photo_x, photo_y, photo_size, photo_size, 5, fill=1, stroke=0)
            pdf.setFillColor(ink)
            pdf.setFont("Helvetica", 10)
            pdf.drawCentredString(x + card_width / 2, photo_y + photo_size / 2, "Add a photo")
        pdf.setFillColor(ink)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(x + 5 * MM, y + card_height - 10 * MM, card["label"])
        _star(pdf, x + card_width - 9 * MM, y + card_height - 8 * MM, 2.4 * MM, accent)
        caption = (card.get("caption") or "").strip().replace("\n", " ")
        if caption:
            size = _text_fit(pdf, caption, card_width - 10 * MM, 11)
            pdf.setFont("Helvetica", size)
            pdf.drawCentredString(x + card_width / 2, y + 13 * MM, caption)
        pdf.setStrokeColor(accent)
        pdf.setLineWidth(1)
        pdf.line(x + card_width / 2 - 11 * MM, y + 8 * MM, x + card_width / 2 + 11 * MM, y + 8 * MM)
        _cut_marks(pdf, x, y, card_width, card_height)
        if slot == 3:
            pdf.showPage()
    pdf.save()
    return output.getvalue()
