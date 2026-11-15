from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from iphone_backup_decrypt import EncryptedBackup, RelativePath

from ..archive import Archive, sha256_file
from ..attributed_body import decode_attributed_body
from ..backup_io import extract_file, extract_like
from ..chat_props import parse_chat_properties
from ..dates import apple_date_to_iso, utc_now_iso
from ..report import CategoryReport


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _safe_thread_key(chat_id: int, chat_identifier: str, display: str) -> str:
    label = (chat_identifier or display or f"chat-{chat_id}").strip()
    cleaned = re.sub(r"[^\w.\-+@]+", "_", label, flags=re.UNICODE)[:80].strip(" ._")
    return f"{int(chat_id):04d}_{cleaned or f'chat-{chat_id}'}"


def _normalize_attachment_rel(filename: str | None) -> str | None:
    if not filename:
        return None
    name = filename.replace("\\", "/")
    if name.startswith("~/"):
        name = name[2:]
    for marker in (
        "Library/SMS/Attachments/",
        "Library/SMS/StickerCache/",
        "Library/SMS/",
    ):
        if marker in name:
            return name[name.index(marker) :]
    return name


_REACTION_TYPES = {
    2000: "love",
    2001: "like",
    2002: "dislike",
    2003: "laugh",
    2004: "emphasize",
    2005: "question",
    2006: "emoji",  # custom emoji tapback (newer iOS)
}


def _bool_or_none(row: dict, key: str, enabled: bool) -> bool | None:
    if not enabled or row.get(key) is None:
        return None
    return bool(row[key])


def _prune(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != "" and v != []}


def _ext_for_attachment(transfer_name: str | None, filename: str | None, mime: str | None) -> str:
    for candidate in (transfer_name, filename):
        if candidate:
            suffix = Path(candidate.replace("\\", "/")).suffix
            if suffix and len(suffix) <= 12:
                return suffix.lower()
    mime = (mime or "").lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "image/heic-sequence": ".heics",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "audio/amr": ".amr",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "application/pdf": ".pdf",
        "text/vcard": ".vcf",
        "text/x-vcard": ".vcf",
    }
    return mapping.get(mime, "")


def _attachment_filename(att_id: str, transfer_name: str | None, filename: str | None, mime: str | None) -> str:
    # Stable unique name: lowercase guid/uuid + original extension when known
    stem = re.sub(r"[^0-9a-fA-F\-]", "", att_id).lower() or re.sub(r"[^\w.\-]+", "_", att_id).lower()
    ext = _ext_for_attachment(transfer_name, filename, mime)
    return f"{stem}{ext}"


