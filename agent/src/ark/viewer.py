"""Local archive viewer — localhost HTTP UI over archive.sqlite + media files."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import viewer_settings
from .contacts_clean import clean_contact_payload
from .contacts_resolve import build_contact_lookup, display_for, resolve_handle
from .media_convert import (
    convert_for_browser,
    needs_audio_transcode,
    needs_image_transcode,
)
from .overlays import (
    MODULE_CHAT,
    MODULE_CONTACT,
    MODULE_VOICEMAIL,
    MODULE_VOICEMEMO,
    MODULE_WIFI,
    MODULE_WHATSAPP,
    ensure_overlays_schema,
    get_overlay,
    load_overlays_map,
    upsert_overlay,
)
from .overrides import Overrides, load_overrides
from .transcripts import load_voicemail_transcript
from .versioning import SCHEMA_VERSION, __version__

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".heics", ".bmp"}


def _connect(db_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if not db_path.is_file():
        raise SystemExit(f"Archive DB not found: {db_path}")
    if readonly:
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
    ).fetchone()
    return row is not None


def resolve_media_path(archive_root: Path, rel: str | None) -> Path | None:
    """Map stored relative paths onto files under the archive root."""
    if not rel:
        return None
    rel = unquote(str(rel)).replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    candidates = [
        archive_root / rel,
        archive_root / "blobs" / rel,
    ]
    # Legacy extracts stored paths relative to blobs/ without the blobs/ prefix
    if not rel.startswith("blobs/"):
        candidates.append(archive_root / "blobs" / rel)
    # Sometimes only the filename under Library/Voicemail
    name = Path(rel).name
    if name:
        candidates.extend(
            [
                archive_root / "blobs" / "voicemail" / "Library" / "Voicemail" / name,
                archive_root / "blobs" / "voicememos" / "Recordings" / name,
            ]
        )
    for c in candidates:
        try:
            resolved = c.resolve()
            resolved.relative_to(archive_root.resolve())
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def media_url_for(archive_root: Path, rel: str | None) -> str | None:
    path = resolve_media_path(archive_root, rel)
    if not path:
        return None
    # Prefer stable relative path under archive for URLs
    try:
        use = path.relative_to(archive_root).as_posix()
    except ValueError:
        use = rel or path.name
    if needs_audio_transcode(path) or needs_image_transcode(path):
        return f"/play?path={use}"
    return f"/media/{use}"


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in (
        "messages",
        "attachments",
        "voicemails",
        "voicememos",
        "contacts",
        "wifi_networks",
        "whatsapp_messages",
    ):
        if _table_exists(conn, table):
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        else:
            out[table] = 0
    if _table_exists(conn, "contacts"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
        if "on_device" in cols:
            out["contacts_on_device"] = conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE on_device = 1"
            ).fetchone()[0]
            out["contacts_retained"] = conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE on_device = 0"
            ).fetchone()[0]
    return out


def _enrich_handle(handle: str | None, lookup: dict, overrides: Overrides | None = None) -> dict:
    hit = resolve_handle(handle, lookup, overrides)
    return {
        "handle": handle,
        "display_name": hit["display_name"] if hit else None,
        "contact_id": hit["contact_id"] if hit else None,
        "source": hit.get("source") if hit else None,
    }


def _chat_meta_by_id(conn: sqlite3.Connection) -> dict[str, dict]:
    if not _table_exists(conn, "chats"):
        return {}
    out = {}
    for row in conn.execute(
        """
        SELECT chat_id, chat_identifier, thread_key, phone_display_name,
               is_group, group_photo_path, group_photo_guid, participants_json
        FROM chats
        """
    ):
        d = dict(row)
        out[str(d["chat_id"])] = d
        if d.get("chat_identifier"):
            out[f"ident:{d['chat_identifier']}"] = d
    return out


def _ensure_message_indexes(conn: sqlite3.Connection) -> None:
    """Viewer-side index ensure for archives created before migrate added them."""
    if not _table_exists(conn, "messages"):
        return
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, chat_identifier)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date)")
    conn.commit()


def _threads(
    conn: sqlite3.Connection,
    lookup: dict,
    overrides: Overrides,
    overlay_map: dict,
    *,
    limit: int = 2000,
    include_ignored: bool = False,
) -> list[dict]:
    if not _table_exists(conn, "messages"):
        return []
    _ensure_message_indexes(conn)
    chats = _chat_meta_by_id(conn)
    # One aggregate pass over messages — do NOT peek payloads per thread
    # (that was an unindexed LIKE on every group chat and took ~40s for ~300 threads).
    rows = conn.execute(
        """
        SELECT
          chat_id,
          chat_identifier,
          COUNT(*) AS message_count,
          MAX(date) AS last_date,
          MIN(date) AS first_date
        FROM messages
        GROUP BY chat_id, chat_identifier
        ORDER BY CASE WHEN MAX(date) IS NULL THEN 1 ELSE 0 END, MAX(date) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        ident = d.get("chat_identifier")
        chat_id = str(d.get("chat_id"))
        ov = overlay_map.get(f"{MODULE_CHAT}:{chat_id}") or {}
        if ov.get("ignored") and not include_ignored:
            continue
        meta = chats.get(chat_id) or chats.get(f"ident:{ident}") or {}
        phone_name = meta.get("phone_display_name")
        # 1:1 contact resolve (in-memory lookup — cheap)
        contact_name = None
        if ident and not str(ident).startswith("chat"):
            contact_name = display_for(ident, lookup, overrides)

        yaml_name = overrides.group_name(chat_identifier=ident, chat_id=chat_id)
        db_name = ov.get("display_name")
        # Prefer DB overlay, then yaml, then phone group title, then contact name
        display = db_name or yaml_name or phone_name or contact_name
        d["display_name"] = display
        d["phone_display_name"] = phone_name
        d["local_display_name"] = db_name or yaml_name
        d["notes"] = ov.get("notes")
        d["ignored"] = bool(ov.get("ignored"))
        d["name_source"] = (
            "override"
            if (db_name or yaml_name)
            else ("phone" if phone_name else ("contacts" if contact_name else None))
        )
        d["is_group"] = bool(meta.get("is_group")) or bool(ident and str(ident).startswith("chat"))
        d["group_photo_path"] = meta.get("group_photo_path")
        d["group_photo_url"] = (
            f"/media/{meta['group_photo_path']}" if meta.get("group_photo_path") else None
        )
        d["participants"] = []
        try:
            if meta.get("participants_json"):
                d["participants"] = json.loads(meta["participants_json"])
        except json.JSONDecodeError:
            pass
        out.append(d)
    return out


