# ark architecture

## Pieces

| Piece | Role |
|---|---|
| **agent** | Python CLI on the extract host: decrypt/extract MobileSync → local staging archive (+ local viewer). Batch `ark sync` to the server is next. Shipped as `ark-agent-<ver>-windows-amd64.exe` on GitHub Releases. |
| **server** | Node + Express + Eta + MySQL + Tabler UI, built on Tablerock. Shipped as `ghcr.io/<owner>/ark:<ver>`; consumers use `deploy/compose.yml` from the same release. |
| **data** | MySQL (metadata) + filesystem blobs under `ARK_DATA_DIR` (default `/data` in container) |

<a id="tablerock"></a>
**Tablerock** (internal, not-published-yet personal development framework) provides shared Node/Express/MySQL helpers (`@tablerock/*`). Local/dev expects `../tablerock`. CI clones it with private git secrets when building the GHCR image (see [releasing.md](releasing.md)). Publishing Tablerock (or switching off path deps) removes that requirement.

## Sync model

1. Agent runs wherever the MobileSync backup and encryption password exist.
2. Extract → **local staging** (fast on-disk upserts).
3. **Queue/sync** to ark: batch upsert by stable ids + blob sha256 checks + checkpoint — not one API call per message.
4. Ark MySQL + `/data/blobs` = database of record.
5. Soft-deletes and retained history live in ark; disaster recovery is backing up the server host.

iPhone backups are incrementally updated “current device state” folders, not point-in-time generations. History for kept data lives in ark (plus host backups), not in MobileSync.

## Auth

- Humans: session / UI login. Cookie signing secret is `options.session_secret` (auto-generated on first boot if missing).
- Agent: API key (bearer), hashed at rest in `api_keys`; optional `ARK_API_KEY` env bootstrap.

## Deploy

- **Consumers:** GitHub Release assets — `compose.yml` + `.env.example` pull a prebuilt GHCR image (no clone). See [releasing.md](releasing.md).
- **Developers:** root `compose.yml` builds `./server` with BuildKit `additional_contexts: tablerock: ../tablerock`.
- Server path deps: `file:../../tablerock/packages/*` (mirrored in the image as `/workspace/server` + `/workspace/tablerock`).
- Blobs: local filesystem under the data dir — no object store yet.
- Host backup is an ops concern on the ark host, not product sync.

The agent uses its own flags / future YAML config on the extract machine — not the server `.env`.

## Schema / migrations

**Server:** on every boot, `libraries/migrate.js` applies `db/schema.sql` (`CREATE TABLE IF NOT EXISTS`, etc.), then runs additive ensure helpers (`INFORMATION_SCHEMA` + `ALTER` when needed). Operators only create an empty database/user. `express-mysql-session` creates `sessions` itself. `session_secret` is written into `options` on first boot if missing.

**Agent (local SQLite staging):** opening an archive runs `CREATE TABLE IF NOT EXISTS` plus `Archive._migrate()` for new columns/indexes. `SCHEMA_VERSION` in `versioning.py` is stamped into `meta`; bump it when the layout contract changes.

No numbered migration files on either side.

## Non-goals (for now)

- Object store backend
- Rewriting the agent in Go/Rust
- Multi-writer conflict fancy (last-write-wins on guid upsert is fine)
