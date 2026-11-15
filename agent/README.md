# ark agent

Python CLI: extract from an encrypted iPhone backup → local staging archive → sync to the ark server.

## Flow

1. **Extract** into a local staging archive (sqlite + blobs) — append-only / upsert by stable ids.
2. **Sync** to the ark server immediately afterward when `auto_sync: true` (default in `agent.yml`).

`ark sync` alone re-pushes staging without extracting. Use `--no-sync` on extract to skip the upload.

Sync API is not wired yet; extract still works, and auto-sync currently reports “not implemented” without failing the extract.

## Config

Copy `agent.yml.example` → `agent.yml` (next to the exe, or pass `--config`):

```yaml
url: https://ark.example.com
api_key: "…"
auto_sync: true
```

Env overrides: `ARK_URL`, `ARK_API_KEY`. Backup encryption password never leaves this machine (`--password-file` / `--password` / prompt).

Optional per-staging viewer settings: `staging/config.yml` (see `config.example.yml`).

## Commands

```sh
ark status
ark --backup /path/to/MobileSync/Backup/<udid> --out ./staging all
ark --backup … --no-sync messages    # extract only
ark sync --out ./staging             # sync only
ark view --root ./staging
```

## Dev

```sh
cd agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp agent.yml.example agent.yml   # edit url / api_key
ark status
```

## Windows release

GitHub Actions builds `ark-agent-<version>-windows-amd64.exe` and attaches `agent.yml.example` on the same release as the server compose assets.

Browser-friendly media conversion (ffmpeg, etc.) belongs on the **server UI**, not the agent. The agent stores originals as extracted. `ark view` is only a local staging convenience and may degrade without ffmpeg for odd formats.
