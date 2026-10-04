"""Single-user web server for reviewable Immich print projects."""

from __future__ import annotations

import os
import threading
import io
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from PIL import Image

from .immich import Immich, ImmichError
from .media import MediaCache
from .pdf import THEMES, render_project
from .selection import add_months, asset_day, build_cards, new_project
from .storage import Store
from .vision import Vision


store = Store()
cache = MediaCache(store.root)
app = FastAPI(title="Memory Studio", docs_url=None, redoc_url=None)
_active: set[str] = set()
_active_lock = threading.Lock()


class SettingsUpdate(BaseModel):
    immich_url: str | None = None
    immich_api_key: str | None = None
    vision_provider: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None


class ProjectCreate(BaseModel):
    title: str = ""
    baby_name: str = ""
    birth_date: str
    album_ids: list[str] = Field(default_factory=list)
    album_id: str | None = None
    prompt: str = ""
    theme: str = "peach"
    analysis_depth: str = "balanced"


class CardUpdate(BaseModel):
    asset_id: str | None = None
    caption: str | None = None
    crop_x: float | None = Field(default=None, ge=0, le=1)
    crop_y: float | None = Field(default=None, ge=0, le=1)


def _immich() -> Immich:
    settings = store.settings()
    return Immich(settings["immich_url"], settings["immich_api_key"])


def _project(project_id: str) -> dict:
    project = store.project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _vision() -> Vision | None:
    settings = store.settings()
    provider = settings["vision_provider"]
    if provider == "none":
        return None
    if provider not in {"ollama", "openrouter"}:
        raise ValueError("Choose Ollama, OpenRouter, or no AI in Settings")
    model = settings["ollama_model"] if provider == "ollama" else settings["openrouter_model"]
    return Vision(provider, model, settings["openrouter_api_key"], settings["ollama_url"])


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/settings")
def get_settings():
    settings = store.settings().copy()
    settings["has_immich_key"] = bool(settings.pop("immich_api_key"))
    settings["has_openrouter_key"] = bool(settings.pop("openrouter_api_key"))
    return settings


@app.put("/api/settings")
def put_settings(update: SettingsUpdate):
    changes = update.model_dump(exclude_none=True)
    if "vision_provider" in changes and changes["vision_provider"] not in {"ollama", "openrouter", "none"}:
        raise HTTPException(400, "Invalid vision provider")
    store.save_settings(changes)
    return get_settings()


@app.get("/api/albums")
def albums():
    try:
        immich = _immich()
        try:
            return immich.albums()
        finally:
            immich.close()
    except ImmichError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/projects")
def projects():
    return store.list_projects()


@app.post("/api/projects")
def create_project(request: ProjectCreate):
    try:
        if request.theme not in THEMES:
            raise ValueError("Unknown theme")
        album_ids = list(dict.fromkeys([*request.album_ids, *([request.album_id] if request.album_id else [])]))
        if not album_ids:
            raise ValueError("Choose at least one Immich album")
        for album_id in album_ids:
            UUID(album_id)
        project = new_project(request.title, request.baby_name, request.birth_date, None,
                              album_ids, request.prompt, request.theme, request.analysis_depth)
        project["status"] = "new"
        store.save_project(project)
        _start_build(project["id"])
        return project
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return _project(project_id)


