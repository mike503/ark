from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .versioning import SCHEMA_VERSION, __version__


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  chat_id TEXT,
  chat_identifier TEXT,
  date TEXT,
  from_addr TEXT,
  to_addrs_json TEXT,
  text TEXT,
  service TEXT,
  status_json TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  message_id TEXT,
  filename TEXT,
  mime_type TEXT,
  byte_size INTEGER,
  sha256 TEXT,
  blob_path TEXT,
  verified INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voicemails (
  id TEXT PRIMARY KEY,
  date TEXT,
  from_addr TEXT,
  to_addr TEXT,
  duration_sec INTEGER,
  audio_path TEXT,
  audio_sha256 TEXT,
  verified INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voicememos (
  id TEXT PRIMARY KEY,
  title TEXT,
  date TEXT,
  audio_path TEXT,
  audio_sha256 TEXT,
  verified INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  apple_row_id INTEGER,
  first_seen_at TEXT,
  last_seen_at TEXT,
  on_device INTEGER NOT NULL DEFAULT 1,
  removed_from_device_at TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wifi_networks (
  id TEXT PRIMARY KEY,
  ssid TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whatsapp_messages (
  id TEXT PRIMARY KEY,
  date TEXT,
  from_jid TEXT,
  to_jid TEXT,
  text TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY,
  chat_id TEXT,
  chat_identifier TEXT,
  thread_key TEXT,
  phone_display_name TEXT,
  is_group INTEGER NOT NULL DEFAULT 0,
  group_photo_path TEXT,
  group_photo_guid TEXT,
  participants_json TEXT,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS overlays (
  id TEXT PRIMARY KEY,
  module TEXT NOT NULL,
  item_id TEXT NOT NULL,
  display_name TEXT,
  notes TEXT,
  ignored INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  tool_version TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  backup_id TEXT,
  commands_json TEXT,
  status TEXT,
  diagnostic INTEGER NOT NULL DEFAULT 0
);
"""


class Archive:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self._migrate()
        # Stamp current layout + tooling; extract runs also record per-run versions.
        self.set_meta("schema_version", str(SCHEMA_VERSION))
        self.set_meta("tool_version", __version__)
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns/indexes/tables introduced after the first schema without wiping data."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(contacts)")}
        alters = []
        if "apple_row_id" not in cols:
            alters.append("ALTER TABLE contacts ADD COLUMN apple_row_id INTEGER")
        if "first_seen_at" not in cols:
            alters.append("ALTER TABLE contacts ADD COLUMN first_seen_at TEXT")
        if "last_seen_at" not in cols:
            alters.append("ALTER TABLE contacts ADD COLUMN last_seen_at TEXT")
        if "on_device" not in cols:
            alters.append("ALTER TABLE contacts ADD COLUMN on_device INTEGER NOT NULL DEFAULT 1")
        if "removed_from_device_at" not in cols:
            alters.append("ALTER TABLE contacts ADD COLUMN removed_from_device_at TEXT")
        for sql in alters:
            self.conn.execute(sql)
        # Thread list aggregates GROUP BY chat_id / chat_identifier.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, chat_identifier)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date)"
        )
        # runs may already exist via SCHEMA on new DBs; IF NOT EXISTS is fine on old DBs.
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              tool_version TEXT NOT NULL,
              schema_version INTEGER NOT NULL,
              backup_id TEXT,
              commands_json TEXT,
              status TEXT,
              diagnostic INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def close(self) -> None:
        self.conn.close()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def begin_run(
        self,
        *,
        started_at: str,
        tool_version: str,
        schema_version: int,
        backup_id: str,
        commands: list[str],
        diagnostic: bool = False,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO runs(
              started_at, tool_version, schema_version, backup_id, commands_json, diagnostic
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                started_at,
                tool_version,
                schema_version,
                backup_id,
                json.dumps(commands),
                1 if diagnostic else 0,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, finished_at: str, status: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
            (finished_at, status, run_id),
        )
        self.conn.commit()

    def upsert_many(self, table: str, rows: Iterable[dict[str, Any]], columns: list[str]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        placeholders = ",".join("?" for _ in columns)
        col_list = ",".join(columns)
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c != "id")
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        self.conn.executemany(sql, [tuple(r.get(c) for c in columns) for r in rows])
        self.conn.commit()
        return len(rows)

    def export_json(self, table: str, path: Path, *, order_by: str | None = None) -> int:
        sql = f"SELECT payload_json FROM {table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        items = [json.loads(r[0]) for r in self.conn.execute(sql)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return len(items)

    def export_messages_jsonl(self, path: Path) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with path.open("w", encoding="utf-8") as f:
            for (payload,) in self.conn.execute(
                "SELECT payload_json FROM messages ORDER BY date, id"
            ):
                f.write(payload if payload.endswith("\n") else payload + "\n")
                # payload_json is stored as compact json string without newline usually
                n += 1
        return n


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_blob(src: Path, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    dest.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()