def _messages_for_chat(
    conn: sqlite3.Connection,
    lookup: dict,
    archive_root: Path,
    chat_id: str,
    *,
    overrides: Overrides | None = None,
    limit: int = 200,
    offset: int = 0,
    q: str = "",
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, date, from_addr, to_addrs_json, text, service, payload_json
        FROM messages
        WHERE chat_id = ?
        ORDER BY date DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (chat_id, limit, offset),
    ).fetchall()
    qn = q.strip().lower()
    items = []
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except json.JSONDecodeError:
            pass
        text = r["text"] or payload.get("text") or ""
        if qn and qn not in text.lower() and qn not in (r["from_addr"] or "").lower():
            # still allow attachment filename match
            att_hit = False
            for a in payload.get("attachments") or []:
                if isinstance(a, dict) and qn in json.dumps(a).lower():
                    att_hit = True
                    break
            if not att_hit:
                continue
        thread = payload.get("thread")
        atts = []
        for a in payload.get("attachments") or []:
            if not isinstance(a, dict):
                continue
            a = dict(a)
            if not a.get("path") and thread and a.get("filename"):
                a["path"] = f"messages/{thread}/{a['filename']}"
            path = a.get("path")
            file_path = resolve_media_path(archive_root, path)
            ext = Path(a.get("filename") or path or "").suffix.lower()
            mime = (a.get("mime_type") or "").lower()
            is_image = ext in IMAGE_EXTS or mime.startswith("image/")
            a["is_image"] = bool(is_image and file_path)
            a["url"] = media_url_for(archive_root, path) if path else None
            atts.append(a)
        to_raw = []
        try:
            to_raw = json.loads(r["to_addrs_json"] or "[]")
        except json.JSONDecodeError:
            to_raw = payload.get("to") or []
        items.append(
            {
                "id": r["id"],
                "date": r["date"],
                "from": _enrich_handle(r["from_addr"], lookup, overrides),
                "to": [_enrich_handle(t, lookup, overrides) for t in (to_raw or [])],
                "text": text,
                "service": r["service"] or payload.get("service"),
                "bubble": payload.get("bubble"),
                "is_from_me": bool((payload.get("status") or {}).get("is_from_me")),
                "attachments": atts,
            }
        )
    return items


def _enrich_audio_item(archive_root: Path, payload: dict, *, kind: str) -> dict:
    item = dict(payload)
    audio = dict(item.get("audio") or {})
    path = audio.get("path") or item.get("audio_path")
    resolved = resolve_media_path(archive_root, path)
    if resolved:
        try:
            audio["path"] = resolved.relative_to(archive_root).as_posix()
        except ValueError:
            audio["path"] = path
        audio["url"] = media_url_for(archive_root, audio["path"])
        audio["exists"] = True
        audio["byte_size"] = resolved.stat().st_size
    else:
        audio["url"] = None
        audio["exists"] = False
    item["audio"] = audio

    if kind == "voicemail":
        text = item.get("transcript")
        looks_bad = (
            not text
            or (isinstance(text, str) and ("bplist" in text or "\x00" in text or len(text) > 5000 and " " not in text[:200]))
        )
        if looks_bad and resolved:
            tpath = resolved.with_suffix(".transcript")
            decoded = load_voicemail_transcript(tpath)
            if decoded and decoded.get("text"):
                item["transcript"] = decoded["text"]
                item["transcript_confidence"] = decoded.get("confidence")
    return item


def _list_voicemails(
    conn: sqlite3.Connection,
    archive_root: Path,
    lookup: dict,
    overrides: Overrides,
    overlay_map: dict,
    *,
    include_ignored: bool = False,
) -> list[dict]:
    if not _table_exists(conn, "voicemails"):
        return []
    rows = conn.execute(
        "SELECT payload_json FROM voicemails ORDER BY date DESC LIMIT 2000"
    ).fetchall()
    items = []
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            continue
        item = _enrich_audio_item(archive_root, payload, kind="voicemail")
        vid = item.get("id") or ""
        ov = overlay_map.get(f"{MODULE_VOICEMAIL}:{vid}") or {}
        if ov.get("ignored") and not include_ignored:
            continue
        item["from_resolved"] = _enrich_handle(item.get("from"), lookup, overrides)
        item["to_resolved"] = _enrich_handle(item.get("to"), lookup, overrides)
        item["notes"] = ov.get("notes")
        item["ignored"] = bool(ov.get("ignored"))
        if ov.get("display_name"):
            item["local_display_name"] = ov["display_name"]
        items.append(item)
    return items


def _list_voicememos(
    conn: sqlite3.Connection,
    archive_root: Path,
    overlay_map: dict,
    *,
    include_ignored: bool = False,
) -> list[dict]:
    if not _table_exists(conn, "voicememos"):
        return []
    rows = conn.execute(
        "SELECT payload_json FROM voicememos ORDER BY date DESC LIMIT 2000"
    ).fetchall()
    items = []
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            continue
        item = _enrich_audio_item(archive_root, payload, kind="voicememo")
        vid = item.get("id") or ""
        ov = overlay_map.get(f"{MODULE_VOICEMEMO}:{vid}") or {}
        if ov.get("ignored") and not include_ignored:
            continue
        if ov.get("display_name"):
            item["title"] = ov["display_name"]
            item["local_display_name"] = ov["display_name"]
        item["notes"] = ov.get("notes")
        item["ignored"] = bool(ov.get("ignored"))
        items.append(item)
    return items


def _list_contacts(
    conn: sqlite3.Connection,
    overrides: Overrides | None = None,
    overlay_map: dict | None = None,
    *,
    limit: int = 10000,
    include_ignored: bool = False,
) -> list[dict]:
    if not _table_exists(conn, "contacts"):
        return []
    overlay_map = overlay_map or {}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
    has_on = "on_device" in cols
    order = "on_device DESC, display_name COLLATE NOCASE" if has_on else "display_name COLLATE NOCASE"
    extra = ", on_device, last_seen_at, first_seen_at, removed_from_device_at" if has_on else ""
    rows = conn.execute(
        f"SELECT id, display_name, payload_json{extra} FROM contacts ORDER BY {order} LIMIT ?",
        (limit,),
    ).fetchall()
    items = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {"id": r["id"], "display_name": r["display_name"]}
        payload = clean_contact_payload(payload)
        cid = payload.get("id") or r["id"]
        ov = overlay_map.get(f"{MODULE_CONTACT}:{cid}") or {}
        if ov.get("ignored") and not include_ignored:
            continue
        if has_on:
            payload["on_device"] = bool(r["on_device"])
            payload["last_seen_at"] = r["last_seen_at"]
            payload["first_seen_at"] = r["first_seen_at"]
            payload["removed_from_device_at"] = r["removed_from_device_at"]

        phone_name = payload.get("display_name")
        db_name = ov.get("display_name")
        yaml_name = None
        if overrides is not None:
            yaml_name = overrides.contact_name(cid)
            if not yaml_name:
                for phone in payload.get("phones") or []:
                    val = phone.get("value") if isinstance(phone, dict) else phone
                    yaml_name = overrides.handle_name(val)
                    if yaml_name:
                        break
        display = db_name or yaml_name or phone_name
        if db_name or yaml_name:
            payload["phone_display_name"] = phone_name
            payload["display_name"] = display
            payload["name_source"] = "override"
        payload["notes"] = ov.get("notes")
        payload["ignored"] = bool(ov.get("ignored"))
        items.append(payload)
    return items


