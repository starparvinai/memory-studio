"""Small, single-user local store. Private data never belongs in the repository."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.environ.get("MEMORY_STUDIO_DATA_DIR", "data"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(exist_ok=True)
        self.lock = threading.RLock()

    def _read(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def settings(self) -> dict[str, str]:
        with self.lock:
            saved = self._read(self.root / "settings.json", {})
        env_file = Path(os.environ.get("MEMORY_STUDIO_ENV_FILE", ".env"))
        file_values = dotenv_values(env_file) if env_file.is_file() else {}

        def get(name: str, key: str, default: str = "") -> str:
            if name in os.environ:
                return os.environ[name]
            if name in file_values and file_values[name] is not None:
                return str(file_values[name])
            return saved.get(key, default)

        return {
            "immich_url": get("IMMICH_URL", "immich_url"),
            "immich_api_key": get("IMMICH_API_KEY", "immich_api_key"),
            "openrouter_api_key": get("OPENROUTER_API_KEY", "openrouter_api_key"),
            "openrouter_model": get("OPENROUTER_MODEL", "openrouter_model", "google/gemini-3.1-flash-lite"),
            "vision_provider": get("VISION_PROVIDER", "vision_provider", "ollama"),
            "ollama_url": get("OLLAMA_URL", "ollama_url", "http://127.0.0.1:11434"),
            "ollama_model": get("OLLAMA_MODEL", "ollama_model", "qwen3-vl:4b-instruct"),
        }

    def save_settings(self, changes: dict[str, str]) -> None:
        allowed = {"immich_url", "immich_api_key", "openrouter_api_key", "openrouter_model", "vision_provider", "ollama_url", "ollama_model"}
        with self.lock:
            current = self._read(self.root / "settings.json", {})
            current.update({key: value.strip() for key, value in changes.items() if key in allowed and value is not None})
            self._write(self.root / "settings.json", current)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.lock:
            projects = [self._read(path, {}) for path in self.projects_dir.glob("*.json")]
        return sorted(projects, key=lambda item: item.get("created_at", ""), reverse=True)

    def project(self, project_id: str) -> dict[str, Any] | None:
        if not _safe_id(project_id):
            return None
        with self.lock:
            return self._read(self.projects_dir / f"{project_id}.json", None)

    def save_project(self, project: dict[str, Any]) -> None:
        if not _safe_id(project.get("id", "")):
            raise ValueError("Invalid project ID")
        with self.lock:
            self._write(self.projects_dir / f"{project['id']}.json", project)


def _safe_id(value: str) -> bool:
    return bool(value) and all(char in "0123456789abcdef-" for char in value)
