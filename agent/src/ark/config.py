"""Load per-archive config.yml (viewer port, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


DEFAULT_VIEWER_PORT = 8765
DEFAULT_VIEWER_HOST = "127.0.0.1"


def load_config(archive_root: Path) -> dict[str, Any]:
    path = archive_root / "config.yml"
    if not path.is_file():
        return {}
    if yaml is None:
        raise SystemExit("PyYAML is required to read config.yml — pip install pyyaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"config.yml must be a mapping: {path}")
    return data


def viewer_settings(archive_root: Path, *, port: int | None = None, host: str | None = None) -> dict[str, Any]:
    cfg = load_config(archive_root)
    viewer = cfg.get("viewer") if isinstance(cfg.get("viewer"), dict) else {}
    # Allow flat keys too: port: 8765 at top level
    resolved_port = port
    if resolved_port is None:
        resolved_port = viewer.get("port", cfg.get("port", DEFAULT_VIEWER_PORT))
    resolved_host = host
    if resolved_host is None:
        resolved_host = viewer.get("host", cfg.get("host", DEFAULT_VIEWER_HOST))
    title = viewer.get("title") or cfg.get("title") or archive_root.name
    db = viewer.get("db") or cfg.get("db") or "archive/archive.sqlite"
    return {
        "host": str(resolved_host),
        "port": int(resolved_port),
        "title": str(title),
        "db": str(db),
        "raw": cfg,
    }
