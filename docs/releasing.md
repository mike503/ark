# Releasing ark

One GitHub Release ships **aligned** server + agent artifacts:

| Asset | Purpose |
|---|---|
| `ghcr.io/<owner>/ark:<version>` (+ `:latest`) | Server container image |
| `compose.yml` | Pulls that image (no clone / no build) |
| `.env.example` | Server env template |
| `schema.sql` | Baseline MySQL schema (apply once) |
| `ark-agent-<version>-windows-amd64.exe` | Windows extract/stage agent |
| `ark-agent.config.example.yml` | Optional local viewer config sample |

## Tag a release

```sh
git tag v0.1.0
git push origin v0.1.0
```

Or run the **Release** workflow manually (`workflow_dispatch`) with a tag like `v0.1.0`.

## Tablerock and GHCR builds

The server image depends on **Tablerock** (internal, not-published-yet personal development framework). Public runners cannot see a private sibling checkout, so CI clones Tablerock with secrets:

| Secret | Example |
|---|---|
| `TABLEROCK_GIT_URL` | `https://gitlab.com/mike503/tablerock.git` |
| `TABLEROCK_GIT_TOKEN` | PAT / deploy token with `read_repository` |

Local docker still uses Compose `additional_contexts: tablerock: ../tablerock`.

Longer-term options (when you want fewer secrets):

1. Publish `@tablerock/*` to a registry and switch `package.json` off path deps.
2. Mirror Tablerock to a private GitHub repo and use `actions/checkout` with a fine-scoped token.
3. Vendor a snapshot of Tablerock into this repo (works, but stale copies).

Until one of those lands, the clone-via-secret approach is the pragmatic path for GHCR.

## Consumer install (server)

```sh
# from the GitHub Release assets:
cp .env.example .env   # edit DATABASE_*
docker compose up -d
curl -s localhost:3010/api/health
```

Apply the release `schema.sql` once against your MySQL database before first useful boot.

## Consumer install (agent)

Download `ark-agent-*-windows-amd64.exe`, point it at a MobileSync backup folder, write a local staging archive with `all` / per-category commands. `ark sync` to the server is not implemented yet.
