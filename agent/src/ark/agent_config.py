"""Load agent.yml (server URL, auto_sync, optional defaults)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML is required to read agent.yml — pip install pyyaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"agent.yml must be a mapping: {path}")
    return data


def find_agent_config(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    candidates = [
        Path.cwd() / "agent.yml",
        Path(__file__).resolve().parents[2] / "agent.yml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_agent_config(explicit: Path | None = None) -> dict[str, Any]:
    """
    Resolved agent settings.

    Keys: path, url, api_key, auto_sync, backup, out, raw
    """
    path = find_agent_config(explicit)
    raw = _load_yaml(path) if path else {}
    ark_block = raw.get("ark") if isinstance(raw.get("ark"), dict) else {}

    url = os.environ.get("ARK_URL") or raw.get("url") or ark_block.get("url")
    api_key = (
        os.environ.get("ARK_API_KEY")
        or raw.get("api_key")
        or ark_block.get("api_key")
    )

    auto_sync_raw = raw.get("auto_sync", True)
    if isinstance(auto_sync_raw, str):
        auto_sync = auto_sync_raw.strip().lower() in {"1", "true", "yes", "on"}
    elif auto_sync_raw is None:
        auto_sync = True
    else:
        auto_sync = bool(auto_sync_raw)

    backup = raw.get("backup")
    out = raw.get("out")

    return {
        "path": path,
        "url": str(url).rstrip("/") if url else None,
        "api_key": str(api_key) if api_key else None,
        "auto_sync": auto_sync,
        "backup": Path(backup) if backup else None,
        "out": Path(out) if out else None,
        "raw": raw,
    }
