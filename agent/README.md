# ark agent

Python CLI: extract from an encrypted iPhone backup → local staging → sync to the ark server.

Browsing and media conversion happen on the **server UI**, not here.

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
# password: "…"          # optional; same sensitivity as api_key
```

Env overrides: `ARK_URL`, `ARK_API_KEY`, `ARK_BACKUP_PASSWORD`.

Backup password: `ARK_BACKUP_PASSWORD` or `agent.yml` `password:`, else interactive prompt. Never leaves this machine.

## Commands

```sh
ark status
ark --backup /path/to/MobileSync/Backup/<udid> --out ./staging all
ark --backup … --no-sync messages    # extract only
ark sync --out ./staging             # sync only
```

## Dev

```sh
cd agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp agent.yml.example agent.yml
ark status
```

## Windows release

GitHub Actions builds `ark-agent-<version>-windows-amd64.exe` and attaches `agent.yml.example` on the same release as the server compose assets.
