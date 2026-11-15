# ark architecture

## Pieces

| Piece | Role |
|---|---|
| **agent** | Python CLI on the extract host: decrypt/extract MobileSync → local staging → batch sync. Intended Windows one-click / `.exe` release later. |
| **server** | Node + Express + Eta + MySQL + Tabler UI, built on Tablerock. Deployed with Docker Compose. |
| **data** | MySQL (metadata) + filesystem blobs under `ARK_DATA_DIR` (default `/data` in container) |

<a id="tablerock"></a>
**Tablerock** (internal, not-published-yet personal development framework) provides shared Node/Express/MySQL helpers (`@tablerock/*`). A public release of ark needs Tablerock published (or another install path). Until then, development expects a local checkout at `../tablerock`.

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

- `compose.yml` at the repo root: host networking, data volume, BuildKit `additional_contexts: tablerock: ../tablerock`.
- Server path deps: `file:../../tablerock/packages/*` (mirrored in the image as `/workspace/server` + `/workspace/tablerock`).
- Blobs: local filesystem under the data dir — no object store yet.
- Host backup (kopia/borg/etc.) is an ops concern on the ark host, not product sync.

Root `.env` + `compose.yml` match “clone the repo and run the server from here.” The agent will use its own config (YAML / env), not that file.

## Schema / migrations

There is **no** automatic schema migrator on boot yet. Apply `server/db/schema.sql` with `.helpers/run-db-command.sh` (or equivalent). `express-mysql-session` creates the `sessions` table itself.

When the domain schema starts changing often, prefer blogs-style **idempotent ensure-on-boot** helpers (check `INFORMATION_SCHEMA`, `ALTER` if missing) rather than numbered migration files — see project `AGENTS.md`.

## Non-goals (for now)

- Object store backend
- Rewriting the agent in Go/Rust
- Multi-writer conflict fancy (last-write-wins on guid upsert is fine)
