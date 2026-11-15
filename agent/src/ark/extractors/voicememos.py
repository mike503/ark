from __future__ import annotations

import json
import plistlib
import re
import sqlite3
from pathlib import Path

from iphone_backup_decrypt import EncryptedBackup

from ..archive import Archive, sha256_file
from ..backup_io import extract_like
from ..dates import apple_date_to_iso, utc_now_iso
from ..report import CategoryReport

VOICE_DOMAIN = "AppDomainGroup-group.com.apple.VoiceMemos.shared"


def _title_from_filename(name: str) -> str:
    stem = Path(name).stem
    # "20250710 194026" or with suffix hash
    stem = re.sub(r"-[0-9A-Fa-f]{8}$", "", stem)
    return stem


def extract_voicememos(
    backup: EncryptedBackup,
    *,
    archive: Archive,
    work: Path,
    blobs_dir: Path,
    export_dir: Path | None = None,
) -> CategoryReport:
    report = CategoryReport(category="voicememos", status="failed")
    audio_root = blobs_dir / "voicememos"
    try:
        n = extract_like(
            backup,
            relative_paths_like="Recordings/%",
            domain_like=VOICE_DOMAIN,
            output_folder=audio_root,
            preserve_folders=True,
        )
        report.note(f"Extracted {n} files from {VOICE_DOMAIN}/Recordings")
    except Exception as exc:  # noqa: BLE001
        report.note(f"extract failed: {exc}")
        return report

    # Optional CloudRecordings.db for titles/dates
    meta_by_file: dict[str, dict] = {}
    db_candidates = list(audio_root.rglob("CloudRecordings.db"))
    for db_path in db_candidates:
        try:
            conn = sqlite3.connect(str(db_path))
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            report.note(f"{db_path.name} tables: {', '.join(tables)}")
            # Try common schemas
            for table in tables:
                cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
                # ZCLOUDRECORDING / ZRECORDING style
                if not any(c.lower() in {"z_pk", "rowid"} or "date" in c.lower() or "title" in c.lower() or "path" in c.lower() for c in cols):
                    continue
                try:
                    rows = list(conn.execute(f'SELECT * FROM "{table}"'))
                except sqlite3.Error:
                    continue
                col_list = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
                for row in rows:
                    d = {col_list[i]: row[i] for i in range(len(col_list))}
                    # Find filename-ish field
                    path_val = None
                    for k, v in d.items():
                        if isinstance(v, str) and (v.endswith(".m4a") or "/" in v or "Recordings" in v):
                            path_val = v
                            break
                    title = None
                    for k in d:
                        if "title" in k.lower() or k in {"ZCUSTOMLABEL", "ZLABEL", "ZNAME"}:
                            if d[k]:
                                title = d[k]
                                break
                    date = None
                    for k in d:
                        if "date" in k.lower() and d[k] is not None:
                            date = apple_date_to_iso(d[k])
                            if date:
                                break
                    if path_val:
                        key = Path(path_val).name
                        meta_by_file[key] = {"title": title, "date": date, "raw": {k: d[k] for k, v in d.items() if not isinstance(v, (bytes, memoryview))}}
            conn.close()
        except sqlite3.Error as exc:
            report.note(f"Could not parse {db_path}: {exc}")

    # Also read composition manifests if present
    for manifest in audio_root.rglob("manifest.plist"):
        try:
            with manifest.open("rb") as f:
                data = plistlib.load(f)
            # best effort
            parent = manifest.parent.name.replace(".composition", "")
            meta_by_file.setdefault(parent + ".m4a", {})
            if isinstance(data, dict):
                title = data.get("title") or data.get("Title")
                if title:
                    meta_by_file[parent + ".m4a"]["title"] = title
        except Exception:
            pass

    now = utc_now_iso()
    upserts = []
    export_items = []
    ok = partial = failed = 0

    m4as = sorted({p for p in audio_root.rglob("*.m4a") if p.is_file()})
    if not m4as:
        report.note("No .m4a voice memos found after extract")
        report.status = "failed"
        return report

    for audio in m4as:
        name = audio.name
        meta = meta_by_file.get(name, {})
        title = meta.get("title") or _title_from_filename(name)
        # Prefer date embedded in filename YYYYMMDD HHMMSS
        date = meta.get("date")
        m = re.match(r"^(\d{8})[ _](\d{6})", Path(name).stem)
        if m and not date:
            y, mo, d = m.group(1)[0:4], m.group(1)[4:6], m.group(1)[6:8]
            hh, mm, ss = m.group(2)[0:2], m.group(2)[2:4], m.group(2)[4:6]
            date = f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"

        rel = str(audio.relative_to(blobs_dir.parent)).replace("\\", "/")
        size = audio.stat().st_size
        verified = size > 0
        sha = sha256_file(audio) if verified else None
        notes = []
        if not verified:
            notes.append("empty audio file")
            failed += 1
            item_status = "failed"
        else:
            ok += 1
            item_status = "ok"

        vid = f"voicememo:{name}"
        payload = {
            "id": vid,
            "title": title,
            "date": date,
            "filename": name,
            "audio": {
                "path": rel,
                "sha256": sha,
                "byte_size": size,
                "format": "m4a",
                "verified": verified,
            },
            "integrity": {"status": item_status, "notes": notes},
            "extracted_at": now,
        }
        export_items.append(payload)
        upserts.append(
            {
                "id": vid,
                "title": title,
                "date": date,
                "audio_path": rel,
                "audio_sha256": sha,
                "verified": 1 if verified else 0,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )

    archive.upsert_many(
        "voicememos",
        upserts,
        [
            "id",
            "title",
            "date",
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
        out = export_dir / "voicememos.json"
        out.write_text(
            json.dumps(export_items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report.artifacts["voicememos_json"] = str(out)
    report.status = "ok" if ok and not failed else ("partial" if ok else "failed")
    return report
