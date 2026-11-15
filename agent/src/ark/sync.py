"""Push local staging archive to the ark server (batch, idempotent)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def sync_staging(staging_root: Path, agent_cfg: dict[str, Any]) -> int:
    """
    Upload staging archive to the server.

    Returns process-style exit code: 0 ok, 1 failure, 2 not implemented / skipped.
    """
    url = agent_cfg.get("url")
    api_key = agent_cfg.get("api_key")
    cfg_path = agent_cfg.get("path")

    print(f"\n=== sync ===")
    print(f"Staging: {staging_root}")
    if cfg_path:
        print(f"Config:  {cfg_path}")
    if url:
        print(f"Server:  {url}")
    else:
        print("Server:  (not set — set url in agent.yml or ARK_URL)")
    if not api_key:
        print("API key: (not set — set api_key in agent.yml or ARK_API_KEY)")

    archive = staging_root / "archive" / "archive.sqlite"
    if not archive.is_file():
        print(f"No staging archive at {archive}")
        return 1

    print(
        "Sync is not implemented yet (server sync API still landing).\n"
        "Extract/staging completed; nothing was uploaded."
    )
    return 2
