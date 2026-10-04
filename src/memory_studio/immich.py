"""Read-only Immich API adapter."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx


class ImmichError(Exception):
    pass


class Immich:
    def __init__(self, url: str, api_key: str):
        if not url or not api_key:
            raise ImmichError("Set your Immich URL and API key in Settings.")
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ImmichError("Immich URL must start with http:// or https://.")
        base = url.rstrip("/")
        self.base = base if base.endswith("/api") else base + "/api"
        self.client = httpx.Client(
            base_url=self.base + "/",
            headers={"x-api-key": api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(40, connect=10),
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def _json(self, method: str, path: str, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ImmichError(f"Immich returned HTTP {exc.response.status_code} for {path}.") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise ImmichError(f"Could not read Immich: {exc}") from exc

    def ping(self) -> dict:
        return self._json("GET", "server/version")

    def people(self) -> list[dict]:
        result = []
        page = 1
        while True:
            data = self._json("GET", "people", params={"page": page, "size": 250})
            batch = data.get("people", data.get("items", [])) if isinstance(data, dict) else data
            result.extend(batch)
            if len(batch) < 250 or page >= 20:
                break
            page += 1
        return [person for person in result if person.get("name")]

    def albums(self) -> list[dict]:
        data = self._json("GET", "albums")
        return data if isinstance(data, list) else data.get("albums", data.get("items", []))

    def search_year(self, start: str, end: str, person_id: str | None, album_id: str | None) -> list[dict]:
        filters: dict = {
            "takenAfter": f"{start}T00:00:00.000Z",
            "takenBefore": f"{end}T23:59:59.999Z",
            "type": "IMAGE",
            "withExif": True,
            "withPeople": True,
            "size": 250,
        }
        if person_id:
            filters["personIds"] = [person_id]
        if album_id:
            filters["albumIds"] = [album_id]
        assets = []
        page = 1
        while True:
            data = self._json("POST", "search/metadata", json={**filters, "page": page})
            group = data.get("assets", {})
            batch = group.get("items", [])
            assets.extend(batch)
            if len(assets) > 10000:
                raise ImmichError("More than 10,000 photos matched. Narrow the person or album selection.")
            if not group.get("nextPage") or not batch:
                break
            page = int(group["nextPage"])
        return [asset for asset in assets if asset.get("type") == "IMAGE" and not asset.get("isTrashed") and not asset.get("isOffline")]

    def image(self, asset_id: str, size: str) -> bytes:
        if size not in {"thumbnail", "preview", "original"}:
            raise ValueError("Unsupported Immich image size")
        path = f"assets/{asset_id}/original" if size == "original" else f"assets/{asset_id}/thumbnail"
        params = None if size == "original" else {"size": size}
        try:
            with self.client.stream("GET", path, params=params) as response:
                response.raise_for_status()
                limit = {"thumbnail": 4, "preview": 20, "original": 250}[size] * 1024 * 1024
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise ImmichError(f"{size.title()} for photo {asset_id} exceeded the {limit // 1024 // 1024} MB limit.")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPStatusError as exc:
            raise ImmichError(f"Immich could not provide photo {asset_id} (HTTP {exc.response.status_code}).") from exc
        except httpx.RequestError as exc:
            raise ImmichError(f"Could not download photo {asset_id}: {exc}") from exc

    def preview(self, asset_id: str) -> bytes:
        return self.image(asset_id, "preview")
