from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from iphone_backup_decrypt import EncryptedBackup, RelativePath

from ..archive import Archive
from ..backup_io import extract_file
from ..dates import utc_now_iso
from ..report import CategoryReport

# ABMultiValue property codes commonly used on iOS
_PROP = {
    3: "phone",
    4: "email",
    22: "address",
    46: "social_profile",
    5: "url",
}


def _stable_contact_id(pid: int, extra_fields: dict, first: str, last: str, phones: list, emails: list) -> str:
    """Prefer Apple guid / ExternalUUID; fall back to row id (weak but historical)."""
    for key in ("guid", "ExternalUUID", "GUID"):
        val = extra_fields.get(key)
        if isinstance(val, str) and val.strip():
            return f"contact:{val.strip().lower()}"
    return f"contact:row:{pid}"


def extract_contacts(
    backup: EncryptedBackup,
    *,
    archive: Archive,
    work: Path,
    export_dir: Path | None = None,
) -> CategoryReport:
    report = CategoryReport(category="contacts", status="failed")
    raw = work / "contacts"
    raw.mkdir(parents=True, exist_ok=True)
    db = raw / "AddressBook.sqlitedb"
    try:
        extract_file(backup, RelativePath.ADDRESS_BOOK, db)
    except Exception as exc:  # noqa: BLE001
        report.note(f"AddressBook extract failed: {exc}")
        return report

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    people = list(conn.execute("SELECT * FROM ABPerson ORDER BY ROWID"))
    person_cols = [r[1] for r in conn.execute("PRAGMA table_info(ABPerson)")]

    multi: dict[int, list[dict]] = {}
    try:
        for row in conn.execute(
            """
            SELECT mv.record_id, mv.property, mv.label AS label_id, mv.value,
                   COALESCE(l.value, '') AS label
            FROM ABMultiValue mv
            LEFT JOIN ABMultiValueLabel l ON l.ROWID = mv.label
            """
        ):
            multi.setdefault(int(row["record_id"]), []).append(dict(row))
    except sqlite3.Error as exc:
        report.note(f"ABMultiValue query failed: {exc}")

    now = utc_now_iso()
    upserts = []
    seen_ids: set[str] = set()

    # Preserve first_seen_at for existing rows
    existing_first: dict[str, str] = {}
    for cid, first_seen in archive.conn.execute(
        "SELECT id, first_seen_at FROM contacts"
    ):
        if first_seen:
            existing_first[cid] = first_seen

    for p in people:
        pid = int(p["ROWID"])
        first = (p["First"] if "First" in person_cols else None) or ""
        last = (p["Last"] if "Last" in person_cols else None) or ""
        middle = (p["Middle"] if "Middle" in person_cols else None) or ""
        org = (p["Organization"] if "Organization" in person_cols else None) or ""
        nick = (p["Nickname"] if "Nickname" in person_cols else None) or ""
        note = (p["Note"] if "Note" in person_cols else None) or ""
        display = (
            " ".join(x for x in [first, middle, last] if x).strip()
            or org
            or nick
            or f"contact-{pid}"
        )

        phones = []
        emails = []
        urls = []
        extended = []
        for mv in multi.get(pid, []):
            prop = mv["property"]
            entry = {
                "label": (mv["label"] or "").strip("_$!<>") or None,
                "value": mv["value"],
                "property": prop,
            }
            kind = _PROP.get(prop)
            if kind == "phone":
                phones.append(entry)
            elif kind == "email":
                emails.append(entry)
            elif kind == "url":
                urls.append(entry)
            else:
                extended.append(entry)

        standard = {
            "First",
            "Last",
            "Middle",
            "Organization",
            "Nickname",
            "Note",
            "ROWID",
        }
        extra_fields = {}
        for col in person_cols:
            if col in standard:
                continue
            val = p[col]
            if val is None or val == "" or val == 0:
                continue
            if isinstance(val, (bytes, memoryview)):
                continue
            extra_fields[col] = val

        cid = _stable_contact_id(pid, extra_fields, first, last, phones, emails)
        seen_ids.add(cid)
        first_seen = existing_first.get(cid, now)

        payload = {
            "id": cid,
            "apple_row_id": pid,
            "display_name": display,
            "name": {
                "first": first or None,
                "middle": middle or None,
                "last": last or None,
                "nickname": nick or None,
            },
            "organization": org or None,
            "note": note or None,
            "phones": phones,
            "emails": emails,
            "urls": urls,
            "extended_multivalues": extended,
            "extended_fields": extra_fields,
            "lifecycle": {
                "first_seen_at": first_seen,
                "last_seen_at": now,
                "on_device": True,
                "removed_from_device_at": None,
            },
            "integrity": {"status": "ok", "notes": []},
            "extracted_at": now,
        }
        upserts.append(
            {
                "id": cid,
                "display_name": display,
                "apple_row_id": pid,
                "first_seen_at": first_seen,
                "last_seen_at": now,
                "on_device": 1,
                "removed_from_device_at": None,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )

    conn.close()
    archive.upsert_many(
        "contacts",
        upserts,
        [
            "id",
            "display_name",
            "apple_row_id",
            "first_seen_at",
            "last_seen_at",
            "on_device",
            "removed_from_device_at",
            "payload_json",
            "updated_at",
        ],
    )

    # Append-only: contacts missing from this backup stay in the DB forever
    retained = 0
    if seen_ids:
        placeholders = ",".join("?" for _ in seen_ids)
        gone = list(
            archive.conn.execute(
                f"SELECT id, payload_json FROM contacts WHERE on_device = 1 "
                f"AND id NOT IN ({placeholders})",
                tuple(seen_ids),
            )
        )
        for cid, payload_json in gone:
            try:
                payload = json.loads(payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            life = payload.get("lifecycle") or {}
            life.update(
                {
                    "on_device": False,
                    "removed_from_device_at": life.get("removed_from_device_at") or now,
                    "last_seen_at": life.get("last_seen_at"),
                }
            )
            payload["lifecycle"] = life
            archive.conn.execute(
                """
                UPDATE contacts
                SET on_device = 0,
                    removed_from_device_at = COALESCE(removed_from_device_at, ?),
                    payload_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, json.dumps(payload, ensure_ascii=False), now, cid),
            )
            retained += 1
        archive.conn.commit()

    report.items_ok = len(upserts)
    report.artifacts = {}
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        export_items = [json.loads(u["payload_json"]) for u in upserts]
        for (payload_json,) in archive.conn.execute(
            "SELECT payload_json FROM contacts WHERE on_device = 0"
        ):
            try:
                export_items.append(json.loads(payload_json))
            except json.JSONDecodeError:
                pass
        out = export_dir / "contacts.json"
        out.write_text(
            json.dumps(export_items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report.artifacts["contacts_json"] = str(out)

    report.status = "ok" if upserts else "failed"
    report.note(
        f"Upserted {len(upserts)} contacts from AddressBook; "
        f"marked {retained} previously-seen contacts as no longer on device "
        "(rows retained — append-only)."
    )
    return report