def _list_payloads(conn: sqlite3.Connection, table: str, *, order_by: str, limit: int = 2000) -> list[dict]:
    if not _table_exists(conn, table):
        return []
    rows = conn.execute(
        f"SELECT payload_json FROM {table} ORDER BY {order_by} LIMIT ?", (limit,)
    ).fetchall()
    items = []
    for (payload_json,) in rows:
        try:
            items.append(json.loads(payload_json or "{}"))
        except json.JSONDecodeError:
            continue
    return items


def _list_wifi(
    conn: sqlite3.Connection,
    overlay_map: dict,
    *,
    include_ignored: bool = False,
) -> list[dict]:
    items = _list_payloads(conn, "wifi_networks", order_by="ssid COLLATE NOCASE")
    out = []
    for item in items:
        wid = item.get("id") or item.get("ssid") or ""
        ov = overlay_map.get(f"{MODULE_WIFI}:{wid}") or {}
        if ov.get("ignored") and not include_ignored:
            continue
        if ov.get("display_name"):
            item["ssid_display"] = ov["display_name"]
            item["local_display_name"] = ov["display_name"]
        item["notes"] = ov.get("notes")
        item["ignored"] = bool(ov.get("ignored"))
        out.append(item)
    return out


def _summary(conn: sqlite3.Connection, archive_root: Path) -> dict:
    meta = {}
    if _table_exists(conn, "meta"):
        for k, v in conn.execute("SELECT key, value FROM meta"):
            meta[k] = v
    counts = _counts(conn)
    ensure_overlays_schema(conn)
    ignored = 0
    try:
        ignored = conn.execute("SELECT COUNT(*) FROM overlays WHERE ignored = 1").fetchone()[0]
    except sqlite3.Error:
        pass
    recent_runs = []
    if _table_exists(conn, "runs"):
        for row in conn.execute(
            """
            SELECT id, started_at, finished_at, tool_version, schema_version,
                   commands_json, status, diagnostic
            FROM runs ORDER BY id DESC LIMIT 10
            """
        ):
            d = dict(row)
            try:
                d["commands"] = json.loads(d.pop("commands_json") or "[]")
            except json.JSONDecodeError:
                d["commands"] = []
            recent_runs.append(d)
    return {
        "title": meta.get("device_name") or archive_root.name,
        "archive_root": str(archive_root),
        "counts": counts,
        "meta": meta,
        "ignored_count": ignored,
        "tool_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "recent_runs": recent_runs,
        "whatsapp_note": (
            "This backup has no plaintext ChatStorage.sqlite (WhatsApp E2E chat "
            "backup is likely ON — history is excluded from iTunes backups). "
            "Only ChatStorage.sqlite.enc is present. TouchCopy works with just "
            "the backup password when plaintext ChatStorage is included (E2E off). "
            "Turn off WhatsApp → Chats → Chat Backup → End-to-end encrypted backup, "
            "make a fresh encrypted backup, then re-extract."
        ),
    }


# Large HTML UI kept as one template for a single-file viewer.
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__ — iPhone Archiver</title>
<style>
:root {
  --bg:#0f1419; --panel:#1a222c; --text:#e7ecf1; --muted:#8b9aab;
  --accent:#3d9cf0; --line:#2a3542; --bad:#c45c5c;
}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);
  display:grid;grid-template-columns:360px 1fr;min-height:100vh}
aside{border-right:1px solid var(--line);background:var(--panel);display:flex;flex-direction:column;max-height:100vh}
header{padding:1rem 1.1rem;border-bottom:1px solid var(--line)}
header h1{margin:0;font-size:1.05rem;font-weight:600}
header p{margin:.35rem 0 0;color:var(--muted);font-size:.8rem}
nav{display:flex;flex-wrap:wrap;gap:.35rem;padding:.65rem .85rem;border-bottom:1px solid var(--line)}
nav button{border:1px solid var(--line);background:#121820;color:var(--text);border-radius:999px;
  padding:.28rem .65rem;font:inherit;font-size:.72rem;cursor:pointer}
nav button.active,nav button:hover{border-color:var(--accent);color:#fff}
.toolbar{padding:.55rem .85rem;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:.4rem}
.toolbar input,.toolbar select{width:100%;background:#121820;border:1px solid var(--line);color:var(--text);
  border-radius:8px;padding:.4rem .55rem;font:inherit;font-size:.8rem}
#stats{padding:.55rem 1.1rem;font-size:.7rem;color:var(--muted);border-bottom:1px solid var(--line);
  display:flex;flex-wrap:wrap;gap:.4rem .7rem}
#list{overflow:auto;flex:1}
.row{display:flex;gap:.65rem;align-items:center;width:100%;text-align:left;border:0;cursor:pointer;background:transparent;color:inherit;
  padding:.7rem 1.1rem;border-bottom:1px solid var(--line);font:inherit}
