"""Display-name helpers (DB overlays are the source of truth in archive.sqlite).

Kept as an empty in-memory map so older call sites still compile; prefer
`overlays` table via the viewer APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contacts_resolve import normalize_email, phone_keys


class Overrides:
    def __init__(self, data: dict[str, Any] | None = None):
        data = data or {}
        self.handles: dict[str, str] = {}
        self.contacts: dict[str, str] = {}
        self.groups: dict[str, str] = {}

        for raw, name in (data.get("handles") or {}).items():
            if not name:
                continue
            name = str(name).strip()
            key = str(raw).strip()
            self.handles[key.lower()] = name
            for pk in phone_keys(key):
                self.handles[f"tel:{pk}"] = name
                self.handles[pk] = name
            em = normalize_email(key)
            if em:
                self.handles[f"email:{em}"] = name
                self.handles[em] = name

        for cid, name in (data.get("contacts") or {}).items():
            if name:
                self.contacts[str(cid).strip().lower()] = str(name).strip()

        for gid, name in (data.get("groups") or {}).items():
            if name:
                self.groups[str(gid).strip().lower()] = str(name).strip()

    def handle_name(self, handle: str | None) -> str | None:
        if not handle:
            return None
        raw = str(handle).strip()
        candidates = [raw, raw.lower()]
        for pk in phone_keys(raw):
            candidates.extend([pk, f"tel:{pk}", f"+{pk}"])
        em = normalize_email(raw)
        if em:
            candidates.extend([em, f"email:{em}"])
        for c in candidates:
            hit = self.handles.get(c.lower() if not c.startswith("tel:") else c)
            if hit:
                return hit
            hit = self.handles.get(c)
            if hit:
                return hit
        return None

    def contact_name(self, contact_id: str | None) -> str | None:
        if not contact_id:
            return None
        return self.contacts.get(str(contact_id).strip().lower())

    def group_name(
        self, *, chat_identifier: str | None = None, chat_id: str | int | None = None
    ) -> str | None:
        for key in (chat_identifier, chat_id):
            if key is None or key == "":
                continue
            hit = self.groups.get(str(key).strip().lower())
            if hit:
                return hit
        return None


def load_overrides(_archive_root: Path | None = None) -> Overrides:
    """YAML overrides removed — always empty; use DB `overlays` table instead."""
    return Overrides()
