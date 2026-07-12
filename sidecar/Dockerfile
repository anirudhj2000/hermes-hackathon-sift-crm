# Sift WhatsApp sidecar — Baileys bridge.
# Build from the REPO ROOT: docker build -f sidecar/Dockerfile .
# WhatsApp session state lives in /app/auth_state — persist it (compose
# volume locally; R2/DO storage on Cloudflare, where disk is ephemeral and
# a lost auth_state means re-pairing).

FROM node:22-slim

WORKDIR /app

COPY sidecar/package.json sidecar/package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev

COPY sidecar/ ./

EXPOSE 3001

CMD ["node", "index.js"]