.row:hover,.row.active{background:#243040}
.row .avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;background:#243040;flex-shrink:0}
.row .avatar.ph{display:flex;align-items:center;justify-content:center;font-size:.75rem;color:var(--muted)}
.row .body{min-width:0;flex:1}
.row .id{font-size:.82rem;color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .meta{font-size:.72rem;color:var(--muted);margin-top:.2rem}
.badge{display:inline-block;font-size:.65rem;padding:.1rem .4rem;border-radius:4px;background:#3a2a2a;color:#f0b4b4;margin-left:.35rem}
.badge.local{background:#1e3d2f;color:#a8e6c5}
main{display:flex;flex-direction:column;max-height:100vh}
#detail-title{padding:1rem 1.25rem;border-bottom:1px solid var(--line);background:var(--panel);font-weight:600}
#detail{overflow:auto;flex:1;padding:1rem 1.25rem 2rem}
#messages{display:flex;flex-direction:column-reverse;gap:.65rem}
.msg{max-width:min(640px,92%);padding:.55rem .75rem;border-radius:12px;background:#243447;align-self:flex-start}
.msg.me{align-self:flex-end;background:#1e4d7b}
.msg .from{font-size:.7rem;color:var(--muted);margin-bottom:.2rem}
.msg .date{font-size:.68rem;color:var(--muted);margin-top:.35rem}
.msg .atts a{color:#9fd0ff;font-size:.78rem}
.msg img.inline{display:block;max-width:min(280px,100%);max-height:220px;border-radius:8px;margin-top:.4rem;cursor:zoom-in;object-fit:cover}
.card{border:1px solid var(--line);border-radius:10px;padding:.85rem 1rem;margin-bottom:.65rem;background:#16202a}
.card h3{margin:0 0 .35rem;font-size:.95rem}
.card .muted{color:var(--muted);font-size:.78rem}
.kv{display:grid;grid-template-columns:140px 1fr;gap:.25rem .75rem;font-size:.82rem;margin:.35rem 0}
.kv .k{color:var(--muted)}
.empty{color:var(--muted);padding:2rem}
audio{width:min(100%,420px);margin-top:.4rem}
#lightbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:50;align-items:center;justify-content:center;padding:2rem}
#lightbox.open{display:flex}
#lightbox img{max-width:95vw;max-height:95vh;border-radius:8px}
#lightbox .close{position:absolute;top:1rem;right:1.25rem;color:#fff;font-size:1.5rem;cursor:pointer;background:none;border:0}
@media(max-width:800px){body{grid-template-columns:1fr}aside{max-height:45vh}}
</style>
</head>
<body>
<aside>
  <header><h1>__TITLE__</h1><p>Local archive viewer · v__VERSION__</p></header>
  <nav id="nav"></nav>
  <div class="toolbar">
    <input id="search" type="search" placeholder="Search…" />
    <select id="sort"></select>
    <select id="filter"></select>
  </div>
  <div id="stats" style="display:none"></div>
  <div id="list"></div>
</aside>
<main>
  <div id="detail-title">Select an item</div>
  <div id="detail"><div class="empty">Pick something on the left.</div></div>
</main>
<div id="lightbox"><button class="close" type="button" aria-label="Close">×</button><img alt=""/></div>
<script>
const MODULES = [
  {id:"summary",label:"Summary"},
  {id:"messages",label:"Messages"},
  {id:"voicemail",label:"Voicemail"},
  {id:"voicememos",label:"Voice memos"},
  {id:"contacts",label:"Contacts"},
  {id:"wifi",label:"Wi‑Fi"},
  {id:"whatsapp",label:"WhatsApp"},
];
let module = "summary";
let activeBtn = null;
let cache = {threads:[], contacts:[], voicemails:[], voicememos:[], wifi:[], whatsapp:[], summary:null};
let openThread = null;
let includeIgnored = false;
const MODULE_KEY = {messages:"chat", contacts:"contact", voicemail:"voicemail", voicememos:"voicememo", wifi:"wifi", whatsapp:"whatsapp"};

async function j(url){const r=await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json()}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}
function personLabel(p){if(!p)return""; if(typeof p==="string")return p; if(p.display_name) return `${p.display_name} (${p.handle||""})`; return p.handle||""}
function setDetail(title, html){document.getElementById("detail-title").textContent=title; document.getElementById("detail").innerHTML=html}
function norm(s){return String(s||"").toLowerCase()}

function buildNav(){
  const nav=document.getElementById("nav"); nav.innerHTML="";
  for(const m of MODULES){
    const b=document.createElement("button"); b.type="button"; b.textContent=m.label;
    if(m.id===module) b.classList.add("active");
    b.onclick=()=>{module=m.id; buildNav(); setupControls(); loadModule()};
    nav.appendChild(b);
  }
}
function setupControls(){
  const sort=document.getElementById("sort");
  const filter=document.getElementById("filter");
  const search=document.getElementById("search");
  search.value="";
  document.querySelector(".toolbar").style.display = module==="summary" ? "none" : "flex";
  if(module==="messages"){
    sort.innerHTML=`<option value="last_desc">Newest activity</option><option value="last_asc">Oldest activity</option><option value="name">Name A–Z</option><option value="count">Most messages</option>`;
    filter.innerHTML=`<option value="all">All chats</option><option value="named">Named</option><option value="groups">Groups</option><option value="direct">1:1</option><option value="unknown">Unknown numbers</option><option value="ignored">Show ignored only</option>`;
  } else if(module==="contacts"){
    sort.innerHTML=`<option value="name">Name A–Z</option><option value="seen">Last seen</option>`;
    filter.innerHTML=`<option value="all">All</option><option value="on">On device</option><option value="off">Retained only</option><option value="ignored">Show ignored only</option>`;
  } else if(module==="voicemail"||module==="voicememos"){
    sort.innerHTML=`<option value="date_desc">Newest</option><option value="date_asc">Oldest</option><option value="name">Name A–Z</option>`;
    filter.innerHTML=`<option value="all">All</option><option value="has_audio">Has audio</option><option value="missing_audio">Missing audio</option><option value="ignored">Show ignored only</option>`;
  } else if(module==="wifi"){
    sort.innerHTML=`<option value="name">SSID A–Z</option>`;
    filter.innerHTML=`<option value="all">All</option><option value="ignored">Show ignored only</option>`;
  } else {
    sort.innerHTML=`<option value="date_desc">Newest</option><option value="date_asc">Oldest</option>`;
    filter.innerHTML=`<option value="all">All</option>`;
  }
}

async function loadStats(){ /* stats live on Summary tab */ }

async function saveOverlay(moduleName, itemId, fields){
  const r = await fetch("/api/overlay", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({module: moduleName, item_id: itemId, ...fields})
  });
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

function overlayBar(moduleName, itemId, opts){
  opts = opts || {};
  const nameVal = opts.display_name || "";
  const notesVal = opts.notes || "";
  const ignored = !!opts.ignored;
  const showName = opts.showName !== false;
  return `<div class="card" id="overlay-bar">
    <h3>Local annotations</h3>
    ${showName ? `<div class="kv"><div class="k">Display name</div><div><input id="ov-name" type="text" value="${esc(nameVal)}" placeholder="Override name (groups / titles)" style="width:100%;background:#121820;border:1px solid var(--line);color:var(--text);border-radius:6px;padding:.35rem .5rem"/></div></div>` : ""}
    <div class="kv"><div class="k">Notes</div><div><textarea id="ov-notes" rows="3" style="width:100%;background:#121820;border:1px solid var(--line);color:var(--text);border-radius:6px;padding:.35rem .5rem">${esc(notesVal)}</textarea></div></div>
    <div style="margin-top:.6rem;display:flex;gap:.5rem;flex-wrap:wrap">
      <button type="button" id="ov-save">Save</button>
      <button type="button" id="ov-ignore">${ignored ? "Un-ignore" : "Ignore / hide"}</button>
      ${showName ? `<button type="button" id="ov-clear-name">Clear name</button>` : ""}
      <button type="button" id="ov-clear-notes">Clear notes</button>
    </div>
  </div>`;
}

function wireOverlayBar(moduleName, itemId, opts={}){
  const showName = opts.showName !== false;
  const save = async (extra={})=>{
    const fields = {...extra};
    if(showName){
      const el = document.getElementById("ov-name");
      if(el) fields.display_name = el.value;
    }
    const notes = document.getElementById("ov-notes");
    if(notes) fields.notes = notes.value;
    await saveOverlay(moduleName, itemId, fields);
    await loadModule();
  };
  document.getElementById("ov-save")?.addEventListener("click", ()=>save().catch(e=>alert(e)));
  document.getElementById("ov-ignore")?.addEventListener("click", ()=>{
    save({ignored: !opts.ignored}).catch(e=>alert(e));
  });
  document.getElementById("ov-clear-name")?.addEventListener("click", ()=>saveOverlay(moduleName, itemId, {clear_display_name:true}).then(()=>loadModule()).catch(e=>alert(e)));
  document.getElementById("ov-clear-notes")?.addEventListener("click", ()=>saveOverlay(moduleName, itemId, {clear_notes:true}).then(()=>loadModule()).catch(e=>alert(e)));
}

async function loadModule(){
  activeBtn=null; openThread=null;
  const q = includeIgnored ? "?include_ignored=1" : "";
  if(module==="summary"){
    document.getElementById("list").innerHTML = `<div class="empty">Archive overview</div>`;
    cache.summary = await j("/api/summary");
    showSummary(cache.summary);
    return;
  }
  document.getElementById("list").innerHTML=`<div class="empty">Loading…</div>`;
  setDetail(MODULES.find(m=>m.id===module).label, `<div class="empty">Pick an item.</div>`);
  if(module==="messages"){ cache.threads=(await j("/api/threads"+q)).threads; renderList(); return }
  if(module==="contacts"){ cache.contacts=(await j("/api/contacts"+q)).contacts; renderList(); return }
  if(module==="voicemail"){ cache.voicemails=(await j("/api/voicemails"+q)).items; renderList(); return }
  if(module==="voicememos"){ cache.voicememos=(await j("/api/voicememos"+q)).items; renderList(); return }
  if(module==="wifi"){ cache.wifi=(await j("/api/wifi"+q)).items; renderList(); return }
  if(module==="whatsapp"){
    cache.whatsapp=(await j("/api/whatsapp")).items;
    if(!cache.whatsapp.length){
      const s = cache.summary || await j("/api/summary");
      document.getElementById("list").innerHTML=`<div class="empty">No WhatsApp messages archived.</div>`;
      setDetail("WhatsApp", `<div class="card"><p>${esc(s.whatsapp_note||"")}</p></div>`);
      return;
    }
    renderList();
  }
}

function showSummary(s){
  const c = s.counts || {};
  const m = s.meta || {};
  const rows = [
    ["Device", m.device_name || s.title],
    ["Product", [m.product_name, m.product_type].filter(Boolean).join(" · ")],
    ["iOS", [m.product_version, m.build_version].filter(Boolean).join(" · ")],
    ["Phone", m.phone_number],
    ["Backup finished", m.backup_finished_at],
    ["Backup started", m.backup_started_at],
    ["Snapshot", m.snapshot_state],
    ["Full backup?", m.is_full_backup === "1" ? "yes" : (m.is_full_backup === "0" ? "no" : m.is_full_backup)],
    ["Last extract run", m.last_run],
    ["Last run finished", m.last_run_finished],
    ["Last run status", m.last_run_status],
    ["Extracted with tool", m.last_run_tool_version || m.tool_version],
    ["Archive schema", m.schema_version || m.last_run_schema_version],
    ["Viewer tool", s.tool_version],
    ["Viewer schema expect", s.schema_version],
    ["Backup id", m.backup_id],
    ["Ignored items", s.ignored_count],
  ];
  const countPrefer = ["messages","contacts","contacts_on_device","contacts_retained","voicemails","voicememos","wifi_networks","whatsapp_messages","attachments"];
  let html = `<div class="card"><h3>Backup & device</h3><div class="kv">${rows.filter(([,v])=>v!=null&&v!=="").map(([k,v])=>`<div class="k">${esc(k)}</div><div>${esc(v)}</div>`).join("")}</div></div>`;
  html += `<div class="card"><h3>Archive counts</h3><div class="kv">${countPrefer.filter(k=>c[k]!=null).map(k=>`<div class="k">${esc(k)}</div><div><strong>${esc(c[k])}</strong></div>`).join("")}</div></div>`;
  const runs = s.recent_runs || [];
  if(runs.length){
    html += `<div class="card"><h3>Recent extract runs</h3><div class="kv">${runs.map(r=>{
      const cmds=(r.commands||[]).join(", ");
      const label=[r.started_at, r.status, `v${r.tool_version}`, `schema ${r.schema_version}`, cmds].filter(Boolean).join(" · ");
      return `<div class="k">#${esc(r.id)}</div><div>${esc(label)}</div>`;
    }).join("")}</div></div>`;
  }
  html += `<div class="card"><h3>WhatsApp</h3><p class="muted">${esc(s.whatsapp_note||"")}</p></div>`;
  html += `<div class="card"><h3>Paths</h3><div class="muted">${esc(s.archive_root||"")}</div></div>`;
  setDetail("Summary", html);
}

function filteredSorted(){
  const q=norm(document.getElementById("search").value);
  const sort=document.getElementById("sort").value;
  const filter=document.getElementById("filter").value;
  let items=[];
  if(module==="messages"){
    items=cache.threads.filter(t=>{
      const label=norm(t.display_name||t.chat_identifier||t.chat_id);
      if(q && !label.includes(q) && !norm(t.chat_identifier).includes(q)) return false;
      if(filter==="named" && !t.display_name) return false;
      if(filter==="unknown" && t.display_name) return false;
      if(filter==="groups" && !t.is_group) return false;
      if(filter==="direct" && t.is_group) return false;
      if(filter==="ignored" && !t.ignored) return false;
      return true;
    });
    items.sort((a,b)=>{
      if(sort==="name") return (a.display_name||a.chat_identifier||"").localeCompare(b.display_name||b.chat_identifier||"");
      if(sort==="count") return (b.message_count||0)-(a.message_count||0);
      if(sort==="last_asc") return String(a.last_date||"").localeCompare(String(b.last_date||""));
      return String(b.last_date||"").localeCompare(String(a.last_date||""));
    });
  } else if(module==="contacts"){
    items=cache.contacts.filter(c=>{
      const blob=norm(JSON.stringify(c));
      if(q && !blob.includes(q)) return false;
      if(filter==="on" && c.on_device===false) return false;
      if(filter==="off" && c.on_device!==false) return false;
      if(filter==="ignored" && !c.ignored) return false;
      return true;
    });
    items.sort((a,b)=>{
      if(sort==="seen") return String(b.last_seen_at||"").localeCompare(String(a.last_seen_at||""));
      return String(a.display_name||"").localeCompare(String(b.display_name||""));
    });
  } else if(module==="voicemail"){
    items=cache.voicemails.filter(v=>{
      const label=norm(personLabel(v.from_resolved)||v.from||v.transcript||v.id);
      if(q && !label.includes(q) && !norm(v.transcript).includes(q)) return false;
      const ok=!!(v.audio&&v.audio.exists);
      if(filter==="has_audio" && !ok) return false;
      if(filter==="missing_audio" && ok) return false;
      return true;
    });
    items.sort((a,b)=>{
      if(sort==="name") return String(personLabel(a.from_resolved)||a.from||"").localeCompare(String(personLabel(b.from_resolved)||b.from||""));
      if(sort==="date_asc") return String(a.date||"").localeCompare(String(b.date||""));
      return String(b.date||"").localeCompare(String(a.date||""));
    });
  } else if(module==="voicememos"){
    items=cache.voicememos.filter(v=>{
      if(q && !norm(v.title||v.filename||"").includes(q)) return false;
      const ok=!!(v.audio&&v.audio.exists);
      if(filter==="has_audio" && !ok) return false;
      if(filter==="missing_audio" && ok) return false;
      return true;
    });
    items.sort((a,b)=>{
      if(sort==="name") return String(a.title||"").localeCompare(String(b.title||""));
      if(sort==="date_asc") return String(a.date||"").localeCompare(String(b.date||""));
      return String(b.date||"").localeCompare(String(a.date||""));
    });
  } else if(module==="wifi"){
    items=cache.wifi.filter(w=>!q || norm(w.ssid||w.id).includes(q));
    items.sort((a,b)=>String(a.ssid||"").localeCompare(String(b.ssid||"")));
  } else if(module==="whatsapp"){
    items=cache.whatsapp.filter(w=>!q || norm(w.text||"").includes(q) || norm(w.from||"").includes(q));
    items.sort((a,b)=>{
      if(sort==="date_asc") return String(a.date||"").localeCompare(String(b.date||""));
      return String(b.date||"").localeCompare(String(a.date||""));
    });
  }
  return items;
}

function renderList(){
  const items=filteredSorted();
  const root=document.getElementById("list"); root.innerHTML="";
  if(!items.length){ root.innerHTML=`<div class="empty">No matches.</div>`; return }
  for(const item of items){
    const btn=document.createElement("button"); btn.className="row"; btn.type="button";
    if(module==="messages"){
      const label=item.display_name||item.chat_identifier||("chat "+item.chat_id);
      const sub=item.chat_identifier && item.display_name && item.display_name!==item.chat_identifier ? item.chat_identifier+" · " : "";
      const badge=item.name_source==="override"?'<span class="badge local">local</span>':"";
      const av=item.group_photo_url
        ? `<img class="avatar" src="${esc(item.group_photo_url)}" alt=""/>`
        : `<div class="avatar ph">${esc((label||"?").slice(0,2))}</div>`;
      btn.innerHTML=`${av}<div class="body"><div class="id">${esc(label)}${badge}</div><div class="meta">${esc(sub)}${esc(item.message_count)} msgs · last ${esc(item.last_date||"—")}</div></div>`;
      btn.onclick=()=>showThread(item, btn);
    } else if(module==="contacts"){
      const gone=item.on_device===false;
      btn.innerHTML=`<div class="id">${esc(item.display_name||item.id)}${gone?'<span class="badge">not on device</span>':""}</div>
        <div class="meta">${esc((item.phones||[]).map(p=>p.value).filter(Boolean).slice(0,2).join(" · ")||(item.emails||[]).map(e=>e.value).slice(0,1).join("")||"")}</div>`;
      btn.onclick=()=>showContact(item, btn);
    } else if(module==="voicemail"){
      const title=personLabel(item.from_resolved)||item.from||item.id;
      btn.innerHTML=`<div class="id">${esc(title)}</div><div class="meta">${esc(item.date||"")} · ${esc(item.duration_sec??"?")}s ${(item.audio&&item.audio.exists)?"":"· missing audio"}</div>`;
      btn.onclick=()=>showVoicemail(item, btn);
    } else if(module==="voicememos"){
      btn.innerHTML=`<div class="id">${esc(item.title||item.filename||item.id)}</div><div class="meta">${esc(item.date||"")} ${(item.audio&&item.audio.exists)?"":"· missing audio"}</div>`;
      btn.onclick=()=>showMemo(item, btn);
    } else if(module==="wifi"){
      const label = item.ssid_display || item.ssid || item.id;
      btn.innerHTML=`<div class="id">${esc(label)}</div><div class="meta">${esc(item.bssid||item.security||"")}</div>`;
      btn.onclick=()=>{
        activate(btn);
        let html = overlayBar("wifi", item.id, {
          display_name: item.local_display_name || "",
          notes: item.notes || "",
          ignored: item.ignored,
          showName: true
        });
        html += `<div class="card"><pre style="white-space:pre-wrap;font-size:.78rem;color:var(--muted)">${esc(JSON.stringify(item,null,2))}</pre></div>`;
        setDetail(label, html);
        wireOverlayBar("wifi", item.id, {ignored: item.ignored, showName: true});
      };
    } else if(module==="whatsapp"){
      btn.innerHTML=`<div class="id">${esc((item.text||"").slice(0,80)||item.id)}</div><div class="meta">${esc(item.from||"")} · ${esc(item.date||"")}</div>`;
      btn.onclick=()=>{activate(btn); setDetail(item.id, `<div class="card"><pre style="white-space:pre-wrap;font-size:.78rem;color:var(--muted)">${esc(JSON.stringify(item,null,2))}</pre></div>`)};
    }
    root.appendChild(btn);
  }
}

function activate(btn){ if(activeBtn) activeBtn.classList.remove("active"); activeBtn=btn; btn.classList.add("active") }

async function showThread(t, btn){
  activate(btn); openThread=t;
  const title=(t.display_name||t.chat_identifier||t.chat_id)+" · "+t.message_count+" messages";
  setDetail(title, `<div class="empty">Loading…</div>`);
  const q=document.getElementById("search").value.trim();
  const data=await j(`/api/messages?chat_id=${encodeURIComponent(t.chat_id)}&limit=400&q=${encodeURIComponent(q)}`);
  const box=document.createElement("div"); box.id="messages";
  let head = overlayBar("chat", t.chat_id, {
    display_name: t.local_display_name || "",
    notes: t.notes || "",
    ignored: t.ignored,
    showName: true
  });
  if(t.group_photo_url) head = `<div class="card"><img src="${esc(t.group_photo_url)}" alt="" style="max-width:96px;border-radius:12px"/></div>` + head;
  if(!data.messages.length){
    setDetail(title, head + `<div class="empty">No messages${q?" matching search":""}.</div>`);
    wireOverlayBar("chat", t.chat_id, {ignored: t.ignored, showName: true});
    return;
  }
  for(const m of data.messages){
    const div=document.createElement("div");
    div.className="msg"+(m.is_from_me?" me":"");
    let atts="";
    for(const a of (m.attachments||[])){
      if(a.is_image && a.url){
        atts+=`<img class="inline" src="${esc(a.url)}" alt="${esc(a.original_filename||a.filename||"image")}" data-full="${esc(a.url)}" loading="lazy"/>`;
      } else if(a.url){
        atts+=`<div class="atts"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.original_filename||a.filename||a.path)}</a></div>`;
      }
    }
    div.innerHTML=`<div class="from">${esc(personLabel(m.from))} · ${esc(m.service||"")}</div>
      <div>${esc(m.text||(atts?"":"(no text)"))}</div>${atts}
      <div class="date">${esc(m.date||"")}</div>`;
    box.appendChild(div);
  }
  document.getElementById("detail").innerHTML = head;
  document.getElementById("detail").appendChild(box);
  wireOverlayBar("chat", t.chat_id, {ignored: t.ignored, showName: true});
  box.querySelectorAll("img.inline").forEach(img=>{
    img.addEventListener("click",()=>openLightbox(img.dataset.full||img.src));
  });
}

function showContact(c, btn){
  activate(btn);
  const gone=c.on_device===false;
  const name=c.name||{};
  const rows=[];
  const add=(k,v)=>{ if(v===null||v===undefined||v==="") return; rows.push(`<div class="k">${esc(k)}</div><div>${esc(typeof v==="object"?JSON.stringify(v):v)}</div>`) };
  add("ID", c.id);
  add("Organization", c.organization);
  add("First", name.first); add("Middle", name.middle); add("Last", name.last); add("Nickname", name.nickname);
  add("Birthday", c.birthday);
  add("Address book note", c.note);
  add("On device", gone ? "no (retained)" : "yes");
  add("First seen", c.first_seen_at || (c.lifecycle&&c.lifecycle.first_seen_at));
  add("Last seen", c.last_seen_at || (c.lifecycle&&c.lifecycle.last_seen_at));
  add("Removed", c.removed_from_device_at || (c.lifecycle&&c.lifecycle.removed_from_device_at));
  let blocks = overlayBar("contact", c.id, {
    display_name: c.name_source==="override" ? c.display_name : "",
    notes: c.notes || "",
    ignored: c.ignored,
    showName: true
  });
  blocks+=`<div class="card"><h3>${esc(c.display_name||c.id)}</h3><div class="kv">${rows.join("")}</div></div>`;
  const listBlock=(title, arr, fmt)=>{
    if(!arr||!arr.length) return "";
    return `<div class="card"><h3>${title}</h3>${arr.map(fmt).join("")}</div>`;
  };
  blocks+=listBlock("Phones", c.phones, p=>`<div>${esc(p.label||"phone")}: <strong>${esc(p.value)}</strong></div>`);
  blocks+=listBlock("Emails", c.emails, p=>`<div>${esc(p.label||"email")}: <strong>${esc(p.value)}</strong></div>`);
  blocks+=listBlock("URLs", c.urls, p=>`<div>${esc(p.label||"url")}: ${esc(p.value)}</div>`);
  blocks+=listBlock("Dates", c.dates, p=>`<div>${esc(p.label||"date")}: <strong>${esc(p.date||p.raw||"")}</strong></div>`);
  blocks+=listBlock("Other multi-values", c.extended_multivalues, p=>`<div>${esc(p.label||("prop "+p.property))}: ${esc(p.value)}</div>`);
  const ef=c.extended_fields||{};
  const efKeys=Object.keys(ef);
  if(efKeys.length){
    blocks+=`<div class="card"><h3>Extended fields</h3><div class="kv">${efKeys.map(k=>`<div class="k">${esc(k)}</div><div>${esc(typeof ef[k]==="object"?JSON.stringify(ef[k]):ef[k])}</div>`).join("")}</div></div>`;
  }
  setDetail(c.display_name||c.id, blocks);
  wireOverlayBar("contact", c.id, {ignored: c.ignored, showName: true});
}

function showVoicemail(v, btn){
  activate(btn);
  const title=v.local_display_name || personLabel(v.from_resolved)||v.from||v.id;
  const audio=v.audio||{};
  let html = overlayBar("voicemail", v.id, {
    display_name: v.local_display_name || "",
    notes: v.notes || "",
    ignored: v.ignored,
    showName: true
  });
  html+=`<div class="card"><div class="muted">${esc(v.id)}</div>
    <div class="kv">
      <div class="k">From</div><div>${esc(personLabel(v.from_resolved)||v.from||"—")}</div>
      <div class="k">To</div><div>${esc(personLabel(v.to_resolved)||v.to||"—")}</div>
      <div class="k">Date</div><div>${esc(v.date||"—")}</div>
      <div class="k">Duration</div><div>${esc(v.duration_sec??"—")}s</div>
      <div class="k">Callback</div><div>${esc(v.callback_number||"—")}</div>
    </div>`;
  if(audio.url) html+=`<audio controls preload="metadata" src="${esc(audio.url)}"></audio>`;
  else html+=`<div class="muted">Audio file not found on disk.</div>`;
  if(v.transcript) html+=`<h3 style="margin-top:1rem">Transcript</h3><p style="white-space:pre-wrap">${esc(v.transcript)}</p>`;
  if(v.transcript_confidence!=null) html+=`<div class="muted">confidence ${esc(v.transcript_confidence)}</div>`;
  html+=`</div>`;
  setDetail(title, html);
  wireOverlayBar("voicemail", v.id, {ignored: v.ignored, showName: true});
}

function showMemo(v, btn){
  activate(btn);
  const audio=v.audio||{};
  let html = overlayBar("voicememo", v.id, {
    display_name: v.local_display_name || v.title || "",
    notes: v.notes || "",
    ignored: v.ignored,
    showName: true
  });
  html+=`<div class="card"><div class="muted">${esc(v.id)}</div>
    <div class="kv"><div class="k">Date</div><div>${esc(v.date||"—")}</div>
    <div class="k">File</div><div>${esc(v.filename||audio.path||"—")}</div></div>`;
  if(audio.url) html+=`<audio controls preload="metadata" src="${esc(audio.url)}"></audio>`;
  else html+=`<div class="muted">Audio file not found on disk (looked under blobs/voicememos/…).</div>`;
  html+=`</div>`;
  setDetail(v.title||v.filename||v.id, html);
  wireOverlayBar("voicememo", v.id, {ignored: v.ignored, showName: true});
}

function openLightbox(src){
  const lb=document.getElementById("lightbox");
  lb.querySelector("img").src=src; lb.classList.add("open");
}
document.getElementById("lightbox").addEventListener("click",e=>{
  if(e.target.id==="lightbox"||e.target.classList.contains("close")) document.getElementById("lightbox").classList.remove("open");
});
document.getElementById("search").addEventListener("input", ()=>{
  if(module==="messages" && openThread){ showThread(openThread, activeBtn); }
  else renderList();
});
document.getElementById("sort").addEventListener("change", renderList);
document.getElementById("filter").addEventListener("change", ()=>{
  const f = document.getElementById("filter").value;
  const wantIgnored = f === "ignored";
  if(wantIgnored !== includeIgnored){
    includeIgnored = wantIgnored;
    loadModule().catch(e=>alert(e));
  } else {
    renderList();
  }
});

buildNav(); setupControls();
loadModule().catch(e=>alert(e));
</script>
</body>
</html>
"""


class ViewerHandler(BaseHTTPRequestHandler):
    archive_root: Path
    db_path: Path
    title: str
    cache_root: Path
    overrides: Overrides

    def log_message(self, fmt: str, *args) -> None:
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: object) -> None:
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            html = (
                INDEX_HTML.replace("__TITLE__", self.title)
                .replace("__VERSION__", __version__)
                .encode("utf-8")
            )
            self._send(200, html, "text/html; charset=utf-8")
            return

        if path == "/media/" or path.startswith("/media/"):
            rel = unquote(path[len("/media/") :])
            media = resolve_media_path(self.archive_root, rel)
            if not media:
                self._json(404, {"error": "not found", "path": rel})
                return
            ctype = mimetypes.guess_type(str(media))[0] or "application/octet-stream"
            self._send(200, media.read_bytes(), ctype)
            return

        if path == "/play":
            rel = (qs.get("path") or [""])[0]
            media = resolve_media_path(self.archive_root, rel)
            if not media:
                self._json(404, {"error": "not found", "path": rel})
                return
            out = media
            if needs_audio_transcode(media):
                converted = convert_for_browser(media, self.cache_root, kind="audio")
                if not converted:
                    self._json(500, {"error": "audio transcode failed (is ffmpeg available?)"})
                    return
                out = converted
            elif needs_image_transcode(media):
                converted = convert_for_browser(media, self.cache_root, kind="image")
                if not converted:
                    self._json(500, {"error": "image transcode failed (is ffmpeg available?)"})
                    return
                out = converted
            ctype = mimetypes.guess_type(str(out))[0] or "application/octet-stream"
            self._send(200, out.read_bytes(), ctype)
            return

        conn = _connect(self.db_path)
        try:
            ensure_overlays_schema(conn)
            lookup = build_contact_lookup(conn)
            overrides = self.overrides
            overlay_map = load_overlays_map(conn)
            include_ignored = (qs.get("include_ignored") or ["0"])[0] in ("1", "true", "yes")

            if path == "/api/summary":
                self._json(200, _summary(conn, self.archive_root))
                return

            if path == "/api/stats":
                self._json(200, _summary(conn, self.archive_root))
                return

            if path == "/api/threads":
                self._json(
                    200,
                    {
                        "threads": _threads(
                            conn,
                            lookup,
                            overrides,
                            overlay_map,
                            include_ignored=include_ignored,
                        )
                    },
                )
                return

            if path == "/api/messages":
                chat_id = (qs.get("chat_id") or [""])[0]
                if not chat_id:
                    self._json(400, {"error": "chat_id required"})
                    return
                limit = int((qs.get("limit") or ["200"])[0])
                offset = int((qs.get("offset") or ["0"])[0])
                q = (qs.get("q") or [""])[0]
                ov = get_overlay(conn, MODULE_CHAT, chat_id) or {}
                self._json(
                    200,
                    {
                        "chat_id": chat_id,
                        "overlay": ov,
                        "messages": _messages_for_chat(
                            conn,
                            lookup,
                            self.archive_root,
                            chat_id,
                            overrides=overrides,
                            limit=min(limit, 1000),
                            offset=offset,
                            q=q,
                        ),
                    },
                )
                return

            if path == "/api/contacts":
                self._json(
                    200,
                    {
                        "contacts": _list_contacts(
                            conn,
                            overrides,
                            overlay_map,
                            include_ignored=include_ignored,
                        )
                    },
                )
                return

            if path == "/api/voicemails":
                self._json(
                    200,
                    {
                        "items": _list_voicemails(
                            conn,
                            self.archive_root,
                            lookup,
                            overrides,
                            overlay_map,
                            include_ignored=include_ignored,
                        )
                    },
                )
                return

            if path == "/api/voicememos":
                self._json(
                    200,
                    {
                        "items": _list_voicememos(
                            conn,
                            self.archive_root,
                            overlay_map,
                            include_ignored=include_ignored,
                        )
                    },
                )
                return

            if path == "/api/wifi":
                self._json(
                    200,
                    {"items": _list_wifi(conn, overlay_map, include_ignored=include_ignored)},
                )
                return

            if path == "/api/whatsapp":
                self._json(
                    200,
                    {
                        "items": _list_payloads(
                            conn, "whatsapp_messages", order_by="date DESC", limit=2000
                        )
                    },
                )
                return

            self._json(404, {"error": "not found"})
        finally:
            conn.close()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/overlay":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        module = str(body.get("module") or "").strip()
        item_id = str(body.get("item_id") or "").strip()
        if not module or not item_id:
            self._json(400, {"error": "module and item_id required"})
            return
        allowed = {
            MODULE_CHAT,
            MODULE_CONTACT,
            MODULE_VOICEMAIL,
            MODULE_VOICEMEMO,
            MODULE_WIFI,
            MODULE_WHATSAPP,
        }
        if module not in allowed:
            self._json(400, {"error": f"unknown module {module}"})
            return
        conn = _connect(self.db_path)
        try:
            result = upsert_overlay(
                conn,
                module=module,
                item_id=item_id,
                display_name=body.get("display_name") if "display_name" in body else None,
                notes=body.get("notes") if "notes" in body else None,
                ignored=body.get("ignored") if "ignored" in body else None,
                clear_display_name=bool(body.get("clear_display_name")),
                clear_notes=bool(body.get("clear_notes")),
            )
            self._json(200, {"ok": True, "overlay": result})
        finally:
            conn.close()


def run_viewer(
    archive_root: Path,
    *,
    port: int | None = None,
    host: str | None = None,
    open_browser: bool = True,
) -> int:
    archive_root = archive_root.resolve()
    settings = viewer_settings(archive_root, port=port, host=host)
    db_path = (archive_root / settings["db"]).resolve()
    if not db_path.is_file():
        raise SystemExit(
            f"No archive DB at {db_path}. Run an extract into this folder first."
        )

    ViewerHandler.archive_root = archive_root
    ViewerHandler.db_path = db_path
    ViewerHandler.title = settings["title"]
    ViewerHandler.cache_root = archive_root / ".viewer-cache"
    ViewerHandler.overrides = load_overrides(archive_root)

    server = ThreadingHTTPServer((settings["host"], settings["port"]), ViewerHandler)
    url = f"http://{settings['host']}:{settings['port']}/"
    print(f"Viewer: {url}")
    print(f"Archive: {archive_root}")
    print(f"DB: {db_path}")
    print("Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0
