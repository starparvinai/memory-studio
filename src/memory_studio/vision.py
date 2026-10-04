"""Small image comparison interface for local Ollama or OpenRouter."""

from __future__ import annotations

import base64
import io
import json
import re

import httpx
from PIL import Image, ImageOps


class VisionError(Exception):
    pass


def _jpeg(data: bytes) -> bytes:
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image.thumbnail((640, 640))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=78)
    return output.getvalue()


class Vision:
    def __init__(self, provider: str, model: str, api_key: str = "", ollama_url: str = "http://127.0.0.1:11434"):
        self.provider, self.model, self.api_key = provider, model, api_key
        self.ollama_url = ollama_url.rstrip("/")

    def rank(self, month: int, candidates: list[tuple[str, bytes]]) -> tuple[list[str], str]:
        if len(candidates) == 1:
            return [candidates[0][0]], "Only candidate in this comparison."
        ids = [asset_id for asset_id, _ in candidates]
        instruction = (
            f"Rank these {len(ids)} photos for a family's Month {month} keepsake. "
            "The first priority is a clearly visible, reasonably large child's face. "
            "Strongly penalize a face hidden by flowers, toys, playpen bars, hands, or other objects; "
            "also penalize a tiny, turned-away, blurred, or cropped-off face. "
            "Among photos with a clear face, prefer a natural smile, laugh, funny or warm interaction, "
            "then sharpness, good light, and pleasing composition. A sharp obstruction is not a good portrait. "
            "If no photo has a clear face, choose the best visible expression and explain the compromise. "
            "Judge only visible qualities; do not infer identity, health, age, or milestones. "
            f"There are {len(ids)} photos, numbered 1 through {len(ids)} in attachment order. "
            "Return only JSON with ranked_numbers (every number exactly once, best first) and reason (one short visual reason for first choice)."
        )
        try:
            if self.provider == "ollama":
                content = [{"role": "user", "content": instruction,
                            "images": [base64.b64encode(_jpeg(data)).decode() for _, data in candidates]}]
                response = httpx.post(f"{self.ollama_url}/api/chat", json={"model": self.model, "messages": content,
                    "format": {"type": "object", "properties": {"ranked_numbers": {"type": "array", "items": {"type": "integer"}}, "reason": {"type": "string"}}, "required": ["ranked_numbers", "reason"]},
                    "stream": False, "think": False,
                    "options": {"temperature": 0, "num_predict": 180}, "keep_alive": "30m"}, timeout=180)
                response.raise_for_status()
                answer = response.json()["message"]["content"]
            elif self.provider == "openrouter":
                if not self.api_key:
                    raise VisionError("OpenRouter API key is missing")
                content = [{"type": "text", "text": instruction}]
                for number, (_, data) in enumerate(candidates, 1):
                    content.extend([{"type": "text", "text": f"Photo {number}:"},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(_jpeg(data)).decode()}}])
                response = httpx.post("https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": [{"role": "user", "content": content}], "temperature": 0}, timeout=180)
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
            else:
                raise VisionError("Unknown vision provider")
            match = re.search(r"\{.*\}", answer, re.DOTALL)
            result = json.loads(match.group(0) if match else answer)
            numbers = result.get("ranked_numbers", [])
            if not isinstance(numbers, list) or set(numbers) != set(range(1, len(ids) + 1)) or len(numbers) != len(ids):
                raise VisionError("Vision model returned an invalid ranking")
            return [ids[number - 1] for number in numbers], str(result.get("reason", ""))[:200]
        except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise VisionError(f"Vision ranking failed: {exc}") from exc

    def assess(self, data: bytes) -> dict[str, bool]:
        """Check one finalist for the face visibility failures a group ranking can miss."""
        instruction = (
            "Assess this one photo for a printed child's portrait. Answer four separate questions. "
            "Is a child's face visible? Is there a foreground barrier such as playpen bars, "
            "a fence, or railing between the camera and the child? Is a flower, toy, hand, "
            "or other object covering any part of the face? Is the visible face at least "
            "20 percent of the photo width? Return only JSON with boolean fields "
            "face_visible, foreground_barrier, face_covered, and face_large_enough."
        )
        names = ("face_visible", "foreground_barrier", "face_covered", "face_large_enough")
        encoded = base64.b64encode(_jpeg(data)).decode()
        try:
            if self.provider == "ollama":
                response = httpx.post(f"{self.ollama_url}/api/chat", json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": instruction, "images": [encoded]}],
                    "format": {"type": "object", "properties": {name: {"type": "boolean"} for name in names},
                               "required": list(names)},
                    "stream": False, "think": False,
                    "options": {"temperature": 0, "num_predict": 120}, "keep_alive": "30m",
                }, timeout=180)
                response.raise_for_status()
                answer = response.json()["message"]["content"]
            elif self.provider == "openrouter":
                if not self.api_key:
                    raise VisionError("OpenRouter API key is missing")
                response = httpx.post("https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": [{"role": "user", "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}},
                    ]}], "temperature": 0}, timeout=180)
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
            else:
                raise VisionError("Unknown vision provider")
            match = re.search(r"\{.*\}", answer, re.DOTALL)
            result = json.loads(match.group(0) if match else answer)
            if any(not isinstance(result.get(name), bool) for name in names):
                raise VisionError("Vision model returned an invalid photo assessment")
            return {name: result[name] for name in names}
        except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise VisionError(f"Photo assessment failed: {exc}") from exc
