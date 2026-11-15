# Agent notes — ark

## Product

- Official name: **ark**.
- Monorepo: Python **agent** (extract + local staging + sync) + **server** (API + UI).
- Data: MySQL + filesystem blobs. Env **`ARK_DATA_DIR`**, container default `/data`, Docker `-v` from host.
- Server stack uses **Tablerock** (internal, not-published-yet personal development framework) via path deps until it is published.

## Conventions

- Deploy: `compose.yml` BuildKit `additional_contexts: tablerock: ../tablerock`; server path deps `file:../../tablerock/packages/*`.
- UTC datetimes; MySQL via `@tablerock/standard/db`.
- Sync API must be batch/idempotent (upsert by id, blob by sha256). No per-message exists round-trips.
- Secrets: API keys for agents; iTunes backup password stays on extract hosts only. UI `session_secret` lives in `options` (auto-generated on boot) — not `.env`.
- **Server schema auto-migrates on boot** (`libraries/migrate.js` runs `db/schema.sql` CREATE IF NOT EXISTS, then additive ensure* helpers). No numbered migration files; no manual schema step for operators.
- Agent SQLite staging also auto-migrates on open (`Archive._migrate`).
- Prefer `.helpers/` for restart / DB; never hardcode DB credentials in shell.
- **Git:** commit and push to `main` only (no feature branches / MRs unless the user asks).
- Keep docs/README publicly presentable: no private hostnames, no other personal project names, no “today vs old tool” framing.

## First milestones

1. Scaffold `server/` Docker + `/data` volume + health endpoint + API-key stub.
2. Minimal schema (runs, messages, blobs meta, overlays/soft-delete).
3. Agent extract/staging/viewer ported; implement `ark sync` against local staging + server sync API.
4. Optional import path for older local archives.
5. Release pipeline: GHCR image + Windows exe + deploy compose (see docs/releasing.md).

## Context

See [README.md](./README.md).
