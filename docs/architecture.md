# ark architecture

## Pieces

| Piece | Role |
|---|---|
| **agent** | Python CLI on the extract host: decrypt/extract MobileSync → local staging → batch sync |
| **server** | Node + Express + Eta + MySQL + Tabler UI, built on Tablerock (internal, not-published-yet personal development framework) |
| **data** | MySQL (metadata) + filesystem blobs under `ARK_DATA_DIR` (default `/data` in container) |

## Sync model

1. Agent runs where the MobileSync backup and encryption password exist.
2. Extract → local staging (fast on-disk upserts).
3. Queue/sync to ark: batch upsert by stable ids + blob sha256 + checkpoint.
4. Ark MySQL + `/data/blobs` = database of record.
5. Soft-deletes and retained history live in ark; host backups cover disaster recovery.

## Auth

- Humans: session / UI login
- Agent: `Authorization: Bearer` API key (hashed in `api_keys`; optional `ARK_API_KEY` env bootstrap)

## Deploy

Docker Compose with host networking and BuildKit `additional_contexts: tablerock: ../tablerock` so `@tablerock/*` path deps resolve at image build time. A public release needs a published Tablerock (or another install source) instead of a local path checkout.
