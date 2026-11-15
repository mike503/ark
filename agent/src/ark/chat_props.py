"""Parse chat.properties and related group metadata from sms.db."""

from __future__ import annotations

import plistlib
from typing import Any


def _uid_data(obj: Any) -> Any:
    if type(obj).__name__ == "UID" and hasattr(obj, "data"):
        return obj.data
    return obj


def parse_chat_properties(blob: bytes | None) -> dict[str, Any]:
    """
    Return a flat dict of useful keys from chat.properties.
    Especially groupPhotoGuid when present.
    """
    if not blob:
        return {}
    try:
        root = plistlib.loads(blob)
    except Exception:
        return {}

    # Plain dict plist
    if isinstance(root, dict) and "$objects" not in root:
        return _extract_photo_fields(root)

    # NSKeyedArchiver
    if isinstance(root, dict) and "$objects" in root:
        objects = root["$objects"]
        found: dict[str, Any] = {}
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            for key in ("groupPhotoGuid", "groupPhotoGUID", "GroupPhotoGuid"):
                if key in obj:
                    val = obj[key]
                    idx = _uid_data(val)
                    if isinstance(idx, int) and 0 <= idx < len(objects):
                        ref = objects[idx]
                        if isinstance(ref, str) and ref not in ("$null",):
                            found["groupPhotoGuid"] = ref
                    elif isinstance(val, str):
                        found["groupPhotoGuid"] = val
            # Also scan string objects near "groupPhoto"
        if found:
            return found
        # Fallback: any UUID-looking string after a groupPhoto key name in objects
        for i, obj in enumerate(objects):
            if isinstance(obj, str) and "groupphoto" in obj.lower().replace("_", ""):
                # next string might be guid — weak; skip
                pass
        return found

    if isinstance(root, list) and root and isinstance(root[0], dict):
        return _extract_photo_fields(root[0])
    return {}


def _extract_photo_fields(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        lk = str(k)
        if "groupphoto" in lk.lower().replace("_", ""):
            if isinstance(v, str) and v.strip():
                out["groupPhotoGuid"] = v.strip()
            elif isinstance(v, dict):
                # nested
                nested = _extract_photo_fields(v)
                out.update(nested)
        elif isinstance(v, dict):
            nested = _extract_photo_fields(v)
            for nk, nv in nested.items():
                out.setdefault(nk, nv)
    # common direct key
    for key in ("groupPhotoGuid", "groupPhotoGUID"):
        if key in d and isinstance(d[key], str) and d[key].strip():
            out["groupPhotoGuid"] = d[key].strip()
    return out