def _place_file(src: Path, dest: Path) -> tuple[bool, str | None]:
    """Copy/link src -> dest if needed. Returns (ok, note). Append-only: never overwrite differing bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if sha256_file(dest) == sha256_file(src):
            return True, None
        return False, f"destination exists with different content: {dest.name}"
    try:
        # Prefer hardlink to avoid duplicating large media when staging + archive share a volume
        dest.hardlink_to(src)
        return True, None
    except OSError:
        try:
            shutil.copy2(src, dest)
            return True, None
        except OSError as exc:
            return False, f"copy failed: {exc}"


def _load_jsonl_by_id(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    out: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = obj.get("id")
            if mid:
                out[mid] = obj
    return out


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def extract_messages(
    backup: EncryptedBackup,
    *,
    archive: Archive,
    work: Path,
    messages_dir: Path,
    backup_id: str,
    export_dir: Path | None = None,
) -> CategoryReport:
    """
    Denormalized append-only message archive:

      out/messages/{thread}/
        {thread}.jsonl          # one message per line (upsert by guid)
        {attachment-guid}.ext   # media files beside the jsonl
    """
    report = CategoryReport(category="messages", status="failed")
    raw = work / "sms"
    raw.mkdir(parents=True, exist_ok=True)
    messages_dir.mkdir(parents=True, exist_ok=True)
    sms_db = raw / "sms.db"

    try:
        extract_file(backup, RelativePath.TEXT_MESSAGES, sms_db)
    except Exception as exc:  # noqa: BLE001
        report.note(f"Failed to extract sms.db: {exc}")
        return report

    for sidecar in ("Library/SMS/sms.db-wal", "Library/SMS/sms.db-shm"):
        try:
            extract_file(backup, sidecar, raw / Path(sidecar).name)
        except Exception:
            pass

    # Stage decrypted attachments + stickers (MediaDomain), then place into thread folders
    staging = work / "sms_attachments_staging"
    n_att_files = 0
    for label, pattern in (
        ("Attachments", "Library/SMS/Attachments/%"),
        ("StickerCache", "Library/SMS/StickerCache/%"),
    ):
        try:
            n = extract_like(
                backup,
                relative_paths_like=pattern,
                domain_like="MediaDomain",
                output_folder=staging,
                preserve_folders=True,
            )
            n_att_files += n
            report.note(f"{label} decrypted from backup: {n}")
        except Exception as exc:  # noqa: BLE001
            report.note(f"{label} extract error: {exc}")

    extracted_index: dict[str, Path] = {}
    for p in staging.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(staging).as_posix()
        extracted_index[rel] = p
        for marker in ("Library/SMS/Attachments/", "Library/SMS/StickerCache/", "Library/SMS/"):
            if marker in rel:
                extracted_index[rel[rel.index(marker) :]] = p
        extracted_index[p.name] = p

    conn = sqlite3.connect(str(sms_db))
    conn.row_factory = sqlite3.Row
    # Second connection for attributedBody lookups while iterating the main cursor
    conn_blobs = sqlite3.connect(str(sms_db))
    msg_cols = _cols(conn, "message")
    att_cols = _cols(conn, "attachment")

    me_candidates: set[str] = set()
    if "destination_caller_id" in msg_cols:
        for (v,) in conn.execute(
            "SELECT DISTINCT destination_caller_id FROM message WHERE destination_caller_id IS NOT NULL"
        ):
            if v:
                me_candidates.add(str(v))

    chat_handles: dict[int, list[str]] = {}
    try:
        for row in conn.execute(
            """
            SELECT chj.chat_id, h.id
            FROM chat_handle_join chj
            JOIN handle h ON h.ROWID = chj.handle_id
            """
        ):
            chat_handles.setdefault(int(row[0]), []).append(row[1])
    except sqlite3.Error:
        pass

    attachments_by_msg: dict[int, list[dict[str, Any]]] = {}
    try:
        present = []
        wanted = [
            "guid",
            "filename",
            "mime_type",
            "total_bytes",
            "transfer_name",
            "is_outgoing",
            "created_date",
            "transfer_state",
            "hide_attachment",
            "is_sticker",
            "uti",
            "original_guid",
        ]
        for col in wanted:
            if col in att_cols:
                present.append(f"a.{col} AS {col}")
            else:
                present.append(f"NULL AS {col}")
        sel = f"""
            SELECT maj.message_id, a.ROWID AS attachment_id, {", ".join(present)}
            FROM message_attachment_join maj
            JOIN attachment a ON a.ROWID = maj.attachment_id
        """
        for row in conn.execute(sel):
            d = dict(row)
            attachments_by_msg.setdefault(int(d["message_id"]), []).append(d)
    except sqlite3.Error as exc:
        report.note(f"attachment join query failed: {exc}")

    # GUID -> attachment row (for group photos etc.)
    att_by_guid: dict[str, dict[str, Any]] = {}
    try:
        present = []
        wanted = ["guid", "filename", "mime_type", "transfer_name", "total_bytes", "uti"]
        for col in wanted:
            if col in att_cols:
                present.append(f"{col}")
            else:
                present.append(f"NULL AS {col}")
        for row in conn.execute(f"SELECT ROWID AS attachment_id, {', '.join(present)} FROM attachment"):
            d = dict(row)
            g = (d.get("guid") or "").lower().strip()
            if g:
                att_by_guid[g] = d
    except sqlite3.Error as exc:
        report.note(f"attachment guid index failed: {exc}")

    chats = []
    chat_cols = _cols(conn, "chat")
    chat_select = [
        "c.ROWID AS chat_id",
        "COALESCE(c.display_name, '') AS display_name",
        "COALESCE(c.chat_identifier, '') AS chat_identifier",
        "COALESCE(c.room_name, '') AS room_name",
        (
            "(SELECT COUNT(*) FROM chat_message_join cmj WHERE cmj.chat_id = c.ROWID) "
            "AS message_count"
        ),
    ]
    if "guid" in chat_cols:
        chat_select.append("c.guid AS chat_guid")
    else:
        chat_select.append("NULL AS chat_guid")
    if "properties" in chat_cols:
        chat_select.append("c.properties AS properties")
    else:
        chat_select.append("NULL AS properties")
    if "style" in chat_cols:
        chat_select.append("c.style AS style")
    else:
        chat_select.append("NULL AS style")
    for c in conn.execute(f"SELECT {', '.join(chat_select)} FROM chat c"):
        d = dict(c)
        if (d.get("message_count") or 0) > 0:
            chats.append(d)

    # Columns we select when present (attributedBody handled separately)
    optional_cols = [
        "guid",
        "date_delivered",
        "date_read",
        "date_played",
        "date_edited",
        "date_retracted",
        "is_delivered",
        "is_read",
        "is_sent",
        "is_finished",
        "error",
        "service",
        "subject",
        "account",
        "account_guid",
        "destination_caller_id",
        "cache_has_attachments",
        "is_audio_message",
        "is_played",
        "is_system_message",
        "is_emote",
        "is_spam",
        "is_empty",
        "was_downgraded",
        "was_delivered_quietly",
        "did_notify_recipient",
        "associated_message_guid",
        "associated_message_type",
        "associated_message_emoji",
        "reply_to_guid",
        "thread_originator_guid",
        "thread_originator_part",
        "expressive_send_style_id",
        "balloon_bundle_id",
        "item_type",
        "group_title",
        "group_action_type",
        "type",
        "country",
        "is_stewie",
        "is_sos",
        "is_critical",
        "is_time_sensitive",
        "schedule_type",
        "schedule_state",
        "part_count",
    ]
    optional_msg = {col: col in msg_cols for col in optional_cols}
    optional_msg["attributedBody"] = "attributedBody" in msg_cols

    select_bits = [
        "m.ROWID AS message_id",
        "m.date",
        "m.is_from_me",
        "m.text",
        "m.handle_id",
        "COALESCE(h.id, '') AS handle",
        "cmj.chat_id",
    ]
    for col, has in optional_msg.items():
        if has and col != "attributedBody":
            select_bits.append(f"m.{col}")
        elif col == "attributedBody" and has:
            select_bits.append(
                "CASE WHEN m.attributedBody IS NULL THEN 0 ELSE 1 END AS has_attributed_body"
            )

    sql = f"""
        SELECT {", ".join(select_bits)}
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        ORDER BY cmj.chat_id, m.date, m.ROWID
    """

    now = utc_now_iso()
    message_rows: list[dict[str, Any]] = []
    attachment_upserts: list[dict[str, Any]] = []
    ok = partial = failed = 0
    missing_attachment_files = 0
    decoded_attr = 0
    undecoded_attr = 0

    chat_by_id = {int(c["chat_id"]): c for c in chats}
    thread_payloads: dict[str, dict[str, dict]] = {}  # thread_key -> id -> payload
    thread_meta: dict[str, dict] = {}

    for row in conn.execute(sql):
        r = dict(row)
        chat = chat_by_id.get(int(r["chat_id"]))
        if not chat:
            continue

        thread_key = _safe_thread_key(
            int(chat["chat_id"]),
            chat["chat_identifier"],
            chat["display_name"] or chat["room_name"],
        )
        thread_dir = messages_dir / thread_key
        thread_dir.mkdir(parents=True, exist_ok=True)
        thread_meta.setdefault(
            thread_key,
            {
                "thread": thread_key,
                "chat_id": chat["chat_id"],
                "chat_identifier": chat["chat_identifier"] or None,
                "display_name": chat["display_name"] or chat["room_name"] or None,
                "participants": chat_handles.get(int(chat["chat_id"]), []),
            },
        )
        if thread_key not in thread_payloads:
            # Load existing jsonl for append-only upsert by message id
            thread_payloads[thread_key] = _load_jsonl_by_id(thread_dir / f"{thread_key}.jsonl")

        guid = r.get("guid") or f"row:{r['message_id']}"
        is_from_me = bool(r.get("is_from_me"))
        handle = r.get("handle") or None
        participants = chat_handles.get(int(r["chat_id"]), [])
        me = r.get("destination_caller_id") if optional_msg["destination_caller_id"] else None
        if not me and me_candidates:
            me = sorted(me_candidates)[0]

        if is_from_me:
            from_addr = me or "me"
            to_addrs = participants or ([handle] if handle else [])
        else:
            from_addr = handle
            to_addrs = [me] if me else ["me"]

        status = _prune(
            {
                "is_from_me": is_from_me,
                "is_sent": _bool_or_none(r, "is_sent", optional_msg["is_sent"]),
                "is_delivered": _bool_or_none(r, "is_delivered", optional_msg["is_delivered"]),
                "is_read": _bool_or_none(r, "is_read", optional_msg["is_read"]),
                "is_finished": _bool_or_none(r, "is_finished", optional_msg.get("is_finished", False)),
                "date_delivered": apple_date_to_iso(r.get("date_delivered"))
                if optional_msg["date_delivered"]
                else None,
                "date_read": apple_date_to_iso(r.get("date_read")) if optional_msg["date_read"] else None,
                "date_played": apple_date_to_iso(r.get("date_played"))
                if optional_msg.get("date_played")
                else None,
                "date_edited": apple_date_to_iso(r.get("date_edited"))
                if optional_msg.get("date_edited")
                else None,
                "date_retracted": apple_date_to_iso(r.get("date_retracted"))
                if optional_msg.get("date_retracted")
                else None,
                "error": r.get("error") if optional_msg["error"] and r.get("error") else None,
                "was_downgraded": _bool_or_none(r, "was_downgraded", optional_msg.get("was_downgraded", False)),
                "was_delivered_quietly": _bool_or_none(
                    r, "was_delivered_quietly", optional_msg.get("was_delivered_quietly", False)
                ),
                "did_notify_recipient": _bool_or_none(
                    r, "did_notify_recipient", optional_msg.get("did_notify_recipient", False)
                ),
            }
        )

        text = r.get("text")
        text_source = "text" if text else None
        has_attr = bool(r.get("has_attributed_body")) if optional_msg["attributedBody"] else False
        integrity_notes: list[str] = []

        if (not text) and has_attr:
            blob_row = conn_blobs.execute(
                "SELECT attributedBody FROM message WHERE ROWID = ?",
                (r["message_id"],),
            ).fetchone()
            blob = blob_row[0] if blob_row else None
            decoded = decode_attributed_body(blob)
            if decoded:
                text = decoded
                text_source = "attributedBody"
                decoded_attr += 1
            else:
                undecoded_attr += 1
                integrity_notes.append("attributedBody present but could not decode to text")

        # Reactions / tapbacks / replies
        assoc_type = r.get("associated_message_type") if optional_msg.get("associated_message_type") else None
        reaction = None
        if assoc_type in _REACTION_TYPES or (isinstance(assoc_type, int) and assoc_type >= 2000):
            reaction = _prune(
                {
                    "type": assoc_type,
                    "name": _REACTION_TYPES.get(assoc_type, f"type_{assoc_type}"),
                    "target_guid": r.get("associated_message_guid"),
                    "emoji": r.get("associated_message_emoji"),
                }
            )
        reply = _prune(
            {
                "reply_to_guid": r.get("reply_to_guid") if optional_msg.get("reply_to_guid") else None,
                "thread_originator_guid": r.get("thread_originator_guid")
                if optional_msg.get("thread_originator_guid")
                else None,
                "thread_originator_part": r.get("thread_originator_part")
                if optional_msg.get("thread_originator_part")
                else None,
            }
        )

        flags = _prune(
            {
                "is_audio_message": _bool_or_none(r, "is_audio_message", optional_msg.get("is_audio_message", False)),
                "is_played": _bool_or_none(r, "is_played", optional_msg.get("is_played", False)),
                "is_system_message": _bool_or_none(
                    r, "is_system_message", optional_msg.get("is_system_message", False)
                ),
                "is_emote": _bool_or_none(r, "is_emote", optional_msg.get("is_emote", False)),
                "is_spam": _bool_or_none(r, "is_spam", optional_msg.get("is_spam", False)),
                "is_empty": _bool_or_none(r, "is_empty", optional_msg.get("is_empty", False)),
                "is_stewie": _bool_or_none(r, "is_stewie", optional_msg.get("is_stewie", False)),
                "is_sos": _bool_or_none(r, "is_sos", optional_msg.get("is_sos", False)),
                "is_critical": _bool_or_none(r, "is_critical", optional_msg.get("is_critical", False)),
                "is_time_sensitive": _bool_or_none(
                    r, "is_time_sensitive", optional_msg.get("is_time_sensitive", False)
                ),
            }
        )

        msg_attachments = []
        for a in attachments_by_msg.get(int(r["message_id"]), []):
            att_id = a.get("guid") or f"att-row-{a['attachment_id']}"
            rel = _normalize_attachment_rel(a.get("filename"))
            local_name = _attachment_filename(
                att_id, a.get("transfer_name"), a.get("filename"), a.get("mime_type")
            )
            dest = thread_dir / local_name
            verified = False
            sha = None
            size_on_disk = None
            path = None
            if rel:
                path = (
                    extracted_index.get(rel)
                    or extracted_index.get(rel.replace("Library/SMS/Attachments/", ""))
                    or extracted_index.get(rel.replace("Library/SMS/StickerCache/", ""))
                    or extracted_index.get(Path(rel).name)
                )
            # Prefer extension from the staged source file when DB name is weak
            if path and path.is_file() and not Path(local_name).suffix and path.suffix:
                local_name = f"{Path(local_name).stem}{path.suffix.lower()}"
                dest = thread_dir / local_name
            if path and path.is_file():
                placed, place_note = _place_file(path, dest)
                if place_note:
                    integrity_notes.append(place_note)
                if placed and dest.is_file():
                    size_on_disk = dest.stat().st_size
                    expected = a.get("total_bytes")
                    if expected is not None and int(expected) > 0 and int(expected) != size_on_disk:
                        integrity_notes.append(
                            f"attachment {att_id} size mismatch db={expected} disk={size_on_disk}"
                        )
                    else:
                        sha = sha256_file(dest)
                        verified = True
                else:
                    missing_attachment_files += 1
                    integrity_notes.append(f"attachment not placed: {rel or att_id}")
            else:
                # Zero-byte plugin stubs / null paths are not "missing media" in the useful sense
                fn = a.get("filename") or ""
                if not fn or "pluginPayloadAttachment" in fn or (a.get("total_bytes") or 0) == 0:
                    integrity_notes.append(f"attachment stub/unmaterialized: {rel or att_id}")
                else:
                    missing_attachment_files += 1
                    integrity_notes.append(f"attachment missing from backup extract: {rel or att_id}")

            kind = "sticker" if a.get("is_sticker") or (rel and "StickerCache" in rel) else "file"
            att_payload = _prune(
                {
                    "id": att_id.lower() if a.get("guid") else att_id,
                    "filename": local_name if verified or dest.exists() else None,
                    "original_filename": a.get("transfer_name")
                    or Path(a.get("filename") or "").name
                    or None,
                    "mime_type": a.get("mime_type"),
                    "uti": a.get("uti"),
                    "kind": kind,
                    "byte_size_db": a.get("total_bytes"),
                    "byte_size_disk": size_on_disk,
                    "sha256": sha,
                    "verified": verified,
                    "is_outgoing": a.get("is_outgoing"),
                    "transfer_state": a.get("transfer_state"),
                    "created_date": apple_date_to_iso(a.get("created_date")),
                    "original_guid": a.get("original_guid"),
                }
            )
            msg_attachments.append(att_payload)
            attachment_upserts.append(
                {
                    "id": att_payload["id"],
                    "source": "imessage",
                    "message_id": guid,
                    "filename": local_name,
                    "mime_type": a.get("mime_type"),
                    "byte_size": size_on_disk if size_on_disk is not None else a.get("total_bytes"),
                    "sha256": sha,
                    "blob_path": f"messages/{thread_key}/{local_name}"
                    if (verified or dest.exists())
                    else None,
                    "verified": 1 if verified else 0,
                    "payload_json": json.dumps(att_payload, ensure_ascii=False),
                    "updated_at": now,
                }
            )

        item_status = "ok"
        if any(
            any(x in n for x in ("missing", "mismatch", "not placed", "could not decode", "different content"))
            for n in integrity_notes
        ):
            item_status = "partial"
        if (
            optional_msg.get("cache_has_attachments")
            and r.get("cache_has_attachments")
            and not msg_attachments
        ):
            integrity_notes.append("cache_has_attachments set but no attachment rows")
            item_status = "partial"

        service = r.get("service") if optional_msg["service"] else None
        bubble = None
        if isinstance(service, str):
            sl = service.lower()
            if sl in ("imessage", "imessagelite"):
                bubble = "blue"
            elif sl in ("sms", "mms", "rcs", "satellitesms"):
                bubble = "green"

        payload = _prune(
            {
                "id": guid,
                "source": "imessage",
                "backup_id": backup_id,
                "thread": thread_key,
                "chat_id": chat["chat_id"],
                "chat_identifier": chat["chat_identifier"] or None,
                "chat_display_name": chat["display_name"] or chat["room_name"] or None,
                "date": apple_date_to_iso(r.get("date")),
                "from": from_addr,
                "to": to_addrs,
                "text": text,
                "text_source": text_source,
                "subject": r.get("subject") if optional_msg["subject"] else None,
                "service": service,
                "bubble": bubble,
                "account": r.get("account") if optional_msg.get("account") else None,
                "account_guid": r.get("account_guid") if optional_msg.get("account_guid") else None,
                "country": r.get("country") if optional_msg.get("country") else None,
                "status": status,
                "flags": flags or None,
                "reaction": reaction,
                "reply": reply or None,
                "effect": r.get("expressive_send_style_id")
                if optional_msg.get("expressive_send_style_id")
                else None,
                "balloon_bundle_id": r.get("balloon_bundle_id")
                if optional_msg.get("balloon_bundle_id")
                else None,
                "item_type": r.get("item_type") if optional_msg.get("item_type") else None,
                "group_title": r.get("group_title") if optional_msg.get("group_title") else None,
                "group_action_type": r.get("group_action_type")
                if optional_msg.get("group_action_type")
                else None,
                "schedule_type": r.get("schedule_type") if optional_msg.get("schedule_type") else None,
                "schedule_state": r.get("schedule_state") if optional_msg.get("schedule_state") else None,
                "part_count": r.get("part_count") if optional_msg.get("part_count") else None,
                "attachments": msg_attachments,
                "integrity": {
                    "status": item_status,
                    "notes": integrity_notes,
                    "has_attributed_body": has_attr,
                },
                "extracted_at": now,
            }
        )

        thread_payloads[thread_key][guid] = payload
        message_rows.append(
            {
                "id": guid,
                "source": "imessage",
                "chat_id": str(chat["chat_id"]),
                "chat_identifier": chat["chat_identifier"],
                "date": payload["date"],
                "from_addr": from_addr,
                "to_addrs_json": json.dumps(to_addrs, ensure_ascii=False),
                "text": text,
                "service": payload.get("service"),
                "status_json": json.dumps(status, ensure_ascii=False),
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )
        if item_status == "ok":
            ok += 1
        else:
            partial += 1

    # Group photos + durable chat rows
    chat_upserts: list[dict[str, Any]] = []
    group_photos_ok = 0
    for thread_key, meta in thread_meta.items():
        chat = chat_by_id.get(int(meta["chat_id"]))
        if not chat:
            continue
        ident = chat.get("chat_identifier") or ""
        phone_name = (chat.get("display_name") or chat.get("room_name") or "").strip() or None
        # Don't treat raw chat id as a "title"
        if phone_name and phone_name == ident:
            phone_name = None
        props = parse_chat_properties(chat.get("properties"))
        photo_guid = props.get("groupPhotoGuid")
        photo_rel = None
        thread_dir = messages_dir / thread_key
        thread_dir.mkdir(parents=True, exist_ok=True)

        src: Path | None = None
        if photo_guid:
            a = att_by_guid.get(str(photo_guid).lower())
            if a:
                rel = _normalize_attachment_rel(a.get("filename"))
                if rel:
                    src = (
                        extracted_index.get(rel)
                        or extracted_index.get(rel.replace("Library/SMS/Attachments/", ""))
                        or extracted_index.get(Path(rel).name)
                    )
            if src is None:
                g = str(photo_guid).lower()
                for key, path in extracted_index.items():
                    if g in key.lower():
                        src = path
                        break
        if src is None and ident.startswith("chat"):
            # Fallback: GroupPhotoImage under this thread's attachment folders
            for path in extracted_index.values():
                if path.name.lower().startswith("groupphotoimage") or "groupphotoimage" in path.name.lower():
                    # Prefer if parent path contains chat guid fragment
                    chat_guid = (chat.get("chat_guid") or "").lower()
                    if chat_guid and chat_guid.replace(";", "") in str(path).lower().replace(";", ""):
                        src = path
                        break

        if src and src.is_file():
            ext = src.suffix.lower() or ".jpg"
            if ext in {".", ""}:
                ext = ".jpg"
            dest = thread_dir / f"_group_photo{ext}"
            placed, _note = _place_file(src, dest)
            if placed and dest.is_file():
                photo_rel = f"messages/{thread_key}/{dest.name}"
                group_photos_ok += 1
                meta["group_photo_path"] = photo_rel
                meta["group_photo_guid"] = photo_guid

        is_group = 1 if ident.startswith("chat") or chat.get("style") in (43, 45) else 0
        participants = chat_handles.get(int(chat["chat_id"]), [])
        payload = {
            "id": str(chat["chat_id"]),
            "chat_id": str(chat["chat_id"]),
            "chat_identifier": ident or None,
            "chat_guid": chat.get("chat_guid"),
            "thread_key": thread_key,
            "phone_display_name": phone_name,
            "is_group": bool(is_group),
            "group_photo_path": photo_rel,
            "group_photo_guid": photo_guid,
            "participants": participants,
            "style": chat.get("style"),
            "extracted_at": now,
        }
        meta["phone_display_name"] = phone_name
        meta["is_group"] = bool(is_group)
        chat_upserts.append(
            {
                "id": str(chat["chat_id"]),
                "chat_id": str(chat["chat_id"]),
                "chat_identifier": ident or None,
                "thread_key": thread_key,
                "phone_display_name": phone_name,
                "is_group": is_group,
                "group_photo_path": photo_rel,
                "group_photo_guid": photo_guid,
                "participants_json": json.dumps(participants, ensure_ascii=False),
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )

    conn.close()
    conn_blobs.close()

    # Write per-thread jsonl (sorted by date) — full upsert rewrite, append-only by id
    for thread_key, by_id in thread_payloads.items():
        thread_dir = messages_dir / thread_key
        items = sorted(by_id.values(), key=lambda m: (m.get("date") or "", m.get("id") or ""))
        _write_jsonl(thread_dir / f"{thread_key}.jsonl", items)
        meta = thread_meta[thread_key]
        meta["message_count"] = len(items)
        meta["updated_at"] = now
        (thread_dir / f"{thread_key}.meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    archive.upsert_many(
        "messages",
        message_rows,
        [
            "id",
            "source",
            "chat_id",
            "chat_identifier",
            "date",
            "from_addr",
            "to_addrs_json",
            "text",
            "service",
            "status_json",
            "payload_json",
            "updated_at",
        ],
    )
    archive.upsert_many(
        "attachments",
        attachment_upserts,
        [
            "id",
            "source",
            "message_id",
            "filename",
            "mime_type",
            "byte_size",
            "sha256",
            "blob_path",
            "verified",
            "payload_json",
            "updated_at",
        ],
    )
    archive.upsert_many(
        "chats",
        chat_upserts,
        [
            "id",
            "chat_id",
            "chat_identifier",
            "thread_key",
            "phone_display_name",
            "is_group",
            "group_photo_path",
            "group_photo_guid",
            "participants_json",
            "payload_json",
            "updated_at",
        ],
    )

    report.items_ok = ok
    report.items_partial = partial
    report.items_failed = failed
    report.artifacts = {"messages_dir": str(messages_dir)}
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        index = []
        for thread_key, meta in sorted(thread_meta.items()):
            index.append(
                {
                    **meta,
                    "path": f"messages/{thread_key}/",
                    "jsonl": f"messages/{thread_key}/{thread_key}.jsonl",
                }
            )
        chats_json = export_dir / "chats.json"
        chats_json.write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        summary = {
            "messages": ok + partial + failed,
            "messages_ok": ok,
            "messages_partial": partial,
            "threads": len(thread_meta),
            "attachment_rows": len(attachment_upserts),
            "attachment_files_decrypted": n_att_files,
            "attachment_files_missing": missing_attachment_files,
            "attributed_body_decoded": decoded_attr,
            "attributed_body_undecoded": undecoded_attr,
            "layout": "out/messages/{thread}/{thread}.jsonl + {guid}.ext beside it",
            "note": "Append-only upsert by message guid / attachment guid.",
        }
        summary_json = export_dir / "messages_summary.json"
        summary_json.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report.artifacts["chats_json"] = str(chats_json)
        report.artifacts["summary"] = str(summary_json)
    report.note(f"Decoded attributedBody for {decoded_attr} messages")
    if undecoded_attr:
        report.note(f"Could not decode attributedBody for {undecoded_attr} messages")
    if group_photos_ok:
        report.note(f"Placed {group_photos_ok} group chat photos")
    if missing_attachment_files:
        report.note(f"{missing_attachment_files} attachment refs not verified on disk")
        report.status = "partial"
    elif partial:
        report.status = "partial"
    elif ok:
        report.status = "ok"
    else:
        report.status = "failed"
    return report
