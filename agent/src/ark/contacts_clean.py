"""Clean AddressBook fields for human display."""

from __future__ import annotations

import re
from typing import Any

from .dates import apple_date_to_iso

# ABMultiValue property codes
_PROP_DATE = 12  # custom dates / birthdays with labels
_PROP_SOCIAL = 46
_PROP_RELATED = 22  # sometimes address
_OPAQUE_PROPS = {76}  # encrypted / binary social payloads — not useful raw

_HIDE_EXTENDED = {
    "FirstSort",
    "LastSort",
    "FirstSortSection",
    "LastSortSection",
    "PersonLink",
    "StoreID",
    "IsPreferredName",
    "ExternalModificationTag",
}


def _apple_epoch_to_iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        n = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    # AddressBook often stores Cocoa epoch as float seconds
    try:
        return apple_date_to_iso(n)
    except (OSError, OverflowError, ValueError):
        return None


def clean_contact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a display-oriented copy of a contact payload."""
    out = dict(payload)

    # Named dates from multi-value property 12
    dates = []
    cleaned_mv = []
    for mv in payload.get("extended_multivalues") or []:
        if not isinstance(mv, dict):
            continue
        prop = mv.get("property")
        val = mv.get("value")
        label = mv.get("label")
        if prop in _OPAQUE_PROPS:
            continue
        if prop == _PROP_SOCIAL and not val:
            continue
        if prop == _PROP_DATE:
            iso = _apple_epoch_to_iso(val)
            if iso or label:
                dates.append({"label": label or "Date", "date": iso, "raw": val})
            continue
        if val is None or val == "":
            continue
        # Skip base64-looking blobs
        if isinstance(val, str) and len(val) > 80 and re.fullmatch(r"[A-Za-z0-9+/=]+", val or ""):
            continue
        cleaned_mv.append(mv)
    out["dates"] = dates
    out["extended_multivalues"] = cleaned_mv

    # Birthday field
    ef = dict(payload.get("extended_fields") or {})
    birthday = ef.pop("Birthday", None)
    if birthday:
        out["birthday"] = _apple_epoch_to_iso(birthday) or birthday

    for k in list(ef.keys()):
        if k in _HIDE_EXTENDED:
            ef.pop(k, None)
            continue
        if k in ("CreationDate", "ModificationDate"):
            iso = apple_date_to_iso(ef[k])
            if iso:
                ef[k] = iso
        # Drop binary-ish sort leftovers
        v = ef.get(k)
        if isinstance(v, str) and any(ord(ch) < 9 for ch in v):
            ef.pop(k, None)

    out["extended_fields"] = ef

    # Drop empty urls
    out["urls"] = [
        u
        for u in (payload.get("urls") or [])
        if isinstance(u, dict) and u.get("value")
    ]
    return out
