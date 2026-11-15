"""Decode iMessage attributedBody (NSAttributedString typedstream) to plain text."""

from __future__ import annotations

import re

try:
    from typedstream import Unarchiver

    _HAS_TYPEDSTREAM = True
except ImportError:
    _HAS_TYPEDSTREAM = False

_SKIP_PREFIXES = ("NS", "__k", "{")


def _decode_via_typedstream(attr_body: bytes) -> str | None:
    try:
        result = Unarchiver.from_data(attr_body).decode_all()
        for tv in result:
            obj = tv.value
            if hasattr(obj, "contents"):
                for item in obj.contents:
                    val = item.value
                    if hasattr(val, "value") and isinstance(val.value, str):
                        text = val.value.strip()
                        if text:
                            return text
                    elif isinstance(val, str):
                        text = val.strip()
                        if text and not text.startswith(_SKIP_PREFIXES):
                            return text
    except (IndexError, ValueError, UnicodeDecodeError, TypeError, OSError, AttributeError):
        return None
    return None


def _decode_via_multiformat(attr_body: bytes) -> str | None:
    try:
        text_section = attr_body.split(b"NSString")[1].split(b"NSDictionary")[0]

        plus_idx = text_section.find(b"+")
        if plus_idx != -1 and plus_idx + 2 < len(text_section):
            marker = text_section[plus_idx + 1]
            if marker < 0x80:
                length, start = marker, plus_idx + 2
            elif marker == 0x81 and plus_idx + 4 <= len(text_section):
                length = int.from_bytes(text_section[plus_idx + 2 : plus_idx + 4], "little")
                start = plus_idx + 4
            elif marker == 0x82 and plus_idx + 5 <= len(text_section):
                length = int.from_bytes(text_section[plus_idx + 2 : plus_idx + 5], "little")
                start = plus_idx + 5
            elif marker == 0x83 and plus_idx + 6 <= len(text_section):
                length = int.from_bytes(text_section[plus_idx + 2 : plus_idx + 6], "little")
                start = plus_idx + 6
            else:
                length, start = 0, 0

            if length > 0 and start + length <= len(text_section):
                text = text_section[start : start + length].decode("utf-8", errors="ignore").strip()
                if text:
                    return text

        for i in range(len(text_section) - 2):
            if text_section[i] != 0x4F:
                continue
            size_marker = text_section[i + 1]
            if size_marker == 0x10:
                length, start = text_section[i + 2], i + 3
            elif size_marker == 0x11 and i + 4 <= len(text_section):
                length = int.from_bytes(text_section[i + 2 : i + 4], "big")
                start = i + 4
            elif size_marker == 0x12 and i + 6 <= len(text_section):
                length = int.from_bytes(text_section[i + 2 : i + 6], "big")
                start = i + 6
            else:
                continue
            if 0 < length < 100000 and start + length <= len(text_section):
                text = text_section[start : start + length].decode("utf-8", errors="ignore").strip()
                if text:
                    return text

        i_idx = text_section.find(b"I")
        if i_idx != -1 and i_idx + 5 < len(text_section):
            length = int.from_bytes(text_section[i_idx + 1 : i_idx + 5], "big")
            if 0 < length < 100000 and i_idx + 5 + length <= len(text_section):
                text = (
                    text_section[i_idx + 5 : i_idx + 5 + length]
                    .decode("utf-8", errors="ignore")
                    .strip()
                )
                if text:
                    return text
    except (IndexError, ValueError):
        pass

    try:
        if b"streamtyped" in attr_body:
            parts = attr_body.split(b"NSString")
            if len(parts) > 1:
                matches = re.findall(rb"[\x20-\x7e\xc0-\xff]{4,}", parts[1])
                for m in matches:
                    decoded = m.decode("utf-8", errors="ignore").strip()
                    if decoded and not decoded.startswith(_SKIP_PREFIXES):
                        return decoded
    except (IndexError, ValueError, UnicodeDecodeError):
        return None
    return None


def _decode_via_nsstring_marker(attr_body: bytes) -> str | None:
    try:
        parts = attr_body.split(b"NSString")
        if len(parts) < 2:
            return None
        content = parts[1][5:]
        length = content[0]
        start = 1
        if content[0] == 0x81:
            length = int.from_bytes(content[1:3], "little")
            start = 3
        text = content[start : start + length].decode("utf-8", errors="ignore").strip()
        return text if text else None
    except (IndexError, ValueError):
        return None


def decode_attributed_body(attr_body: bytes | None) -> str | None:
    """Return plain text from an attributedBody blob, or None if undecodable."""
    if not attr_body:
        return None
    if _HAS_TYPEDSTREAM:
        result = _decode_via_typedstream(attr_body)
        if result:
            return result
    result = _decode_via_multiformat(attr_body)
    if result:
        return result
    return _decode_via_nsstring_marker(attr_body)
