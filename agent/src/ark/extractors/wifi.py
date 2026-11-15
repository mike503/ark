from __future__ import annotations

import json
import plistlib
from pathlib import Path
from typing import Any

from iphone_backup_decrypt import EncryptedBackup

from ..archive import Archive
from ..backup_io import extract_file
from ..dates import utc_now_iso
from ..report import CategoryReport

# Modern iOS stores known networks here (SystemPreferencesDomain)
_CANDIDATES = [
    ("SystemPreferencesDomain", "com.apple.wifi.known-networks.plist"),
    ("SystemPreferencesDomain", "SystemConfiguration/com.apple.wifi-networks.plist"),
    ("SystemPreferencesDomain", "SystemConfiguration/com.apple.wifi-private-mac-networks.plist"),
    ("SystemPreferencesDomain", "SystemConfiguration/com.apple.wifi.plist"),
    ("RootDomain", "Library/Preferences/wifid.plist"),
]


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _parse_networks(data: Any, source: str) -> list[dict[str, Any]]:
    networks: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return networks

    # known-networks.plist is often a dict keyed by SSID/network key
    if all(isinstance(v, dict) for v in data.values()) and any(
        isinstance(v, dict) and ("SSID" in v or "SSID_STR" in v or "SupportedSecurityTypes" in v or "BSSID" in str(v))
        for v in list(data.values())[:5]
    ):
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            networks.append(_network_from_dict(item, source, fallback_ssid=str(key)))
        if networks:
            return networks

    for list_key in (
        "List of known networks",
        "KnownNetworks",
        "ListOfKnownNetworks",
        "Networks",
        "networkList",
    ):
        for item in _as_list(data.get(list_key)):
            if isinstance(item, dict):
                networks.append(_network_from_dict(item, source))
    return networks


def _network_from_dict(item: dict, source: str, fallback_ssid: str | None = None) -> dict[str, Any]:
    ssid = item.get("SSID_STR") or item.get("SSID") or fallback_ssid
    if isinstance(ssid, bytes):
        try:
            ssid = ssid.decode("utf-8", errors="replace")
        except Exception:
            ssid = repr(ssid)
    bssid = item.get("BSSID") or item.get("syncedBSSID")
    # Keep useful extras without dumping huge binary blobs
    extras = {}
    for k, v in item.items():
        if k in {"SSID_STR", "SSID", "BSSID"}:
            continue
        if isinstance(v, (bytes, memoryview)):
            extras[k] = f"<bytes:{len(v)}>"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            extras[k] = v
        elif hasattr(v, "isoformat"):
            extras[k] = v.isoformat()
        else:
            extras[k] = str(type(v).__name__)
    return {
        "ssid": ssid,
        "bssid": bssid,
        "security": item.get("SecurityMode") or item.get("SupportedSecurityTypes"),
        "hidden": item.get("HIDDEN_NETWORK") or item.get("Hidden"),
        "last_joined": str(item.get("lastJoined") or item.get("LastJoined") or item.get("joinedByUserAt") or ""),
        "last_auto_joined": str(
            item.get("lastAutoJoined") or item.get("LastAutoJoined") or item.get("joinedBySystemAt") or ""
        ),
        "source_plist": source,
        "extended": extras,
    }


def extract_wifi(
    backup: EncryptedBackup,
    *,
    archive: Archive,
    work: Path,
    export_dir: Path | None = None,
) -> CategoryReport:
    report = CategoryReport(category="wifi", status="failed")
    raw = work / "wifi"
    raw.mkdir(parents=True, exist_ok=True)
    all_networks: list[dict[str, Any]] = []
    parsed_sources = []

    for domain, rel in _CANDIDATES:
        dest = raw / rel.replace("/", "__")
        try:
            extract_file(backup, rel, dest, domain_like=domain)
        except Exception as exc:  # noqa: BLE001
            report.note(f"skip {domain}:{rel} ({exc})")
            continue
        try:
            with dest.open("rb") as f:
                data = plistlib.load(f)
            nets = _parse_networks(data, f"{domain}:{rel}")
            report.note(f"parsed {len(nets)} from {domain}:{rel} (top keys: {list(data)[:12] if isinstance(data, dict) else type(data)})")
            if nets:
                parsed_sources.append(f"{domain}:{rel}")
                all_networks.extend(nets)
        except Exception as exc:  # noqa: BLE001
            report.note(f"parse failed {rel}: {exc}")

    # Dedupe by ssid+bssid
    dedup: dict[str, dict] = {}
    for n in all_networks:
        key = f"{n.get('ssid')}|{n.get('bssid')}"
        dedup[key] = n
    networks = list(dedup.values())

    now = utc_now_iso()
    upserts = []
    export_items = []
    for i, n in enumerate(networks):
        nid = f"wifi:{(n.get('ssid') or 'unknown')}:{(n.get('bssid') or i)}"
        payload = {
            "id": nid,
            **n,
            "integrity": {"status": "ok" if n.get("ssid") else "partial", "notes": []},
            "extracted_at": now,
        }
        export_items.append(payload)
        upserts.append(
            {
                "id": nid,
                "ssid": n.get("ssid"),
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "updated_at": now,
            }
        )

    archive.upsert_many("wifi_networks", upserts, ["id", "ssid", "payload_json", "updated_at"])
    report.items_ok = len(export_items)
    report.artifacts = {}
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        out = export_dir / "wifi.json"
        out.write_text(
            json.dumps(export_items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report.artifacts["wifi_json"] = str(out)
    if export_items:
        report.status = "ok"
        report.note(f"Sources with networks: {', '.join(parsed_sources) or '(none)'}")
    else:
        report.status = "failed"
        report.note("No known networks parsed — iOS may have moved them or backup omitted them")
    return report
