# ark

Personal iPhone archive — durable store of messages, contacts, media, and related life data.

## Why?

For a decade-plus, TouchCopy was how I kept an unfurled copy of the useful bits of my phone — messages, contacts, media, and so on — in ordinary files I could browse and keep. Then it stopped working. No amount of fiddling would make it see the device again.

Each TouchCopy run also dumped a full fresh export. That was fine until you wanted a living archive: something that grows over time instead of rewriting the world on every plug-in. Because ark unfurls the backup first, it can treat each kind of item on its own terms — append new messages, skip blobs it already has, update contacts in place — instead of blasting out another complete copy.

That left a simple question: if the libraries exist to do what TouchCopy did, why not build something that stores everything in the formats I actually want, in places I control, and that I can keep appending to for years?

The intended loop is deliberately boring. Plug the phone in, click run. ark triggers the official local iPhone backup (required), then digs through that backup and files the pieces you care about into the right shapes and the right spots — an archive you own, not a black-box export.

## Layout (monorepo)

```
ark/
  agent/          # Python CLI — extract from iPhone backup, local staging, sync to ark
  server/         # API + web UI
  compose.yml     # Dockerized server; data on volume (/data)
  docs/           # architecture, sync protocol
  .helpers/       # restart + DB helpers
```

### Quick start (server)

```sh
cp .env.example .env   # set DATABASE_* and SESSION_SECRET
# create MySQL database/user `ark`, then:
cat server/db/schema.sql | .helpers/run-db-command.sh
cd server && npm install && cd ..
docker compose up -d --build
curl -s localhost:3010/api/health
```

Agent API key smoke: set `ARK_API_KEY` in `.env`, or `cd server && npm run create-api-key -- laptop`.

## Architecture

| Piece | Choice |
|---|---|
| Agent | Python (Windows exe later via PyInstaller one-dir + ffmpeg) |
| Server | Tablerock + Express + Eta + MySQL + Tabler UI |
| Deploy | Docker Compose; Tablerock via BuildKit `additional_contexts` (local path dep for now) |
| Blobs | Local filesystem under the data dir — no object store yet |
| Host backup | Ops concern on the machine that hosts ark (not part of product sync) |
| Data dir | `ARK_DATA_DIR` (env), default **`/data`** in container; host bind-mounts elsewhere |

**Tablerock** (internal, not-published-yet personal development framework) provides shared Node/Express/MySQL helpers used by the server. A public release of ark will need Tablerock published (or another install path for `@tablerock/*`). Until then, development expects a local checkout at `../tablerock`.

### Sync model

1. Agent runs wherever the MobileSync backup and encryption password exist.
2. Extract → **local staging** (fast on-disk upserts).
3. **Queue/sync** to ark: batch upsert by stable ids + blob sha256 checks + checkpoint — not one API call per message.
4. Ark MySQL + `/data/blobs` = database of record.
5. Soft-deletes and retained history live in ark; disaster recovery is backing up the server host.

iPhone backups are incrementally updated “current device state” folders, not point-in-time generations. History for kept data lives in ark (plus host backups), not in MobileSync.

### Config (agent)

```yaml
ark:
  url: https://ark.example.com
  api_key: "…"                   # or env ARK_API_KEY
```

Backup encryption password never leaves the extract machine.

### Auth (server)

- Humans: session / UI login
- Agent: API key (bearer), hashed at rest

## Non-goals (for now)

- Object store backend
- Rewriting the agent in Go/Rust
- Multi-writer conflict fancy (last-write-wins on guid upsert is fine)
