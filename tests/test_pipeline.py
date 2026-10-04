from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from uuid import uuid4

from PIL import Image
from pypdf import PdfReader
from fastapi.testclient import TestClient

import memory_studio.app as webapp
from memory_studio.media import MediaCache
from memory_studio.pdf import render_project
from memory_studio.selection import add_months, build_cards, new_project
from memory_studio.storage import Store


class FakeImmich:
    def __init__(self, image: bytes):
        self.image_bytes = image
        self.calls: list[tuple[str, str]] = []

    def image(self, asset_id: str, size: str) -> bytes:
        self.calls.append((asset_id, size))
        return self.image_bytes


def test_thumbnails_then_previews_then_selected_originals(tmp_path: Path):
    output = io.BytesIO()
    Image.new("RGB", (2400, 2400), "#efaa90").save(output, format="JPEG")
    immich = FakeImmich(output.getvalue())
    cache = MediaCache(tmp_path)
    birthday = date(2025, 1, 12)
    assets = []
    for month in range(12):
        start = add_months(birthday, month)
        for offset in (3, 10):
            assets.append({"id": str(uuid4()), "type": "IMAGE", "localDateTime": start.replace(day=min(start.day + offset, 28)).isoformat(),
                           "livePhotoVideoId": str(uuid4()) if month == 0 else None,
                           "exifInfo": {"exifImageWidth": 2400, "exifImageHeight": 2400}})
    project = new_project("First year", "", birthday.isoformat(), None, [str(uuid4())], "warm moments", "peach")
    cards, warnings = build_cards(project, assets, immich, cache, None)
    assert not warnings
    assert len(cards) == 12
    assert all(card["asset_id"] and len(card["candidates"]) == 2 for card in cards)
    assert cards[0]["candidates"][0]["live_photo_video_id"]
    assert sum(size == "thumbnail" for _, size in immich.calls) == 24
    assert sum(size == "preview" for _, size in immich.calls) == 24
    assert not any(size == "original" for _, size in immich.calls)

    project["cards"] = cards
    pdf = render_project(project, immich, cache)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 3
    assert round(float(reader.pages[0].mediabox.width)) == 595
    assert sum(size == "original" for _, size in immich.calls) == 12


def test_live_photo_heic_still_prints_without_motion_download(tmp_path: Path):
    output = io.BytesIO()
    Image.new("RGB", (1800, 1800), "#dceabb").save(output, format="HEIF")
    immich = FakeImmich(output.getvalue())
    cache = MediaCache(tmp_path)
    project = new_project("Live Photo", "", "2025-01-01", None, [str(uuid4())], "", "sage")
    project["cards"] = [{"month": month, "label": f"Month {month}", "asset_id": str(uuid4()),
                         "live_photo_video_id": str(uuid4()), "crop_x": 0.5, "crop_y": 0.5, "caption": ""}
                        for month in range(1, 13)]
    pdf = render_project(project, immich, cache)
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 3
    assert all(size == "original" for _, size in immich.calls)
    assert len(immich.calls) == 12


def test_server_creates_reviews_and_exports_a_draft(tmp_path: Path, monkeypatch):
    from time import monotonic, sleep

    output = io.BytesIO()
    Image.new("RGB", (1200, 1200), "#dceabb").save(output, format="JPEG")
    immich = FakeImmich(output.getvalue())
    birthday = date(2025, 1, 1)
    album_ids = [str(uuid4()), str(uuid4())]
    assets = [{"id": str(uuid4()), "type": "IMAGE", "localDateTime": add_months(birthday, month).isoformat(),
               "width": 1200, "height": 1200} for month in range(12)]
    search_calls = []
    def search_year(*args):
        search_calls.append(args)
        return [*assets, assets[0]]
    immich.search_year = search_year
    immich.close = lambda: None
    monkeypatch.setattr(webapp, "store", Store(tmp_path))
    monkeypatch.setattr(webapp, "cache", MediaCache(tmp_path))
    monkeypatch.setattr(webapp, "_immich", lambda: immich)
    monkeypatch.setattr(webapp, "_vision", lambda: None)
    client = TestClient(webapp.app)

    assert client.post("/api/projects", json={"birth_date": birthday.isoformat(), "album_ids": [], "theme": "sage"}).status_code == 400
    created = client.post("/api/projects", json={"birth_date": birthday.isoformat(), "album_ids": album_ids, "theme": "sage"})
    assert created.status_code == 200
    assert created.json()["album_ids"] == album_ids
    project_id = created.json()["id"]
    deadline = monotonic() + 5
    while monotonic() < deadline:
        project = client.get(f"/api/projects/{project_id}").json()
        if project["status"] in {"ready", "error"}:
            break
        sleep(0.05)
    assert project["status"] == "ready", project.get("error")
    assert search_calls[0][3] == album_ids
    assert project["asset_count"] == 12
    first = project["cards"][0]
    assert client.patch(f"/api/projects/{project_id}/cards/1", json={"caption": "First smiles", "crop_x": 0.7}).status_code == 200
    assert client.get(f"/api/projects/{project_id}/images/{first['asset_id']}/preview").status_code == 200
    exported = client.get(f"/api/projects/{project_id}/export")
    assert exported.status_code == 200
    assert len(PdfReader(io.BytesIO(exported.content)).pages) == 3
    assert sum(size == "original" for _, size in immich.calls) == 12
