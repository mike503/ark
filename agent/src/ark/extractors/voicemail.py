from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from iphone_backup_decrypt import EncryptedBackup, RelativePathsLike

from ..archive import Archive, sha256_file
from ..backup_io import extract_file, extract_like
from ..dates import unix_seconds_to_iso, utc_now_iso
from ..report import CategoryReport
from ..transcripts import load_voicemail_transcript


def extract_voicemail(
    backup: EncryptedBackup,
    *,
    archive: Archive,
    work: Path,
    blobs_dir: Path,
    export_dir: Path | None = None,
) -> CategoryReport:
    report = CategoryReport(category="voicemail", status="failed")
    raw = work / "voicemail"
    raw.mkdir(parents=True, exist_ok=True)
    db_path = raw / "voicemail.db"
    try:
        extract_file(backup, "Library/Voicemail/voicemail.db", db_path)
    except Exception as exc:  # noqa: BLE001
        report.note(f"voicemail.db extract failed: {exc}")
        return report

    audio_root = blobs_dir / "voicemail"
    try:
        n = extract_like(
            backup,
            relative_paths_like="Library/Voicemail/%",
            domain_like="HomeDomain",
            output_folder=audio_root,
            preserve_folders=True,
        )
        report.note(f"Extracted {n} files under Library/Voicemail")
    except Exception as exc:  # noqa: BLE001
        report.note(f"audio extract error: {exc}")
        n = 0

    # Index audio by ROWID filename stem
    by_id: dict[str, Path] = {}
    transcripts: dict[str, Path] = {}
    for p in audio_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() == ".amr":
            by_id[p.stem] = p
        elif p.suffix.lower() == ".transcript":
            transcripts[p.stem] = p

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT * FROM voicemail ORDER BY date, ROWID"))
    now = utc_now_iso()
    upserts = []
    ok = partial = failed = 0
    export_items = []

    for r in rows:
        rid = str(r["ROWID"])
        # uuid column is often an account/label id shared across rows — not unique per message
        vid = f"voicemail:{rid}"
        account_uuid = r["uuid"]
        audio = by_id.get(rid)
        notes = []
        verified = False
        audio_rel = None
        sha = None
        size = None
        if audio and audio.is_file():
            # Store path relative to archive root (parent of blobs/)
            archive_root = blobs_dir.parent
            audio_rel = str(audio.relative_to(archive_root)).replace("\\", "/")
            size = audio.stat().st_size
            sha = sha256_file(audio)
            verified = size > 0
        else:
            notes.append(f"missing audio file {rid}.amr")
            failed += 1

        transcript_text = None
        transcript_confidence = None
        tpath = transcripts.get(rid)
        if tpath and tpath.is_file():
            decoded = load_voicemail_transcript(tpath)
            if decoded and decoded.get("text"):
                transcript_text = decoded["text"]
                transcript_confidence = decoded.get("confidence")
            else:
                notes.append("transcript present but could not decode")

        item_status = "ok" if verified and not notes else ("partial" if verified else "failed")
        if item_status == "ok":
            ok += 1
        elif item_status == "partial":
            partial += 1

        def _clean_ts(v):
            iso = unix_seconds_to_iso(v) if v else None
            # Sentinel / garbage dates (e.g. 1984) — don't present as real
            if iso and iso.startswith("198"):
                return None
            return iso

        payload = {
            "id": vid,
            "row_id": int(r["ROWID"]),
            "account_uuid": account_uuid,
            "date": unix_seconds_to_iso(r["date"]),
            "from": r["sender"],
            "callback_number": r["callback_num"],
            "to": r["receiver"],
            "duration_sec": r["duration"],
            "expiration": _clean_ts(r["expiration"]),
            "trashed_date": _clean_ts(r["trashed_date"]),
            "token": r["token"],
            "flags": r["flags"],
            "label": r["label"],
            "audio": {
                "path": audio_rel,
                "sha256": sha,
                "byte_size": size,
                "format": "amr",
                "verified": verified,
            },
            "transcript": transcript_text,
            "transcript_confidence": transcript_confidence,
            "integrity": {"status": item_status, "notes": notes},
            "extracted_at": now,
        }
        export_items.append(payload)
        upserts.append(
            {
                "id": vid,
                "date": payload["date"],
                "from_addr": r["sender"],
                "to_addr": r["receiver"],
                "duration_sec": r["duration"],
                "audio_path": audio_rel,
                "audio_sha256": sha,
                "verified": 1 if verified else 0,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )

    conn.close()
    archive.upsert_many(
        "voicemails",
        upserts,
        [
            "id",
            "date",
            "from_addr",
            "to_addr",
            "duration_sec",
            "audio_path",
            "audio_sha256",
            "verified",
            "payload_json",
            "updated_at",
        ],
    )
    report.items_ok = ok
    report.items_partial = partial
    report.items_failed = failed
    report.artifacts = {"audio_dir": str(audio_root)}
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        out = export_dir / "voicemail.json"
        out.write_text(
            json.dumps(export_items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report.artifacts["voicemail_json"] = str(out)
    if ok and not failed and not partial:
        report.status = "ok"
    elif ok or partial:
        report.status = "partial"
    else:
        report.status = "failed"
    # recount: failed above counted missing audio; adjust if row had no audio
    report.note("Each item ties DB row ROWID -> {ROWID}.amr; verified only if audio file present and non-empty.")
    return report
