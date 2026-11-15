# Sync protocol (draft)

Batch, idempotent. No per-message exists round-trips.

## Principles

- Upsert messages/contacts/etc. by stable id (guid).
- Blobs addressed by sha256; skip upload when server already has the hash.
- Checkpoint progress so retries resume cleanly.
- Last-write-wins on guid upsert is fine for now.

## Endpoints (planned)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Public liveness |
| GET | `/api/agent/whoami` | Bearer auth smoke check (stub exists) |
| POST | `/api/sync/batch` | Upsert entities + declare blob hashes (TODO) |
| PUT | `/api/sync/blobs/:sha256` | Upload missing blob bytes (TODO) |

Exact payload shapes land with the domain schema (runs, messages, blobs meta, overlays).
