"""Normalize handles and resolve them via archived contacts."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D+", "", str(value))
    if not digits:
        return None
    # Drop leading 00 international prefix
    if digits.startswith("00") and len(digits) > 2:
        digits = digits[2:]
    return digits


def phone_keys(value: str | None) -> set[str]:
    """Multiple lookup keys for the same number (+1 / 10-digit variants)."""
    d = normalize_phone(value)
    if not d:
        return set()
    keys = {d}
    if len(d) == 11 and d.startswith("1"):
        keys.add(d[1:])
    elif len(d) == 10:
        keys.add("1" + d)
    return keys


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).strip().lower()
    return s or None


def build_contact_lookup(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """
    Map normalized phone/email -> {display_name, contact_id, on_device}.
    Prefer on-device contacts when the same handle maps to more than one row.
    """
    if not _table_exists(conn, "contacts"):
        return {}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
    has_on_device = "on_device" in cols
    sql = "SELECT id, display_name, payload_json"
    if has_on_device:
        sql += ", on_device"
    sql += " FROM contacts"
    lookup: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql):
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        on_device = bool(row["on_device"]) if has_on_device else True
        entry = {
            "display_name": row["display_name"] or payload.get("display_name"),
            "contact_id": row["id"],
            "on_device": on_device,
        }
        for phone in payload.get("phones") or []:
            val = phone.get("value") if isinstance(phone, dict) else phone
            for key in phone_keys(val):
                _put(lookup, f"tel:{key}", entry)
        for email in payload.get("emails") or []:
            val = email.get("value") if isinstance(email, dict) else email
            em = normalize_email(val)
            if em:
                _put(lookup, f"email:{em}", entry)
    return lookup


def _put(lookup: dict[str, dict[str, Any]], key: str, entry: dict[str, Any]) -> None:
    prev = lookup.get(key)
    if prev is None:
        lookup[key] = entry
        return
    # Prefer currently-on-device contact over a retained deleted one
    if entry.get("on_device") and not prev.get("on_device"):
        lookup[key] = entry


def resolve_handle(
    handle: str | None,
    lookup: dict[str, dict[str, Any]],
    overrides: Any | None = None,
) -> dict[str, Any] | None:
    if not handle:
        return None
    raw = str(handle).strip()
    if not raw or raw.lower() in {"me", "unknown"}:
        return None

    # 1) Local handle override
    if overrides is not None:
        ov = overrides.handle_name(raw)
        if ov:
            return {
                "display_name": ov,
                "contact_id": None,
                "on_device": None,
                "source": "override",
            }

    hit = None
    if "@" in raw and not raw.startswith("chat"):
        em = normalize_email(raw.split(";")[0])
        if em and f"email:{em}" in lookup:
            hit = lookup[f"email:{em}"]
    if hit is None:
        for key in phone_keys(raw):
            hit = lookup.get(f"tel:{key}")
            if hit:
                break
    if hit is None:
        em = normalize_email(raw)
        if em and f"email:{em}" in lookup:
            hit = lookup[f"email:{em}"]

    if not hit:
        return None

    # 2) Contact-id override on top of address book
    name = hit.get("display_name")
    if overrides is not None:
        cov = overrides.contact_name(hit.get("contact_id"))
        if cov:
            name = cov
            return {
                "display_name": name,
                "contact_id": hit.get("contact_id"),
                "on_device": hit.get("on_device"),
                "source": "override",
            }

    return {
        "display_name": name,
        "contact_id": hit.get("contact_id"),
        "on_device": hit.get("on_device"),
        "source": "contacts",
    }


def display_for(
    handle: str | None,
    lookup: dict[str, dict[str, Any]],
    overrides: Any | None = None,
) -> str | None:
    hit = resolve_handle(handle, lookup, overrides)
    return hit["display_name"] if hit else None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
    ).fetchone()
    return row is not None
