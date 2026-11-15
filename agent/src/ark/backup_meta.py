"""Read Apple backup Info.plist / Status.plist metadata."""

from __future__ import annotations

import plistlib
from datetime import datetime
from pathlib import Path
from typing import Any


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(microsecond=0).isoformat()
    return str(v)


def read_backup_info(backup_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"backup_path": str(backup_dir)}
    info_path = backup_dir / "Info.plist"
    status_path = backup_dir / "Status.plist"
    if info_path.is_file():
        try:
            info = plistlib.loads(info_path.read_bytes())
        except Exception:
            info = {}
        out.update(
            {
                "device_name": info.get("Device Name") or info.get("Display Name"),
                "product_name": info.get("Product Name"),
                "product_type": info.get("Product Type"),
                "product_version": info.get("Product Version"),
                "build_version": info.get("Build Version"),
                "serial_number": info.get("Serial Number"),
                "unique_identifier": info.get("Unique Identifier"),
                "backup_finished_at": _iso(info.get("Last Backup Date")),
                "phone_number": info.get("Phone Number") or info.get("Phone Number 2"),
            }
        )
    if status_path.is_file():
        try:
            status = plistlib.loads(status_path.read_bytes())
        except Exception:
            status = {}
        out.update(
            {
                "backup_started_at": _iso(status.get("Date")),
                "snapshot_state": status.get("SnapshotState"),
                "is_full_backup": status.get("IsFullBackup"),
                "backup_state": status.get("BackupState"),
            }
        )
    return out
