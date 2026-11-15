"""User overlays: display names, notes, ignore flags (stored in archive.sqlite)."""

from __future__ import annotations

import sqlite3
from typing import Any

from .dates import utc_now_iso

OVERLAYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS overlays (
  id TEXT PRIMARY KEY,
  module TEXT NOT NULL,
  item_id TEXT NOT NULL,
  display_name TEXT,
  notes TEXT,
  ignored INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_overlays_module ON overlays(module);
CREATE INDEX IF NOT EXISTS idx_overlays_ignored ON overlays(ignored);
"""

# module values used by the viewer / APIs
MODULE_CHAT = "chat"  # messages thread (group or 1:1) — item_id = chat_id
MODULE_CONTACT = "contact"
MODULE_VOICEMAIL = "voicemail"
MODULE_VOICEMEMO = "voicememo"
MODULE_WIFI = "wifi"
MODULE_WHATSAPP = "whatsapp"


def overlay_id(module: str, item_id: str) -> str:
    return f"{module}:{item_id}"


def ensure_overlays_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(OVERLAYS_SCHEMA)
    conn.commit()


def load_overlays_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Map overlay_id -> row dict."""
    ensure_overlays_schema(conn)
    out: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        "SELECT id, module, item_id, display_name, notes, ignored, updated_at FROM overlays"
    )
    for row in rows:
        if isinstance(row, sqlite3.Row):
            d = {k: row[k] for k in row.keys()}
        else:
            d = {
                "id": row[0],
                "module": row[1],
                "item_id": row[2],
                "display_name": row[3],
                "notes": row[4],
                "ignored": row[5],
                "updated_at": row[6],
            }
        d["ignored"] = bool(d.get("ignored"))
        out[d["id"]] = d
        out[f"{d['module']}:{d['item_id']}"] = d
    return out


def get_overlay(conn: sqlite3.Connection, module: str, item_id: str) -> dict[str, Any] | None:
    ensure_overlays_schema(conn)
    row = conn.execute(
        "SELECT id, module, item_id, display_name, notes, ignored, updated_at "
        "FROM overlays WHERE module = ? AND item_id = ?",
        (module, str(item_id)),
    ).fetchone()
    if not row:
        return None
    if isinstance(row, sqlite3.Row):
        d = {k: row[k] for k in row.keys()}
    else:
        d = {
            "id": row[0],
            "module": row[1],
            "item_id": row[2],
            "display_name": row[3],
            "notes": row[4],
            "ignored": row[5],
            "updated_at": row[6],
        }
    d["ignored"] = bool(d["ignored"])
    return d


def upsert_overlay(
    conn: sqlite3.Connection,
    *,
    module: str,
    item_id: str,
    display_name: str | None = None,
    notes: str | None = None,
    ignored: bool | None = None,
    clear_display_name: bool = False,
    clear_notes: bool = False,
) -> dict[str, Any]:
    """Merge-update overlay fields. None means leave unchanged unless clear_*."""
    ensure_overlays_schema(conn)
    item_id = str(item_id)
    oid = overlay_id(module, item_id)
    existing = get_overlay(conn, module, item_id) or {
        "id": oid,
        "module": module,
        "item_id": item_id,
        "display_name": None,
        "notes": None,
        "ignored": False,
    }
    if clear_display_name:
        existing["display_name"] = None
    elif display_name is not None:
        existing["display_name"] = display_name.strip() or None
    if clear_notes:
        existing["notes"] = None
    elif notes is not None:
        existing["notes"] = notes  # allow empty string -> store empty; use clear to null
    if ignored is not None:
        existing["ignored"] = bool(ignored)

    # Drop row entirely if nothing left
    if not existing.get("display_name") and not existing.get("notes") and not existing.get("ignored"):
        conn.execute("DELETE FROM overlays WHERE id = ?", (oid,))
        conn.commit()
        return {
            "id": oid,
            "module": module,
            "item_id": item_id,
            "display_name": None,
            "notes": None,
            "ignored": False,
            "deleted": True,
        }

    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO overlays(id, module, item_id, display_name, notes, ignored, updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          display_name=excluded.display_name,
          notes=excluded.notes,
          ignored=excluded.ignored,
          updated_at=excluded.updated_at
        """,
        (
            oid,
            module,
            item_id,
            existing.get("display_name"),
            existing.get("notes"),
            1 if existing.get("ignored") else 0,
            now,
        ),
    )
    conn.commit()
    existing["updated_at"] = now
    existing["deleted"] = False
    return existing
