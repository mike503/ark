from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from iphone_backup_decrypt import EncryptedBackup

from ..archive import Archive
from ..backup_io import extract_file, extract_like, manifest_rows
from ..dates import apple_date_to_iso, utc_now_iso
from ..report import CategoryReport


def extract_whatsapp(
    backup: EncryptedBackup,
    *,
    archive: Archive,
    work: Path,
    blobs_dir: Path,
    backup_id: str,
    export_dir: Path | None = None,
) -> CategoryReport:
    report = CategoryReport(category="whatsapp", status="failed")
    raw = work / "whatsapp"
    raw.mkdir(parents=True, exist_ok=True)

    matches = manifest_rows(
        backup,
        "relativePath LIKE ?",
        ("%ChatStorage.sqlite%",),
    )
    # Prefer plaintext ChatStorage; .enc is WhatsApp's own crypto (not the iTunes backup password)
    plain = [m for m in matches if not m[1].lower().endswith(".enc")]
    enc_only = [m for m in matches if m[1].lower().endswith(".enc")]
    if not plain and enc_only:
        report.status = "skipped"
        report.note(
            "No plaintext ChatStorage.sqlite in this backup — only "
            f"ChatStorage.sqlite.enc ({enc_only[0][1]}). That usually means "
            "WhatsApp → Chats → Chat Backup → End-to-end encrypted backup is ON, "
            "which excludes chat history from Finder/iTunes backups. "
            "TouchCopy only needs the iTunes password when plaintext ChatStorage "
            "is present (E2E off). The .enc file needs WhatsApp's own 64-digit "
            "key/password; open-source tools cannot unwrap it today. "
            "Fix: turn E2E backup off in WhatsApp, make a fresh encrypted "
            "iTunes/Finder backup, then re-run extract."
        )
        return report
    matches = [m for m in plain if "whatsapp" in m[0].lower() or "whatsapp" in m[1].lower()] or plain
    if not matches:
        report.status = "skipped"
        report.note("ChatStorage.sqlite not found in backup")
        return report

    domain, rel = matches[0]
    db = raw / "ChatStorage.sqlite"
    try:
        extract_file(backup, rel, db, domain_like=domain)
    except Exception as exc:  # noqa: BLE001
        report.note(f"ChatStorage extract failed: {exc}")
        return report

    # Media: this backup appears to lack Message/Media — verify and report honestly
    media_matches = manifest_rows(
        backup,
        "domain LIKE ? AND (relativePath LIKE ? OR relativePath LIKE ? OR relativePath LIKE ?)",
        ("%whatsapp%", "Message/Media/%", "Media/%", "%.mp4"),
    )
    media_root = blobs_dir / "whatsapp" / "media"
    media_count = 0
    if media_matches:
        try:
            media_count = extract_like(
                backup,
                relative_paths_like="Message/%",
                domain_like="%whatsapp%",
                output_folder=media_root,
            )
        except Exception as exc:  # noqa: BLE001
            report.note(f"media extract error: {exc}")
    else:
        report.note(
            "No WhatsApp Message/Media (or similar) files in this backup — "
            "ChatStorage present but media was not included by iOS/WhatsApp backup rules."
        )
        # Still pull stickers if present
        try:
            media_count = extract_like(
                backup,
                relative_paths_like="stickers/%",
                domain_like="%whatsapp%",
                output_folder=blobs_dir / "whatsapp" / "stickers",
            )
            if media_count:
                report.note(f"Extracted {media_count} sticker files (not message media)")
        except Exception:
            pass

    conn = sqlite3.connect(str(db))
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    msg_table = "ZWAMESSAGE" if "ZWAMESSAGE" in tables else None
    if not msg_table:
        report.note(f"No ZWAMESSAGE table; tables={tables}")
        conn.close()
        report.status = "partial" if db.is_file() else "failed"
        return report

    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{msg_table}")')]
    col_index = {c: i for i, c in enumerate(cols)}

    def col(row, *names, default=None):
        for name in names:
            if name in col_index:
                return row[col_index[name]]
        return default

    now = utc_now_iso()
    upserts = []
    export_items = []
    ok = 0
    for row in conn.execute(f'SELECT * FROM "{msg_table}"'):
        text = col(row, "ZTEXT") or ""
        stanza = col(row, "ZSTANZAID", "ZUNIQUEKEY")
        date_raw = col(row, "ZMESSAGEDATE", "ZSORT")
        if not text and not stanza:
            continue
        mid = str(stanza or f"wa-row:{col(row, 'Z_PK', default=ok)}")
        notes = []
        if media_count == 0 and col(row, "ZMEDIATYPE", "ZMESSAGETYPE"):
            # media type present but no media files in backup
            notes.append("message may reference media but media files absent from backup")
        payload = {
            "id": mid,
            "source": "whatsapp",
            "backup_id": backup_id,
            "date": apple_date_to_iso(date_raw),
            "from": col(row, "ZFROMJID", "ZFROMJIDSTRING"),
            "to": col(row, "ZTOJID", "ZTOJIDSTRING"),
            "is_from_me": bool(col(row, "ZISFROMME") or 0),
            "text": text,
            "attachments": [],  # cannot verify — not in backup
            "integrity": {
                "status": "partial" if notes else "ok",
                "notes": notes,
                "media_in_backup": media_count > 0,
            },
            "extracted_at": now,
        }
        export_items.append(payload)
        upserts.append(
            {
                "id": mid,
                "date": payload["date"],
                "from_jid": payload["from"],
                "to_jid": payload["to"],
                "text": text,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )
        ok += 1

    conn.close()
    archive.upsert_many(
        "whatsapp_messages",
        upserts,
        ["id", "date", "from_jid", "to_jid", "text", "payload_json", "updated_at"],
    )
    report.items_ok = ok
    report.artifacts = {}
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        out = export_dir / "whatsapp.json"
        if len(export_items) > 20000:
            jsonl = export_dir / "whatsapp.jsonl"
            with jsonl.open("w", encoding="utf-8") as f:
                for item in export_items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            report.artifacts["whatsapp_jsonl"] = str(jsonl)
        else:
            out.write_text(
                json.dumps(export_items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            report.artifacts["whatsapp_json"] = str(out)

    if ok and media_count == 0:
        report.status = "partial"
        report.note(f"Exported {ok} messages; media not present in backup (cannot claim full fidelity)")
    elif ok:
        report.status = "ok"
    else:
        report.status = "failed"
    return report
