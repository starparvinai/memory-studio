"""Optional local face-size signal for thumbnail shortlisting on macOS."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def face_widths(paths: dict[str, Path], data_root: Path) -> dict[str, float]:
    """Return the widest detected face as a fraction of each image's width."""
    if sys.platform != "darwin" or not paths or not shutil.which("swift"):
        return {}
    module_cache = (data_root / "swift-cache").resolve()
    module_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("IMMICH_API_KEY", None)
    env.pop("OPENROUTER_API_KEY", None)
    env["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
    env["SWIFT_MODULECACHE_PATH"] = str(module_cache)
    script = Path(__file__).parent / "static" / "face_detector.swift"
    try:
        completed = subprocess.run(
            ["swift", str(script)],
            input="\n".join(str(path.resolve()) for path in paths.values()) + "\n",
            text=True, capture_output=True, timeout=240, env=env, check=True,
        )
        values = completed.stdout.splitlines()
        if len(values) != len(paths):
            return {}
        return {asset_id: max(0.0, min(float(value), 1.0))
                for asset_id, value in zip(paths, values, strict=True)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
