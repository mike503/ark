# ark

Opinionated personal iPhone archive — plug it in, back it up, keep it in useful formats forever.

Durable store of messages, contacts, media, and related life data.

## Why?

For a decade-plus, TouchCopy was how I kept an unfurled copy of the useful bits of my phone — messages, contacts, media, and so on — in ordinary files I could browse and keep. Then it stopped working. No amount of fiddling would make it see the device again.

Each TouchCopy run also dumped a full fresh export. That was fine until you wanted a living archive: something that grows over time instead of rewriting the world on every plug-in. Because ark unfurls the backup first, it can treat each kind of item on its own terms — append new messages, skip blobs it already has, update contacts in place — instead of blasting out another complete copy.

That left a simple question: if the libraries exist to do what TouchCopy did, why not build something that stores everything in the formats I actually want, in places I control, and that I can keep appending to for years?

The intended loop is deliberately boring. Plug the phone in, click run. ark triggers the official local iPhone backup (required), then digs through that backup and files the pieces you care about into the right shapes and the right spots — an archive you own, not a black-box export.

## Usage

Download assets from the latest [GitHub Release](https://github.com/mike503/ark/releases) (server image + agent exe + config samples, version-aligned).

### Server

1. Grab `compose.yml` and `.env.example` from the release.
2. `cp .env.example .env` and set `DATABASE_*`.
3. Create an empty MySQL database + user (grants to create/alter tables).
4. `docker compose up -d` (pulls `ghcr.io/mike503/ark:<version>`).
5. Schema migrates on boot — `curl -s localhost:3010/api/health`

### Agent

1. Grab `ark-agent-<version>-windows-amd64.exe` and `agent.yml.example`.
2. Copy to `agent.yml`; set `url` / `api_key` (`auto_sync: true` by default). Optional backup password via `password` in that file, or `ARK_BACKUP_PASSWORD` (keep private).
3. Run against your MobileSync backup folder. Password never leaves the extract machine.

After extract, the agent attempts sync automatically. The sync API is still early; extract/staging already work.

## Docs

- [Architecture](docs/architecture.md)
- [Development](docs/development.md) (clone, local server/agent, Tablerock)
- [Releasing](docs/releasing.md)
- [Sync protocol](docs/sync-protocol.md) (draft)
- [Data model](docs/DATA_MODEL.md) (local staging archive)
