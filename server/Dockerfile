# syntax=docker/dockerfile:1
#
# Build with Compose (preferred):
#   docker compose build
#
# Requires BuildKit additional context `tablerock` → ../tablerock
# (Tablerock: internal, not-published-yet personal development framework).
# package.json uses file:../../tablerock/packages/*; image layout mirrors
# that with /workspace/server + /workspace/tablerock.

FROM node:24-bookworm-slim AS deps

WORKDIR /workspace/server

RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 make g++ \
  && rm -rf /var/lib/apt/lists/*

COPY --from=tablerock . /workspace/tablerock
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM node:24-bookworm-slim

WORKDIR /workspace/server

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
ENV APP_PORT=3010
ENV ARK_DATA_DIR=/data

COPY --from=tablerock . /workspace/tablerock
COPY --from=deps /workspace/server/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY server.js ./
COPY config ./config
COPY db ./db
COPY libraries ./libraries
COPY routes ./routes
COPY views ./views
COPY public ./public
COPY scripts ./scripts

RUN mkdir -p /data/blobs logs tmp \
  && chown -R node:node /data /workspace/server/logs /workspace/server/tmp

USER node
EXPOSE 3010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.APP_PORT||3010)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
