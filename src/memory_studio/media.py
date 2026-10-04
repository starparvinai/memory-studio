"""Private, bounded-on-demand cache of Immich image derivatives and originals."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from .immich import Immich


class MediaCache:
    def __init__(self, root: Path):
        self.root = root / "media"
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, immich: Immich, asset_id: str, size: str) -> bytes:
        UUID(asset_id)
        if size not in {"thumbnail", "preview", "original"}:
            raise ValueError("Invalid media size")
        folder = self.root / size
        folder.mkdir(exist_ok=True)
        path = folder / asset_id
        if path.exists():
            return path.read_bytes()
        data = immich.image(asset_id, size)
        temporary = folder / f".{asset_id}.{os.getpid()}.tmp"
        temporary.write_bytes(data)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        return data
