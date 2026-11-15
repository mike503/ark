"""Decode Apple VMVoicemailTranscript (.transcript) NSKeyedArchiver plists."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any


def _uid_index(obj: Any) -> int | None:
    # plistlib.UID in 3.8+
    if hasattr(obj, "data") and type(obj).__name__ == "UID":
        return int(obj.data)
    if isinstance(obj, int):
        return obj
    return None


def _deref(objects: list[Any], ref: Any) -> Any:
    idx = _uid_index(ref)
    if idx is None:
        return ref
    if idx < 0 or idx >= len(objects):
        return None
    return objects[idx]


def decode_voicemail_transcript(data: bytes) -> dict[str, Any] | None:
    """
    Return {text, confidence, segments?} or None if undecodable.
    Prefer the archived transcriptionString (clean full sentence).
    """
    try:
        root = plistlib.loads(data)
    except Exception:
        # Maybe already plain text
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
        if text and not text.startswith("bplist"):
            return {"text": text, "confidence": None, "format": "plain"}
        return None

    if not isinstance(root, dict) or "$objects" not in root:
        return None

    objects: list[Any] = root["$objects"]
    top = root.get("$top") or {}
    # Walk objects for VMVoicemailTranscript-shaped dicts
    best_text = None
    confidence = None
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if "transcriptionString" not in obj:
            continue
        text_obj = _deref(objects, obj["transcriptionString"])
        if isinstance(text_obj, str) and text_obj.strip():
            # Prefer longest (full string over fragments)
            if best_text is None or len(text_obj) > len(best_text):
                best_text = text_obj.strip()
                conf = obj.get("confidence")
                confidence = float(conf) if isinstance(conf, (int, float)) else None

    if not best_text:
        # Fallback: join segment substrings in order via segments array if present
        return None

    return {
        "text": best_text,
        "confidence": confidence,
        "format": "vm_transcript",
    }


def load_voicemail_transcript(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return decode_voicemail_transcript(path.read_bytes())
