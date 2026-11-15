"""On-demand media conversion for browser playback/preview (ffmpeg)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

_FFMPEG = shutil.which("ffmpeg")


def ffmpeg_available() -> bool:
    return Path(_FFMPEG).is_file() if _FFMPEG else False


def _cache_path(cache_root: Path, src: Path, suffix: str) -> Path:
    digest = hashlib.sha256(str(src.resolve()).encode("utf-8")).hexdigest()[:16]
    stamp = int(src.stat().st_mtime_ns)
    return cache_root / f"{src.stem}-{digest}-{stamp}{suffix}"


def convert_for_browser(
    src: Path,
    cache_root: Path,
    *,
    kind: str,
) -> Path | None:
    """
    kind: 'audio' -> m4a/aac; 'image' -> jpeg
    Returns path to converted file, or None on failure.
    """
    if not src.is_file() or not ffmpeg_available():
        return None
    cache_root.mkdir(parents=True, exist_ok=True)
    suffix = ".m4a" if kind == "audio" else ".jpg"
    dest = _cache_path(cache_root, src, suffix)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    if kind == "audio":
        cmd = [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(dest),
        ]
    else:
        cmd = [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(dest),
        ]
    try:
        subprocess.run(cmd, check=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        if dest.exists():
            dest.unlink(missing_ok=True)
        return None
    return dest if dest.is_file() and dest.stat().st_size > 0 else None


def needs_audio_transcode(path: Path) -> bool:
    return path.suffix.lower() in {".amr", ".awb", ".3gp", ".3gpp"}


def needs_image_transcode(path: Path) -> bool:
    return path.suffix.lower() in {".heic", ".heif", ".heics"}
