# Development

Working from a git clone (not release artifacts). For the product overview and consumer install, see the [README](../README.md).

## Layout

```
ark/
  agent/       # Python CLI — extract, local staging, sync
  server/      # API + web UI
  deploy/      # Consumer compose + env (also attached to releases)
  compose.yml  # Dev compose (builds from ./server + local Tablerock)
  docs/
  .helpers/
```

## Server

Requires a local [Tablerock](architecture.md#tablerock) checkout at `../tablerock`.

```sh
cp .env.example .env          # set DATABASE_*
cd server && npm install && cd ..
docker compose up -d --build  # migrates schema on boot
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

Helpers: `.helpers/restart-app-server.sh`, `.helpers/run-db-command.sh` (ad-hoc SQL; schema normally migrates on boot).

## Agent

```sh
cd agent && python -m venv .venv && source .venv/bin/activate
pip install -e .
cp agent.yml.example agent.yml   # url, api_key, auto_sync: true
ark status
ark --backup /path/to/MobileSync/Backup/<udid> --out ./staging all
# → extract, then attempts sync (stub until server API lands)
ark view --root ./staging
```

Password: `--password-file`, `--password`, or prompt. Never sent to the server.

More agent detail: [agent/README.md](../agent/README.md).

## Releases

How tags, GHCR, Windows exe, and Tablerock CI secrets work: [releasing.md](releasing.md).
