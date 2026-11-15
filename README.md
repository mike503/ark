# ark

Opinionated personal iPhone archive — plug it in, back it up, keep it in useful formats forever.

Durable store of messages, contacts, media, and related life data.

## Why?

For a decade-plus, TouchCopy was how I kept an unfurled copy of the useful bits of my phone — messages, contacts, media, and so on — in ordinary files I could browse and keep. Then it stopped working. No amount of fiddling would make it see the device again.

Each TouchCopy run also dumped a full fresh export. That was fine until you wanted a living archive: something that grows over time instead of rewriting the world on every plug-in. Because ark unfurls the backup first, it can treat each kind of item on its own terms — append new messages, skip blobs it already has, update contacts in place — instead of blasting out another complete copy.

That left a simple question: if the libraries exist to do what TouchCopy did, why not build something that stores everything in the formats I actually want, in places I control, and that I can keep appending to for years?

The intended loop is deliberately boring. Plug the phone in, click run. ark triggers the official local iPhone backup (required), then digs through that backup and files the pieces you care about into the right shapes and the right spots — an archive you own, not a black-box export.

## Status

Early scaffold. The **server** boots (health check, login stub, agent API-key stub). The **agent** (extract → stage → sync) is not wired yet. Windows one-click / `.exe` packaging comes later.

## Layout

```
ark/
  agent/       # Python CLI (extract, local staging, sync) — future Windows release
  server/      # API + web UI (Docker)
  compose.yml  # server deploy
  docs/        # architecture, sync protocol, deeper design
  .helpers/    # local restart + DB helpers
```

## Usage

### Server

Requirements: Docker, a MySQL/MariaDB database, and a local [Tablerock](docs/architecture.md#tablerock) checkout at `../tablerock` (until Tablerock is published).

```sh
cp .env.example .env          # set DATABASE_* (and optional ARK_API_KEY)
# create MySQL database/user matching .env, then:
cat server/db/schema.sql | .helpers/run-db-command.sh
cd server && npm install && cd ..
docker compose up -d --build
curl -s localhost:3010/api/health
```

Create a UI admin (from `server/`):

```sh
npm run create-admin -- you@example.com 'your-password'
```

Optional agent API key (prints plaintext once):

```sh
npm run create-api-key -- laptop
# or set ARK_API_KEY in .env for a bootstrap key
```

Session cookie signing uses a `session_secret` row in the `options` table (created automatically on first boot). Database credentials and ports stay in `.env`.

### Agent

Not ready yet. Planned config:

```yaml
ark:
  url: https://ark.example.com
  api_key: "…"    # or env ARK_API_KEY
```

The iPhone backup encryption password never leaves the machine that runs the agent.

## Docs

- [Architecture](docs/architecture.md) — components, sync model, auth, deploy notes
- [Sync protocol](docs/sync-protocol.md) — batch/idempotent sync (draft)
