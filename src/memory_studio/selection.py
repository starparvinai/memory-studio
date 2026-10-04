"""Age windows and reviewable photo selection."""

from __future__ import annotations

import calendar
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from typing import Callable

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .face_detection import face_widths
from .immich import Immich
from .media import MediaCache
from .vision import Vision, VisionError


SELECTION_VERSION = 2


def add_months(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def month_window(birthday: date, month: int) -> tuple[date, date]:
    """Month 1 means birth up to (but excluding) the first monthly anniversary."""
    if month < 1 or month > 12:
        raise ValueError("Month must be between 1 and 12")
    return add_months(birthday, month - 1), add_months(birthday, month)


def asset_day(asset: dict) -> date | None:
    for key in ("localDateTime", "fileCreatedAt"):
        raw = asset.get(key)
        if raw:
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                pass
    return None


def _resolution(asset: dict) -> int:
    exif = asset.get("exifInfo") or {}
    width = exif.get("exifImageWidth") or asset.get("width") or 0
    height = exif.get("exifImageHeight") or asset.get("height") or 0
    return int(width) * int(height)


def _score(asset: dict, middle: date) -> float:
    day = asset_day(asset)
    distance = abs((day - middle).days) if day else 100
    pixels = _resolution(asset)
    return (100 if asset.get("isFavorite") else 0) + min(pixels / 1_000_000, 20) - distance * 0.2


def _candidate_data(asset: dict) -> dict:
    day = asset_day(asset)
    return {
        "id": asset["id"],
        "date": day.isoformat() if day else None,
        "favorite": bool(asset.get("isFavorite")),
        "width": int((asset.get("exifInfo") or {}).get("exifImageWidth") or asset.get("width") or 0),
        "height": int((asset.get("exifInfo") or {}).get("exifImageHeight") or asset.get("height") or 0),
        "filename": asset.get("originalFileName", ""),
        "live_photo_video_id": asset.get("livePhotoVideoId"),
    }


def _image_quality(data: bytes) -> float:
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
        image.thumbnail((256, 256))
        brightness = ImageStat.Stat(image).mean[0]
        contrast = ImageStat.Stat(image).stddev[0]
        edges = ImageStat.Stat(image.filter(ImageFilter.FIND_EDGES)).stddev[0]
        # Edges from bars, toys, and foliage should not dominate the shortlist.
        return min(contrast, 60) * 0.35 + min(edges, 70) * 0.08 - abs(brightness - 125) * 0.12
    except Exception:
        return -100


def _visual_shortlist(items: list[dict], thumbnails: dict[str, bytes], start: date, middle: date,
                      faces: dict[str, float]) -> list[dict]:
    def shortlist_score(item: dict) -> float:
        base = _score(item, middle) * 0.1 + _image_quality(thumbnails[item["id"]])
        if not faces:
            return base
        width = faces.get(item["id"], 0)
        return min(width * 100, 40) + base * 0.3 - (8 if width == 0 else 0)

    scored = sorted(items, key=shortlist_score, reverse=True)
    selected = scored[:12]
    # Temporal spread stops a burst of near-identical photos crowding out the month.
    for quarter in range(4):
        group = [item for item in scored if asset_day(item) and min(3, (asset_day(item) - start).days // 8) == quarter]
        if group and group[0] not in selected:
            selected.append(group[0])
    for item in scored:
        if item.get("isFavorite") and item not in selected and len(selected) < 24:
            selected.append(item)
    for item in scored:
        if len(selected) >= 24:
            break
        if item not in selected:
            selected.append(item)
    return selected[:24]


def build_cards(project: dict, assets: list[dict], immich: Immich, cache: MediaCache,
                vision: Vision | None, progress: Callable[[int, int, str], None] | None = None) -> tuple[list[dict], list[str]]:
    birthday = date.fromisoformat(project["birth_date"])
    previous = {card["month"]: card for card in project.get("cards", [])}
    warnings: list[str] = []
    cards: list[dict] = []
    total = len(assets)
    thumbnails: dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(cache.get, immich, asset["id"], "thumbnail"): asset["id"] for asset in assets}
        for index, future in enumerate(as_completed(futures), 1):
            asset_id = futures[future]
            try:
                thumbnails[asset_id] = future.result()
            except Exception as exc:
                warnings.append(f"Could not read thumbnail for {asset_id}: {exc}")
            if progress and (index % 10 == 0 or index == total):
                progress(index, total, "Downloading small thumbnails")
    faces: dict[str, float] = {}
    if vision and thumbnails:
        if progress:
            progress(0, total, "Checking face prominence in cached thumbnails")
        faces = face_widths({asset_id: cache.root / "thumbnail" / asset_id for asset_id in thumbnails}, cache.root.parent)
    for month in range(1, 13):
        if progress:
            progress(month - 1, 12, f"Month {month} of 12 · finding candidates")
        start, end = month_window(birthday, month)
        middle = start + (end - start) / 2
        matches = [asset for asset in assets if asset["id"] in thumbnails and (day := asset_day(asset)) and start <= day < end]
        seen: set[str] = set()
        unique = []
        for asset in sorted(matches, key=lambda item: _score(item, middle), reverse=True):
            key = asset.get("duplicateId") or asset.get("checksum") or asset["id"]
            if key not in seen:
                seen.add(key)
                unique.append(asset)
        digest = hashlib.sha256(json.dumps(
            [SELECTION_VERSION, [(item["id"], item.get("checksum"), item.get("updatedAt")) for item in unique]],
            sort_keys=True,
        ).encode()).hexdigest()
        old = previous.get(month, {})
        shortlist = _visual_shortlist(unique, thumbnails, start, middle, faces) if unique else []
        shortlist = shortlist[:24 if project.get("analysis_depth") == "thorough" else 16]
        selected = old.get("asset_id") if old.get("photo_locked") else None
        reason = old.get("reason", "") if selected else ""
        if not selected and old.get("source_digest") == digest and old.get("asset_id"):
            selected = old["asset_id"]
            reason = old.get("reason", "")
        ranked_items = shortlist[:]
        if not selected and shortlist:
            finalists = shortlist[:6]
            if vision:
                try:
                    batch_winners = []
                    for offset in range(0, len(shortlist), 8):
                        batch = shortlist[offset:offset + 8]
                        if progress:
                            progress(month - 1, 12, f"Month {month} of 12 · comparing thumbnails with AI")
                        ranked, _ = vision.rank(month, [(item["id"], thumbnails[item["id"]]) for item in batch])
                        batch_winners.extend(ranked[:2])
                    finalists = [next(item for item in shortlist if item["id"] == asset_id) for asset_id in batch_winners]
                except VisionError as exc:
                    warnings.append(f"Month {month}: thumbnail AI ranking failed ({exc}).")
            previews = []
            if progress:
                progress(month - 1, 12, f"Month {month} of 12 · loading previews")
            for item in finalists:
                try:
                    previews.append((item["id"], cache.get(immich, item["id"], "preview")))
                except Exception as exc:
                    warnings.append(f"Month {month}: preview unavailable for {item['id']} ({exc}).")
            if vision and previews:
                final_ids = [asset_id for asset_id, _ in previews]
                if len(previews) > 1:
                    try:
                        if progress:
                            progress(month - 1, 12, f"Month {month} of 12 · comparing final photos with AI")
                        final_ids, _ = vision.rank(month, previews)
                    except VisionError as exc:
                        warnings.append(f"Month {month}: preview AI ranking failed ({exc}).")
                assessments: dict[str, dict[str, bool]] = {}
                for index, (asset_id, data) in enumerate(previews, 1):
                    try:
                        if progress:
                            progress(month - 1, 12, f"Month {month} of 12 · checking face visibility {index}/{len(previews)}")
                        assessments[asset_id] = vision.assess(data)
                        if faces and faces.get(asset_id, 0) < 0.18:
                            assessments[asset_id]["face_large_enough"] = False
                    except VisionError as exc:
                        warnings.append(f"Month {month}: face visibility check failed ({exc}).")
                def finalist_score(asset_id: str) -> tuple[int, int, int, float, int]:
                    flags = assessments.get(asset_id, {})
                    unobstructed = not flags.get("foreground_barrier") and not flags.get("face_covered")
                    return (int(unobstructed), int(flags.get("face_visible", False)),
                            int(flags.get("face_large_enough", False)), faces.get(asset_id, 0), -final_ids.index(asset_id))
                best_ids = sorted(final_ids, key=finalist_score, reverse=True)
                ranked_items = ([next(item for item in shortlist if item["id"] == asset_id) for asset_id in best_ids]
                                + [item for item in shortlist if item["id"] not in best_ids])
                best = assessments.get(best_ids[0], {})
                if best.get("foreground_barrier") or best.get("face_covered"):
                    reason = "Best available finalist, but a foreground object may obscure the portrait. Please review."
                    warnings.append(f"Month {month}: all finalists may need a closer look for obstructions.")
                elif best.get("face_visible") and best.get("face_large_enough"):
                    reason = "Clear, prominent face without a foreground obstruction."
                else:
                    reason = "Best available finalist; check the face and framing before printing."
            selected = ranked_items[0]["id"]
            reason = reason or "Chosen from capture date, image quality, and preview comparison."
        if old.get("photo_locked") and selected and selected not in {a["id"] for a in unique}:
            warnings.append(f"Month {month}: your chosen photo is no longer in the current Immich search results.")
        if selected:
            chosen = next((item for item in unique if item["id"] == selected), None)
            if chosen:
                ranked_items = [chosen, *[item for item in ranked_items if item["id"] != selected]]
        cards.append({
            "month": month,
            "label": f"Month {month}",
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "asset_id": selected,
            "photo_locked": bool(old.get("photo_locked", False)),
            "caption": old.get("caption", ""),
            "crop_x": float(old.get("crop_x", 0.5)),
            "crop_y": float(old.get("crop_y", 0.5)),
            "reason": reason,
            "source_digest": digest,
            "candidate_count": len(unique),
            "candidates": [_candidate_data(item) for item in ranked_items[:12]],
        })
        if progress:
            progress(month, 12, "Comparing monthly finalists")
    return cards, warnings


def new_project(title: str, baby_name: str, birth_date: str, person_id: str | None, album_ids: list[str], prompt: str, theme: str,
                analysis_depth: str = "balanced") -> dict:
    from uuid import uuid4

    birthday = date.fromisoformat(birth_date)
    if birthday > date.today():
        raise ValueError("Birth date cannot be in the future")
    if not person_id and not album_ids:
        raise ValueError("Choose at least one Immich album")
    if analysis_depth not in {"balanced", "thorough"}:
        raise ValueError("Invalid analysis depth")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()),
        "title": title.strip()[:100] or f"{baby_name}'s first year",
        "baby_name": baby_name.strip()[:80],
        "birth_date": birth_date,
        "person_id": person_id or None,
        "album_ids": album_ids,
        "prompt": prompt.strip()[:1000],
        "theme": theme,
        "analysis_depth": analysis_depth,
        "created_at": now,
        "updated_at": now,
        "last_sync_at": None,
        "status": "building",
        "error": None,
        "warnings": [],
        "cards": [],
    }
