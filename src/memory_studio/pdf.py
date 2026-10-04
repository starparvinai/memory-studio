"""Four frameless photo prints on each A4 PDF page."""

from __future__ import annotations

import io
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
    return ImageOps.fit(source, (1200, 1750), method=Image.Resampling.LANCZOS, centering=(crop_x, crop_y))


def render_project(project: dict, immich: Immich, cache: MediaCache) -> bytes:
    if len(project.get("cards", [])) != 12:
        raise ValueError("This draft is not ready to export")
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(project["title"])
    page_width, page_height = A4
    outer = 8 * MM
    gutter = 4 * MM
    photo_width = (page_width - 2 * outer - gutter) / 2
    photo_height = (page_height - 2 * outer - gutter) / 2
    selected_cards = [card for card in project["cards"] if card.get("asset_id")]
    if not selected_cards:
        raise ValueError("Choose at least one photo before exporting")

    for index, card in enumerate(selected_cards):
        slot = index % 4
        col, row = slot % 2, slot // 2
        x = outer + col * (photo_width + gutter)
        y = page_height - outer - photo_height - row * (photo_height + gutter)
        data = cache.get(immich, card["asset_id"], "original")
        fitted = _fitted(data, float(card.get("crop_x", 0.5)), float(card.get("crop_y", 0.5)))
        pdf.drawImage(ImageReader(fitted), x, y, photo_width, photo_height)
        label = card.get("label") or f"Month {card['month']}"
        font_size = 10
        pdf.setFont("Helvetica-Bold", font_size)
        badge_width = pdf.stringWidth(label, "Helvetica-Bold", font_size) + 6 * MM
        badge_height = 9 * MM
        badge_x = x + photo_width - badge_width - 3 * MM
        badge_y = y + 3 * MM
        pdf.saveState()
        pdf.setFillColor(colors.black)
        pdf.setFillAlpha(0.58)
        pdf.roundRect(badge_x, badge_y, badge_width, badge_height, 2 * MM, fill=1, stroke=0)
        pdf.restoreState()
        pdf.setFillColor(colors.white)
        pdf.drawRightString(badge_x + badge_width - 3 * MM, badge_y + 3 * MM, label)
        if slot == 3 and index < len(selected_cards) - 1:
            pdf.showPage()
    pdf.save()
    return output.getvalue()