def _build(project_id: str) -> None:
    try:
        project = _project(project_id)
        project["status"], project["error"] = "building", None
        project["build_started_at"] = datetime.now(timezone.utc).isoformat()
        def progress(done: int, total: int, stage: str):
            project["progress"] = {"done": done, "total": total, "stage": stage,
                                   "updated_at": datetime.now(timezone.utc).isoformat()}
            store.save_project(project)
        progress(0, 1, "Connecting to Immich")
        immich = _immich()
        try:
            birthday = datetime.fromisoformat(project["birth_date"]).date()
            end = add_months(birthday, 12)
            # Search a wider UTC boundary, then assign months using each asset's local capture date.
            from datetime import timedelta
            album_ids = project.get("album_ids") or [project["album_id"]]
            assets = immich.search_year((birthday - timedelta(days=2)).isoformat(),
                                        (end + timedelta(days=2)).isoformat(), None, album_ids, progress)
            assets = list({asset["id"]: asset for asset in assets if (day := asset_day(asset)) and birthday <= day < end}.values())
            project["asset_count"] = len(assets)
            if not assets:
                project["cards"] = []
                project["status"] = "empty"
                project["error"] = "No photos match the selected albums during the first 12 months after the birth date. Check the birth date and album choices, then refresh from Immich."
                progress(1, 1, "No matching photos found")
                return
            progress(0, len(assets), f"Found {len(assets)} photos · preparing thumbnails")
            cards, warnings = build_cards(project, assets, immich, cache, _vision(), progress)
            project["cards"] = cards
            project["warnings"] = warnings
            project["status"] = "ready"
            project["last_sync_at"] = datetime.now(timezone.utc).isoformat()
            project["updated_at"] = project["last_sync_at"]
            progress(12, 12, "Ready to review")
        finally:
            immich.close()
    except Exception as exc:
        project = store.project(project_id)
        if project:
            project["status"] = "error"
            project["error"] = str(exc)
            store.save_project(project)
    finally:
        with _active_lock:
            _active.discard(project_id)


def _start_build(project_id: str):
    with _active_lock:
        if project_id in _active:
            raise HTTPException(409, "This project is already building")
        _active.add(project_id)
    threading.Thread(target=_build, args=(project_id,), daemon=True).start()


@app.post("/api/projects/{project_id}/build")
def rebuild(project_id: str):
    _project(project_id)
    _start_build(project_id)
    return {"status": "building"}


@app.patch("/api/projects/{project_id}/cards/{month}")
def update_card(project_id: str, month: int, update: CardUpdate):
    project = _project(project_id)
    if project["status"] != "ready" or month < 1 or month > 12:
        raise HTTPException(409, "Draft is not ready")
    card = project["cards"][month - 1]
    if update.asset_id is not None:
        if update.asset_id not in {candidate["id"] for candidate in card["candidates"]}:
            raise HTTPException(400, "Choose one of the displayed alternatives")
        card["asset_id"] = update.asset_id
        card["photo_locked"] = True
        card["reason"] = "Chosen by you"
    if update.caption is not None:
        card["caption"] = update.caption.strip()[:140]
    if update.crop_x is not None:
        card["crop_x"] = update.crop_x
    if update.crop_y is not None:
        card["crop_y"] = update.crop_y
    project["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.save_project(project)
    return card


@app.get("/api/projects/{project_id}/images/{asset_id}/{size}")
def project_image(project_id: str, asset_id: str, size: str):
    project = _project(project_id)
    allowed = {candidate["id"] for card in project.get("cards", []) for candidate in card["candidates"]}
    allowed.update(card["asset_id"] for card in project.get("cards", []) if card.get("asset_id"))
    if size not in {"thumbnail", "preview"} or asset_id not in allowed:
        raise HTTPException(404, "Image not in this draft")
    try:
        immich = _immich()
        try:
            data = cache.get(immich, asset_id, size)
        finally:
            immich.close()
        image_format = Image.open(io.BytesIO(data)).format
        media_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "HEIF": "image/heif"}.get(image_format, "application/octet-stream")
        return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
    except (ImmichError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str):
    project = _project(project_id)
    if project["status"] != "ready":
        raise HTTPException(409, "Draft is not ready")
    try:
        immich = _immich()
        try:
            data = render_project(project, immich, cache)
        finally:
            immich.close()
        return Response(data, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="memory-studio-{project_id}.pdf"'})
    except Exception as exc:
        raise HTTPException(502, f"Could not export PDF: {exc}") from exc


def main():
    import uvicorn
    uvicorn.run("memory_studio.app:app", host=os.environ.get("MEMORY_STUDIO_HOST", "127.0.0.1"),
                port=int(os.environ.get("MEMORY_STUDIO_PORT", "8765")))


if __name__ == "__main__":
    main()
