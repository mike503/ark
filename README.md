# ark

Opinionated personal iPhone archive — plug it in, back it up, keep it in useful formats forever.

Durable store of messages, contacts, media, and related life data.

## Why?

For a decade-plus, TouchCopy was how I kept an unfurled copy of the useful bits of my phone — messages, contacts, media, and so on — in ordinary files I could browse and keep. Then it stopped working. No amount of fiddling would make it see the device again.

Each TouchCopy run also dumped a full fresh export. That was fine until you wanted a living archive: something that grows over time instead of rewriting the world on every plug-in. Because ark unfurls the backup first, it can treat each kind of item on its own terms — append new messages, skip blobs it already has, update contacts in place — instead of blasting out another complete copy.

That left a simple question: if the libraries exist to do what TouchCopy did, why not build something that stores everything in the formats I actually want, in places I control, and that I can keep appending to for years?

The intended loop is deliberately boring. Plug the phone in, click run. ark triggers the official local iPhone backup (required), then digs through that backup and files the pieces you care about into the right shapes and the right spots — an archive you own, not a black-box export.

## Status

- **Agent:** extract + local staging + local viewer work today. After extract, sync runs automatically when `auto_sync: true` (default); the sync API itself is not wired yet.
- **Server:** boots (health, login stub, agent API-key stub). Domain sync API / schema still early.
- **Releases:** GitHub Release = GHCR server image + Windows agent `.exe` + `compose.yml` / `.env.example` (aligned versions). See [docs/releasing.md](docs/releasing.md).

## Layout

```
ark/
  agent/       # Python CLI — extract, local staging, viewer (packaged as a Windows .exe in releases)
  server/      # API + web UI (GHCR image in releases)
  deploy/      # Consumer compose + env (also attached to releases)
  compose.yml  # Dev compose (builds from ./server + local Tablerock)
  docs/
  .helpers/    # helper scripts for agents
```

## Usage

### Server

1. Download `compose.yml` and `.env.example` from the [GitHub Release](https://github.com/mike503/ark/releases).
2. `cp .env.example .env` and set `DATABASE_*`.
3. Create an empty MySQL database + user (grants to create/alter tables).
4. `docker compose up -d` (pulls `ghcr.io/mike503/ark:<version>`).
5. Schema is applied automatically on boot. `curl -s localhost:3010/api/health`

### Agent

Windows: release `ark-agent-<version>-windows-amd64.exe` + `agent.yml.example`.

Password: `--password-file`, `--password`, or prompt. Never sent to the server.

## Docs

- [Architecture](docs/architecture.md)
- [Sync protocol](docs/sync-protocol.md) (draft)
- [Data model](docs/DATA_MODEL.md) (local staging archive)
- [Releasing](docs/releasing.md) (GHCR, Windows exe, Tablerock CI secrets)
