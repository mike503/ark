from __future__ import annotations

from pathlib import Path
from typing import Any

from iphone_backup_decrypt import EncryptedBackup


def open_backup(backup_dir: Path, passphrase: str) -> EncryptedBackup:
    backup = EncryptedBackup(
        backup_directory=str(backup_dir),
        passphrase=passphrase,
    )
    backup.test_decryption()
    return backup


def extract_file(
    backup: EncryptedBackup,
    relative_path: str,
    dest: Path,
    *,
    domain_like: str | None = None,
) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "relative_path": relative_path,
        "output_filename": str(dest),
    }
    if domain_like is not None:
        kwargs["domain_like"] = domain_like
    backup.extract_file(**kwargs)
    return dest.is_file() and dest.stat().st_size >= 0


def extract_like(
    backup: EncryptedBackup,
    *,
    relative_paths_like: str,
    output_folder: Path,
    domain_like: str | None = None,
    preserve_folders: bool = True,
) -> int:
    output_folder.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "relative_paths_like": relative_paths_like,
        "output_folder": str(output_folder),
        "preserve_folders": preserve_folders,
        "incremental": True,
    }
    if domain_like is not None:
        kwargs["domain_like"] = domain_like
    return int(backup.extract_files(**kwargs))


def manifest_rows(
    backup: EncryptedBackup, where_sql: str, params: tuple = ()
) -> list[tuple[str, str]]:
    with backup.manifest_db_cursor() as cur:
        cur.execute(
            f"SELECT domain, relativePath FROM Files WHERE ({where_sql}) AND flags=1 "
            "ORDER BY domain, relativePath",
            params,
        )
        return list(cur.fetchall())
